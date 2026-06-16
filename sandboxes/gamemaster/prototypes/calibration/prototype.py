"""
Camera <-> robot calibration — gamemaster session owner.

Phase 1 (capture only): the gamemaster picks a side (green / purple) to calibrate;
the OTHER side's controller is kicked from the relay. For the four playfield corner
markers (ArUco ids 33-36, the corners already defined in playfield-areas) the chosen
side's client captures, per corner:

  * the 2D camera pixel  — auto-detected from the webcam ArUco reader, or clicked
    manually on the image when a tag isn't found, and
  * the robot XYZ        — operator puts a tag on the tool, enables vacuum, unlocks
    the arm and positions it on the marker, then captures the live pose.

The result (4x {marker, cam:{x,y}, robot:{x,y,z}}) is stored server-side as
``calibration-<side>.json``. A later phase will turn it into a pixel->workspace
transform; this module only gathers and persists the correspondences.
"""

import csv
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request

from flask import Blueprint, Response, jsonify, request, send_from_directory

import live

HERE = os.path.dirname(os.path.abspath(__file__))

# The four playfield corner markers (DICT_4X4_50 ids), in corner order. These are
# the corner areas already configured in playfield-areas/areas.json.
CORNERS = (33, 34, 35, 36)
SIDES = ("green", "purple")

# The calibration playfield is just the four corner markers. Corner z is fixed,
# but x depends on whether the side being calibrated is the FLIPPED one: that bot
# reaches x in {-4, 9}; the non-flipped bot reaches {-9, 4} (z = ±2.5, y on the
# ground). When calibration starts we snapshot the live playfield, replace it with
# these, and restore the snapshot when done.
_CORNER_Z = {33: -2.5, 34: -2.5, 35: 2.5, 36: 2.5}
_FLIP_X = {33: -4.0, 36: -4.0, 34: 9.0, 35: 9.0}     # the flipped side
_NORMAL_X = {33: -9.0, 36: -9.0, 34: 4.0, 35: 4.0}   # the non-flipped side


def _cal_field(side):
    xs = _FLIP_X if side == _session["flipped_side"] else _NORMAL_X
    return [
        {"id": f"cal{m}", "name": f"Corner {i+1} ({m})", "marker": m,
         "x": xs[m], "y": 0.0, "z": _CORNER_Z[m], "size": 2.0,
         "color": "#4f9dff", "glow": 1.0, "links": [],
         "show_area": False, "show_aruco": True, "show_links": False}
        for i, m in enumerate(CORNERS)
    ]
_SNAP_PATH = os.path.join(HERE, "field-snapshot.json")
_field_lock = threading.Lock()
_field_active = False
_hub_ctx = None


def hub_init(ctx):
    """Keep the hub context for server-to-server calls (its base URL + service
    token let us drive the playfield-areas machine)."""
    global _hub_ctx
    _hub_ctx = ctx


def _pf(path, method="GET", body=None):
    """Call the gamemaster playfield-areas machine over HTTP with our service token."""
    base = getattr(_hub_ctx, "local_base", None)
    if not base:
        raise RuntimeError("no hub context (playfield unreachable)")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base}/s/gamemaster/p/playfield-areas{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    tok = getattr(_hub_ctx, "service_token", None)
    if tok:
        req.add_header("X-HHH-Auth", tok)
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read() or b"{}")


def _setup_field(side):
    """Snapshot the live playfield (once) and show the four corner markers for
    `side` (redraws with the side's positions if already active)."""
    global _field_active
    with _field_lock:
        if not _field_active:
            cur = _pf("/api/areas").get("areas", [])
            # Don't snapshot if the field is ALREADY our calibration markers (e.g.
            # the hub restarted mid-calibration) — that would lose the real original,
            # which is still in the snapshot file.
            is_cal = bool(cur) and all(str(a.get("id", "")).startswith("cal") for a in cur)
            if not is_cal:
                with open(_SNAP_PATH, "w", encoding="utf-8") as fh:
                    json.dump(cur, fh)
        _pf("/api/replace", "POST", {"areas": _cal_field(side)})
        _field_active = True


def _restore_field():
    """Put back whatever playfield was there before calibration."""
    global _field_active
    with _field_lock:
        try:
            with open(_SNAP_PATH, "r", encoding="utf-8") as fh:
                snap = json.load(fh)
        except (OSError, ValueError):
            snap = []
        _pf("/api/replace", "POST", {"areas": snap})
        _field_active = False

MANIFEST = {
    "name": "Calibration",
    "description": "Camera<->robot corner calibration: the gamemaster picks a side, "
                   "the other is kicked, and the four corner markers' camera pixels "
                   "+ robot XYZ are captured and saved.",
    "default_page": "",
    "pages": [
        {"path": "", "label": "Operator"},
        {"path": "client", "label": "Capture (client)"},
    ],
}
bp = Blueprint("calibration", __name__)

_lock = threading.Lock()
_live = live.LiveState()


def _blank_corner(marker):
    return {"marker": marker, "cam": None, "cam_src": None, "robot": None}


def _blank_corners():
    return {str(m): _blank_corner(m) for m in CORNERS}


_session = {
    "side": None,                 # "green" | "purple" being calibrated (None = idle)
    "corners": _blank_corners(),  # marker-id (str) -> corner record
    "flipped_side": "green",      # which side's capture VIEW is flipped 180° (one
                                  # side is always flipped; green by default)
    "updated_at": time.time(),
}


# ---- roles (mirrors pickup-game) -------------------------------------------
def _roles():
    return request.environ.get("hhh.roles") or set()


def _is_operator():
    return "gamemaster" in _roles()


def _player_side():
    roles = _roles()
    if "green" in roles:
        return "green"
    if "purple" in roles:
        return "purple"
    return ""


def _can_capture():
    """Operator may capture for any side; a player only when it IS the side the
    gamemaster has selected for calibration."""
    if _is_operator():
        return True
    side = _player_side()
    return bool(side) and side == _session["side"]


# ---- state -----------------------------------------------------------------
def _public_state_locked():
    out = dict(_session)
    out["corners"] = {k: dict(v) for k, v in _session["corners"].items()}
    out["markers"] = list(CORNERS)
    out["field_active"] = _field_active
    out["server_time"] = time.time()
    return out


def _public_state():
    with _lock:
        return _public_state_locked()


def _calib_path(side):
    return os.path.join(HERE, f"calibration-{side}.json")


def _csv_path(side):
    return os.path.join(HERE, f"calibration-{side}.csv")


CSV_HEADER = ["marker", "pixel_x", "pixel_y", "robot_x", "robot_y", "robot_z"]


def _csv_text(corners_list):
    """One row per corner: pixel (camera) x,y and robot x,y,z (blank where unset)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    for c in corners_list:
        cam = c.get("cam") or {}
        rob = c.get("robot") or {}
        w.writerow([c.get("marker"),
                    cam.get("x", ""), cam.get("y", ""),
                    rob.get("x", ""), rob.get("y", ""), rob.get("z", "")])
    return buf.getvalue()


# ---- pages -----------------------------------------------------------------
@bp.route("/")
def operator():
    resp = send_from_directory(HERE, "operator.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/client")
def client():
    resp = send_from_directory(HERE, "client.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/state")
def api_state():
    return jsonify(_public_state())


@bp.route("/api/events")
def api_events():
    return _live.stream(_public_state, interval=0.5)


# ---- operator: choose the side under calibration ---------------------------
@bp.route("/api/select", methods=["POST"])
def api_select():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    side = data.get("side")
    if side not in SIDES and side is not None:
        return jsonify({"ok": False, "error": "side must be 'green' or 'purple'"}), 400
    with _lock:
        # Re-selecting a side starts a fresh capture; load any saved file so the
        # operator can review/continue, otherwise blank corners.
        _session["side"] = side
        _session["corners"] = _blank_corners()
        if side:
            try:
                with open(_calib_path(side), "r", encoding="utf-8") as fh:
                    saved = json.load(fh)
                for c in saved.get("corners", []):
                    m = str(c.get("marker"))
                    if m in _session["corners"]:
                        _session["corners"][m].update({
                            "cam": c.get("cam"), "cam_src": c.get("cam_src"),
                            "robot": c.get("robot"),
                        })
            except (OSError, ValueError):
                pass
        _session["updated_at"] = time.time()

    # Starting a side shows the corner markers (snapshotting the field first);
    # stopping restores the original playfield. Best-effort — surface but don't fail.
    field_msg = None
    try:
        if side:
            _setup_field(side)          # snapshots once, then draws this side's markers
        elif _field_active:
            _restore_field()
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
        field_msg = f"playfield: {e}"
    out = _public_state()
    out["field_msg"] = field_msg
    _live.bump()
    return jsonify(out)


@bp.route("/api/field/setup", methods=["POST"])
def api_field_setup():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    side = _session["side"]
    if not side:
        return jsonify({"ok": False, "error": "select a side first"}), 409
    try:
        _setup_field(side)
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
        return jsonify({"ok": False, "error": f"playfield: {e}"}), 502
    _live.bump()
    return jsonify(_public_state())


@bp.route("/api/flip", methods=["POST"])
def api_flip():
    """Operator picks which side's capture VIEW is flipped 180°. One side is always
    flipped. Changing it also re-draws the active side's markers, since the corner
    x positions depend on which side is flipped."""
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    side = data.get("side")
    if side not in SIDES:
        return jsonify({"ok": False, "error": "side must be 'green' or 'purple'"}), 400
    with _lock:
        _session["flipped_side"] = side
        _session["updated_at"] = time.time()
        cur_side = _session["side"]
    field_msg = None
    if _field_active and cur_side:
        try:
            _setup_field(cur_side)   # corner x depends on the flipped side
        except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
            field_msg = f"playfield: {e}"
    _live.bump()
    out = _public_state()
    out["field_msg"] = field_msg
    return jsonify(out)


@bp.route("/api/field/restore", methods=["POST"])
def api_field_restore():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    try:
        _restore_field()
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
        return jsonify({"ok": False, "error": f"playfield: {e}"}), 502
    _live.bump()
    return jsonify(_public_state())


def _corner_or_400(data):
    try:
        marker = int(data.get("marker"))
    except (TypeError, ValueError):
        return None, (jsonify({"ok": False, "error": "marker required"}), 400)
    if marker not in CORNERS:
        return None, (jsonify({"ok": False, "error": f"marker must be one of {CORNERS}"}), 400)
    return marker, None


@bp.route("/api/cam", methods=["POST"])
def api_cam():
    if not _can_capture():
        return jsonify({"ok": False, "error": "not your side / no side selected"}), 403
    data = request.get_json(silent=True) or {}
    marker, err = _corner_or_400(data)
    if err:
        return err
    try:
        x, y = float(data["x"]), float(data["y"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "x, y required"}), 400
    src = "manual" if data.get("src") == "manual" else "aruco"
    with _lock:
        _session["corners"][str(marker)]["cam"] = {"x": round(x, 1), "y": round(y, 1)}
        _session["corners"][str(marker)]["cam_src"] = src
        _session["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/robot", methods=["POST"])
def api_robot():
    if not _can_capture():
        return jsonify({"ok": False, "error": "not your side / no side selected"}), 403
    data = request.get_json(silent=True) or {}
    marker, err = _corner_or_400(data)
    if err:
        return err
    try:
        x, y, z = float(data["x"]), float(data["y"]), float(data["z"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "x, y, z required"}), 400
    with _lock:
        _session["corners"][str(marker)]["robot"] = {
            "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
        }
        _session["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/clear", methods=["POST"])
def api_clear():
    if not _can_capture():
        return jsonify({"ok": False, "error": "not your side / no side selected"}), 403
    data = request.get_json(silent=True) or {}
    with _lock:
        marker = data.get("marker")
        if marker is None:
            _session["corners"] = _blank_corners()
        elif str(marker) in _session["corners"]:
            _session["corners"][str(marker)] = _blank_corner(int(marker))
        _session["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/save", methods=["POST"])
def api_save():
    if not _can_capture():
        return jsonify({"ok": False, "error": "not your side / no side selected"}), 403
    with _lock:
        side = _session["side"]
        if not side:
            return jsonify({"ok": False, "error": "no side selected"}), 409
        corners = [dict(_session["corners"][str(m)]) for m in CORNERS]
        payload = {
            "side": side,
            "markers": list(CORNERS),
            "corners": corners,
            "saved_at": time.time(),
        }
    try:
        with open(_calib_path(side), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        with open(_csv_path(side), "w", encoding="utf-8", newline="") as fh:
            fh.write(_csv_text(corners))
    except OSError as e:
        return jsonify({"ok": False, "error": f"could not write file: {e}"}), 500
    complete = all(c["cam"] and c["robot"] for c in corners)
    return jsonify({"ok": True, "side": side, "complete": complete,
                    "file": os.path.basename(_calib_path(side)),
                    "csv": os.path.basename(_csv_path(side))})


@bp.route("/api/download.csv")
def api_download_csv():
    """Download the current (or ?side=) calibration as CSV: pixel x,y + robot x,y,z."""
    side = request.args.get("side") or _session["side"]
    if not side:
        return Response("no side selected\n", status=400, mimetype="text/plain")
    with _lock:
        if side == _session["side"]:
            corners = [dict(_session["corners"][str(m)]) for m in CORNERS]
        else:
            saved = load_calibration(side)
            corners = saved.get("corners", []) if saved else []
    return Response(
        _csv_text(corners),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=calibration-{side}.csv"},
    )


# ---- programmatic accessor (for the future consuming phase) ----------------
def load_calibration(side):
    """Return the saved correspondences for a side, or None if not calibrated."""
    try:
        with open(_calib_path(side), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
