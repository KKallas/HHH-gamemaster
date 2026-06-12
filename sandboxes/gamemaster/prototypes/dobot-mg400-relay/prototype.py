"""
Dobot MG400 Relay — two-arm game-master relay server (a Flask blueprint).

This machine OWNS TWO MG400 connections — one per side ("purple" / "green") — and
relays each side's move/pump commands to ITS OWN arm. The two sides are fully
INDEPENDENT and drive concurrently: purple's controller drives the purple arm
while green's controller drives the green arm, with no blocking between sides.

Per SIDE the relay still arbitrates: a side must *acquire* its arm and gets an
opaque token + a lease; a per-side watchdog smooth-stops that side's arm if its
holder stops heartbeating. This stops two tabs of the SAME side from fighting,
but it NEVER blocks across sides.

Every command for a side passes the same safety filter (joint limits / reachable
workspace clamp mirrored from the joint and cartesian prototypes) before it
reaches that side's arm.

A single GLOBAL E-STOP latch stops BOTH arms; `clear` un-latches it and clears
both arms' errors.

Loaded by hub.py; registered under /p/dobot-mg400-relay. No app.run() of its own —
it only runs inside the hub server. It needs each arm reachable on the network to
move it; without a robot the operator GUI + every endpoint still work and
move/pump fail cleanly with "Not connected".

Put each robot in API mode first — see ../../docs/operations/dobot-api-mode.md.
Safety: keep the hardware E-stop within reach; start with a low speed.
"""

import math
import os
import sys
import threading
import time
from collections import deque

from flask import Blueprint, jsonify, request, send_from_directory

import live   # shared push helper (prototypes/live.py)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # so the sibling driver imports cleanly
from relay_arm import DobotMG400, DobotError  # noqa: E402

MANIFEST = {
    "name": "Dobot MG400 Relay",
    "description": "Two-arm game-master relay: owns the purple and green MG400s "
                   "and routes each side's commands to its OWN arm. The sides "
                   "drive concurrently. Remote controllers connect via its HTTP API.",
    "default_page": "",
    "pages": [{"path": "", "label": "Relay (operator)"}],
}
bp = Blueprint("dobot_mg400_relay", __name__)

# ---- configuration --------------------------------------------------------
# Per-side arm IPs (operator-editable in the GUI / via /api/connect).
DEFAULT_IPS = {"purple": "192.168.1.6", "green": "192.168.1.7"}

SIDES = ("purple", "green")


@bp.before_request
def _enforce_team_side():
    """Players reach this machine through the hub's shared-API door, which puts
    their authenticated roles in request.environ["hhh.roles"]. A request whose
    roles are ONLY team roles may target ONLY its own side — so a hand-edited
    green controller can never acquire/move/kick the purple arm. Operator
    (gamemaster) sessions and engine deployments without the auth layer are
    unrestricted."""
    if request.method != "POST":
        return None
    roles = request.environ.get("hhh.roles")
    if roles is None:               # engine without the auth layer
        return None
    teams = {r for r in roles if r in SIDES}
    if not teams or roles - teams:  # operator/admin role present → unrestricted
        return None
    side = (request.get_json(silent=True) or {}).get("side")
    if side is not None and side not in teams:
        return jsonify({"ok": False,
                        "error": f"side '{side}' is not your team"}), 403
    return None
MODES = ("joint", "cartesian")
LEASE_SECS = 2.0          # holder must heartbeat within this or it's dropped
WATCHDOG_HZ = 5.0         # how often the watchdog checks each side's lease
COMMAND_LOG_MAX = 160     # recent relay/operator + robot command events

# Per-joint angle limits (degrees) — mirrored from joint-angles-test/prototype.py.
JOINT_LIMITS = {
    "j1": [-160.0, 160.0],   # base rotation
    "j2": [-25.0, 85.0],     # arm joint 1
    "j3": [-25.0, 105.0],    # arm joint 2
    "j4": [-160.0, 160.0],   # end rotation (R)
}

# Approximate MG400 workspace — mirrored EXACTLY from cartesian-xyz-test/prototype.py.
# The reachable area is an ANNULUS, so X/Y are clamped to a min/max radius too.
WORKSPACE = {
    "x": [-450.0, 450.0],
    "y": [-450.0, 450.0],
    "z": [-150.0, 230.0],
    "r": [-160.0, 160.0],
}
RADIUS_MIN = 150.0   # mm — inside this the arm can't reach (too folded)
RADIUS_MAX = 440.0   # mm — max horizontal reach

# Conservative Tag Game defaults: 10% speed with a gentler ramp/brake profile.
MAX_JOINT_VEL = 12.0    # deg/s
MAX_LIN_VEL = 20.0      # mm/s
MAX_ANG_VEL = 9.0       # deg/s
RAMP_SECS = 0.50        # follower ramp/brake time -> accel = vel-cap / ramp-time

# Air pump box (two-line suck/blow model — see joint prototype).
SUCK_DO_INDEX = 2
BLOW_DO_INDEX = 1

# Per-side arm connections, guarded by _arm_locks[side] while reconnecting.
_robots = {s: None for s in SIDES}
_arm_locks = {s: threading.Lock() for s in SIDES}
# Sampled state (live feedback + lease seconds tick down), so the SSE stream
# re-snapshots on a short interval rather than on a bump. See prototypes/live.py.
_live = live.LiveState()
_command_log = deque(maxlen=COMMAND_LOG_MAX)
_command_log_lock = threading.Lock()
_command_log_seq = 0


# ---- arbitration state -----------------------------------------------------
# Guarded by _arb_lock. NEVER do blocking arm socket I/O while holding this lock;
# read what's needed under it, release, then talk to the arm.
_arb_lock = threading.Lock()
_token_counter = 0             # bumps on every acquire → opaque per-side tokens
# Per side: who (if anyone) holds it, the mode they acquired with, and their lease.
_sides = {
    s: {"present": False, "last_seen": 0.0, "token": None, "mode": "joint"}
    for s in SIDES
}


def _arm(side):
    return _robots.get(side)


def _redact_payload(value):
    """Return a JSON-safe, compact payload copy for the operator monitor."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "token":
                out[k] = "..."
            else:
                out[k] = _redact_payload(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact_payload(v) for v in value]
    if isinstance(value, float):
        return round(value, 3)
    return value


def _log_command(direction, side, command, payload=None, ok=None, error=None):
    """Append one command monitor entry and wake the operator SSE stream."""
    global _command_log_seq
    with _command_log_lock:
        _command_log_seq += 1
        _command_log.appendleft({
            "id": _command_log_seq,
            "ts": round(time.time(), 3),
            "time": time.strftime("%H:%M:%S"),
            "direction": direction,  # "incoming" | "robot"
            "side": side,
            "command": command,
            "payload": _redact_payload(payload or {}),
            "ok": ok,
            "error": error,
        })
    _live.bump()


def _command_log_snapshot():
    with _command_log_lock:
        return list(_command_log)


def _incoming_payload(data):
    payload = dict(data or {})
    payload["from"] = request.headers.get("X-HHH-Source") or request.remote_addr or ""
    return payload


def _log_incoming(command, data, ok=None, error=None):
    _log_command("incoming", _side_from(data), command, _incoming_payload(data), ok, error)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _clamp_joints(j1, j2, j3, j4):
    """Clamp a joint target to each joint's limit (mirror joint-angles-test)."""
    return (
        _clamp(j1, *JOINT_LIMITS["j1"]),
        _clamp(j2, *JOINT_LIMITS["j2"]),
        _clamp(j3, *JOINT_LIMITS["j3"]),
        _clamp(j4, *JOINT_LIMITS["j4"]),
    )


def _clamp_pose(x, y, z, r):
    """Clamp a target pose into the (approximate) reachable workspace: Z and R to
    their ranges, X/Y to the reachable annulus, then to the X/Y box. Mirrored
    EXACTLY from cartesian-xyz-test/prototype.py."""
    z = _clamp(z, *WORKSPACE["z"])
    r = _clamp(r, *WORKSPACE["r"])
    radius = math.hypot(x, y)
    if radius == 0.0:
        x, y = RADIUS_MIN, 0.0  # base axis is unreachable; nudge outward
    elif radius > RADIUS_MAX:
        s = RADIUS_MAX / radius
        x, y = x * s, y * s
    elif radius < RADIUS_MIN:
        s = RADIUS_MIN / radius
        x, y = x * s, y * s
    x = _clamp(x, *WORKSPACE["x"])
    y = _clamp(y, *WORKSPACE["y"])
    return x, y, z, r


def _apply_motion(robot, mode):
    """Push conservative velocity + acceleration caps to the follower for `mode`
    (accel = velocity-cap / ramp-time)."""
    secs = max(0.05, RAMP_SECS)
    if mode == "cartesian":
        robot.set_max_velocity_cartesian(MAX_LIN_VEL, MAX_ANG_VEL)
        robot.set_max_accel_cartesian(MAX_LIN_VEL / secs, MAX_ANG_VEL / secs)
    else:
        robot.set_max_velocity_joint(MAX_JOINT_VEL)
        robot.set_max_accel_joint(MAX_JOINT_VEL / secs)


def _ensure_follower(robot, mode):
    """Make sure the arm is running the follower for `mode` (switching followers if
    a different one is active). Keeps the connection + enabled state intact. No
    arbitration lock is held here — this does blocking arm I/O."""
    if robot is None or not robot.is_connected():
        return
    if not robot.get_state().get("enabled"):
        return
    if robot.control_mode() != mode:
        robot.start_servo(mode)   # start_servo stops any current follower first
        _apply_motion(robot, mode)


# ---- lease / arbitration helpers (call with _arb_lock held) ----------------
def _lease_secs_left_locked(side):
    if _sides[side]["token"] is None:
        return 0.0
    left = LEASE_SECS - (time.time() - _sides[side]["last_seen"])
    return max(0.0, left)


def _touch_locked(side):
    """Refresh a side's presence + lease (call with _arb_lock held)."""
    _sides[side]["present"] = True
    _sides[side]["last_seen"] = time.time()


# ---- programmatic API (for other machines via the hub) ---------------------
def arm_state(side):
    """That side's arm sub-object (same shape as state['arms'][side])."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}")
    return _arm_dict(side)


def side_holder(side):
    """The opaque token currently holding `side`, or None if free."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}")
    with _arb_lock:
        return _sides[side]["token"]


def full_state():
    """The relay's full state object (same shape as GET /api/state)."""
    return _state_dict()


# ---- watchdog --------------------------------------------------------------
def _watchdog_loop():
    """~5 Hz: for EACH side, if its holder's lease expired, smooth-stop THAT side's
    arm and free that side (mark not present). The other side is unaffected. Arm
    I/O happens outside the lock."""
    period = 1.0 / WATCHDOG_HZ
    while True:
        time.sleep(period)
        expired = []
        with _arb_lock:
            for s in SIDES:
                if _sides[s]["token"] is not None and _lease_secs_left_locked(s) <= 0.0:
                    expired.append(s)
                    _sides[s]["present"] = False
                    _sides[s]["token"] = None
        for s in expired:
            robot = _arm(s)
            if robot is not None and robot.is_connected():
                try:
                    robot.hold()      # smooth stop; keep servos enabled
                except Exception:     # pragma: no cover - defensive
                    pass
        if expired:
            _live.bump()


_watchdog_thread = threading.Thread(
    target=_watchdog_loop, name="relay-watchdog", daemon=True
)
_watchdog_thread.start()


# ---- response helpers ------------------------------------------------------
def _ok(**kw):
    return jsonify({"ok": True, **kw})


def _fail(error, **kw):
    return jsonify({"ok": False, "error": error, **kw})


def _pump_mode(do_bits):
    suck = bool(do_bits & (1 << (SUCK_DO_INDEX - 1)))
    blow = bool(do_bits & (1 << (BLOW_DO_INDEX - 1)))
    if suck and blow:
        return "conflict"
    if suck:
        return "suck"
    if blow:
        return "blow"
    return "off"


def _arm_dict(side):
    """The arm sub-object for one side (works with no robot connected)."""
    robot = _arm(side)
    raw = DobotMG400._blank_state() if robot is None else robot.get_state()
    return {
        "connected": raw["connected"],
        "enabled": raw["enabled"],
        "mode_name": raw["mode_name"],
        "joints": raw["joints"],
        "pose": raw["pose"],
        "servo_active": raw["servo_active"],
        "servo_error": raw["servo_error"],
        "pump_mode": _pump_mode(raw.get("digital_out", 0)),
        "control_mode": raw.get("control_mode"),
        "target": None if robot is None else robot.get_target(),
    }


def _state_dict():
    """The full relay state (GET /api/state and the SSE stream)."""
    arms = {s: _arm_dict(s) for s in SIDES}
    with _arb_lock:
        sides = {
            s: {
                "present": _sides[s]["present"],
                "lease_secs": round(_lease_secs_left_locked(s), 3),
            }
            for s in SIDES
        }
        state = {
            "arms": arms,
            "sides": sides,
            "command_log": _command_log_snapshot(),
        }
    return state


# ---- pages ----------------------------------------------------------------
@bp.route("/")
def index():
    return send_from_directory(HERE, "controller.html")


@bp.route("/api/config")
def config():
    return jsonify({
        "joint_limits": JOINT_LIMITS,
        "workspace": WORKSPACE,
        "radius_min": RADIUS_MIN,
        "radius_max": RADIUS_MAX,
        "default_ips": DEFAULT_IPS,
        "sides": list(SIDES),
        "modes": list(MODES),
        "lease_secs": LEASE_SECS,
    })


@bp.route("/api/state")
def state():
    return jsonify(_state_dict())


@bp.route("/api/events")
def events():
    """Push the relay state (both arms' feedback, sides, leases) ~5x/s while it
    changes; the leases count down so it changes every sample."""
    return _live.stream(_state_dict, interval=0.2)


# ---- side helpers ----------------------------------------------------------
def _side_from(data):
    side = (data or {}).get("side")
    if side not in SIDES:
        return None
    return side


# ---- operator endpoints (no token) ----------------------------------------
@bp.route("/api/connect", methods=["POST"])
def connect():
    """Connect THAT side's arm (replacing any existing connection for it)."""
    data = request.json or {}
    _log_incoming("connect", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("connect", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'")
    ip = data.get("ip") or DEFAULT_IPS[side]
    with _arm_locks[side]:
        if _robots[side] is not None:
            _robots[side].close()
            _robots[side] = None
        robot = DobotMG400(ip)
        try:
            robot.connect()
        except DobotError as e:
            _log_command("robot", side, "connect", {"ip": ip}, ok=False, error=str(e))
            return _fail(f"Could not connect to {ip}: {e}")
        _robots[side] = robot
    _log_command("robot", side, "connect", {"ip": ip}, ok=True)
    _live.bump()
    return _ok(side=side, ip=ip)


@bp.route("/api/disconnect", methods=["POST"])
def disconnect():
    """Disconnect that side's arm."""
    data = request.json or {}
    _log_incoming("disconnect", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("disconnect", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'")
    with _arm_locks[side]:
        if _robots[side] is not None:
            _robots[side].close()
            _robots[side] = None
            _log_command("robot", side, "close", {}, ok=True)
    _live.bump()
    return _ok(side=side)


@bp.route("/api/clear_error", methods=["POST"])
def clear_error():
    """Clear alarms/warnings on that side's arm without enabling or moving it."""
    data = request.json or {}
    _log_incoming("clear_error", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("clear_error", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'")
    robot = _arm(side)
    if robot is None or not robot.is_connected():
        _log_command("robot", side, "clear_error", {}, ok=False, error="Not connected")
        return _fail("Not connected")
    try:
        errid, resp = robot.clear_error()
    except DobotError as e:
        _log_command("robot", side, "clear_error", {}, ok=False, error=str(e))
        return _fail(str(e), errid=e.errid)
    ok = errid == 0
    _log_command("robot", side, "clear_error", {"errid": errid, "resp": resp}, ok=ok)
    _live.bump()
    return jsonify({"ok": ok, "errid": errid, "resp": resp, "side": side})


@bp.route("/api/enable", methods=["POST"])
def enable():
    """Enable that side's arm + start its follower in its current mode (default
    "joint"). Idempotent."""
    data = request.json or {}
    _log_incoming("enable", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("enable", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'")
    robot = _arm(side)
    if robot is None or not robot.is_connected():
        _log_command("robot", side, "enable", {}, ok=False, error="Not connected")
        return _fail("Not connected")
    with _arb_lock:
        mode = _sides[side]["mode"] if _sides[side]["token"] is not None else "joint"
    try:
        robot.clear_error()
        _log_command("robot", side, "clear_error", {}, ok=True)
    except DobotError:
        pass
    try:
        errid, resp = robot.enable()
    except DobotError as e:
        _log_command("robot", side, "enable", {}, ok=False, error=str(e))
        return _fail(str(e), errid=e.errid)
    if errid == 0:
        robot.start_servo(mode)
        _apply_motion(robot, mode)
        _log_command("robot", side, "enable + start_servo", {"mode": mode}, ok=True)
    else:
        _log_command("robot", side, "enable", {"errid": errid, "resp": resp}, ok=False)
    _live.bump()
    return jsonify({"ok": errid == 0, "errid": errid, "resp": resp, "side": side})


@bp.route("/api/kick", methods=["POST"])
def kick():
    """Force-release that side's controller (smooth-stop that side's arm + free its
    lease). The other side is unaffected."""
    data = request.json or {}
    _log_incoming("kick", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("kick", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'")
    with _arb_lock:
        _sides[side]["present"] = False
        _sides[side]["token"] = None
    robot = _arm(side)
    if robot is not None and robot.is_connected():
        try:
            robot.hold()
            _log_command("robot", side, "hold", {"reason": "kick"}, ok=True)
        except Exception:   # pragma: no cover - defensive
            _log_command("robot", side, "hold", {"reason": "kick"}, ok=False, error="hold failed")
    _live.bump()
    return _ok(side=side)


# ---- client / side endpoints ----------------------------------------------
def _check_token(data):
    """Validate (side, token) against that side's holder. Returns (side, error)
    where error is None on success. Refreshes the side's lease on success.
    Acquires/releases _arb_lock internally; does no arm I/O."""
    side = _side_from(data)
    if side is None:
        return None, "side must be 'purple' or 'green'"
    token = data.get("token")
    with _arb_lock:
        if _sides[side]["token"] is None or token != _sides[side]["token"]:
            return None, "stale token"
        _touch_locked(side)
    return side, None


@bp.route("/api/acquire", methods=["POST"])
def acquire():
    """Acquire THIS side's arm. Records the mode and mints a fresh token
    (invalidating any old one for that side). NEVER conflicts with the other side -
    purple and green can both hold concurrently (no 409)."""
    global _token_counter
    data = request.json or {}
    _log_incoming("acquire", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("acquire", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'"), 400
    mode = (data.get("mode") or "joint").lower()
    if mode not in MODES:
        _log_incoming("acquire", data, ok=False, error="mode must be 'joint' or 'cartesian'")
        return _fail("mode must be 'joint' or 'cartesian'"), 400
    with _arb_lock:
        _token_counter += 1
        token = f"{side}-{_token_counter}"
        _sides[side]["token"] = token
        _sides[side]["mode"] = mode
        _touch_locked(side)
    # If this side's arm is live + enabled, make sure the right follower runs
    # (outside the lock — blocking arm I/O).
    robot = _arm(side)
    if robot is not None and robot.is_connected():
        try:
            _ensure_follower(robot, mode)
            _log_command("robot", side, "ensure_follower", {"mode": mode}, ok=True)
        except Exception:   # pragma: no cover - defensive
            _log_command("robot", side, "ensure_follower", {"mode": mode}, ok=False, error="follower failed")
    _live.bump()
    return _ok(token=token, lease_secs=LEASE_SECS, side=side)


@bp.route("/api/release", methods=["POST"])
def release():
    """Release this side's arm. Requires a valid (side, token)."""
    data = request.json or {}
    _log_incoming("release", data)
    side = _side_from(data)
    if side is None:
        _log_incoming("release", data, ok=False, error="side must be 'purple' or 'green'")
        return _fail("side must be 'purple' or 'green'")
    token = data.get("token")
    with _arb_lock:
        if _sides[side]["token"] is None or token != _sides[side]["token"]:
            _log_incoming("release", data, ok=False, error="stale token")
            return _fail("stale token")
        _sides[side]["token"] = None
        _sides[side]["present"] = False
    robot = _arm(side)
    if robot is not None and robot.is_connected():
        try:
            robot.hold()
            _log_command("robot", side, "hold", {"reason": "release"}, ok=True)
        except Exception:   # pragma: no cover - defensive
            _log_command("robot", side, "hold", {"reason": "release"}, ok=False, error="hold failed")
    _live.bump()
    return _ok(side=side)


@bp.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    """Refresh this side's lease; returns the full state object. Stale token ->
    {ok:false, error:"stale token"}."""
    side, err = _check_token(request.json or {})
    if err:
        return _fail(err)
    return _ok(state=_state_dict())


@bp.route("/api/move", methods=["POST"])
def move():
    """Set this side's follower target after safety-clamping. Requires a valid
    (side, token), and that side's arm connected + enabled."""
    data = request.json or {}
    _log_incoming("move", data)
    side, err = _check_token(data)
    if err:
        _log_incoming("move", data, ok=False, error=err)
        return _fail(err)
    robot = _arm(side)
    if robot is None or not robot.is_connected():
        _log_command("robot", side, "move", {}, ok=False, error="Not connected")
        return _fail("Not connected")
    if not robot.get_state().get("enabled"):
        _log_command("robot", side, "move", {}, ok=False, error="Arm not enabled")
        return _fail("Arm not enabled")
    mode = (data.get("mode") or "joint").lower()
    if mode not in MODES:
        _log_command("robot", side, "move", {"mode": mode}, ok=False, error="bad mode")
        return _fail("mode must be 'joint' or 'cartesian'")
    # Make sure the right follower is running for this command.
    try:
        _ensure_follower(robot, mode)
    except DobotError as e:
        _log_command("robot", side, "ensure_follower", {"mode": mode}, ok=False, error=str(e))
        return _fail(str(e), errid=e.errid)

    if mode == "joint":
        j = data.get("joints")
        if not (isinstance(j, (list, tuple)) and len(j) >= 3):
            return _fail("Expected joints [j1, j2, j3, j4]")
        try:
            j1, j2, j3 = float(j[0]), float(j[1]), float(j[2])
            j4 = float(j[3]) if len(j) > 3 else robot.get_state()["joints"][3]
        except (ValueError, TypeError, IndexError):
            return _fail("joints must be numeric")
        j1, j2, j3, j4 = _clamp_joints(j1, j2, j3, j4)
        robot.set_target_joints(j1, j2, j3, j4)
        clamped = {"j1": round(j1, 2), "j2": round(j2, 2),
                   "j3": round(j3, 2), "j4": round(j4, 2)}
        _log_command("robot", side, "set_target_joints", clamped, ok=True)
    else:
        p = data.get("pose")
        if not (isinstance(p, (list, tuple)) and len(p) >= 3):
            return _fail("Expected pose [x, y, z, r]")
        try:
            x, y, z = float(p[0]), float(p[1]), float(p[2])
            r = float(p[3]) if len(p) > 3 else robot.get_state()["pose"][3]
        except (ValueError, TypeError, IndexError):
            return _fail("pose must be numeric")
        x, y, z, r = _clamp_pose(x, y, z, r)
        robot.set_target_pose(x, y, z, r)
        clamped = {"x": round(x, 2), "y": round(y, 2),
                   "z": round(z, 2), "r": round(r, 2)}
        _log_command("robot", side, "set_target_pose", clamped, ok=True)
    _live.bump()
    return _ok(clamped=clamped, side=side)


@bp.route("/api/pump", methods=["POST"])
def pump():
    """Set this side's air pump (suck|blow|off). Requires a valid (side, token)."""
    data = request.json or {}
    _log_incoming("pump", data)
    side, err = _check_token(data)
    if err:
        _log_incoming("pump", data, ok=False, error=err)
        return _fail(err)
    mode = (data.get("mode") or "off").lower()
    if mode not in ("suck", "blow", "off"):
        _log_command("robot", side, "pump", {"mode": mode}, ok=False, error="bad mode")
        return _fail("mode must be 'suck', 'blow' or 'off'")
    robot = _arm(side)
    if robot is None or not robot.is_connected():
        _log_command("robot", side, "pump", {"mode": mode}, ok=False, error="Not connected")
        return _fail("Not connected")
    try:
        errid, resp = robot.set_pump(mode, SUCK_DO_INDEX, BLOW_DO_INDEX)
    except DobotError as e:
        _log_command("robot", side, "set_pump", {"mode": mode}, ok=False, error=str(e))
        return _fail(str(e), errid=e.errid)
    _log_command("robot", side, "set_pump", {"mode": mode, "errid": errid, "resp": resp}, ok=(errid == 0))
    _live.bump()
    return jsonify({"ok": errid == 0, "errid": errid, "resp": resp, "side": side})


@bp.route("/api/hold", methods=["POST"])
def hold():
    """Smooth-stop this side's arm but keep its lease. Requires a valid (side,
    token)."""
    data = request.json or {}
    _log_incoming("hold", data)
    side, err = _check_token(data)
    if err:
        _log_incoming("hold", data, ok=False, error=err)
        return _fail(err)
    robot = _arm(side)
    if robot is not None and robot.is_connected():
        try:
            robot.hold()
            _log_command("robot", side, "hold", {}, ok=True)
        except Exception:   # pragma: no cover - defensive
            _log_command("robot", side, "hold", {}, ok=False, error="hold failed")
    _live.bump()
    return _ok(side=side)
