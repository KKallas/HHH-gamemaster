# Dobot MG400 Relay (two arms)

A game-master **relay** machine for the Manual Override hub. It owns **two** MG400
connections — one per side, **purple** and **green** — and routes each side's
commands to *its own* arm, applying a safety filter, then exposes an HTTP + SSE
API that remote client controllers talk to. Mounted at `/p/dobot-mg400-relay`.

## Hardware setup (USB Ethernet dongles) — do this first

Both MG400s keep Dobot's **factory IP `192.168.1.6`** (we deliberately don't
change it), so they can NOT hang off one network — the relay tells them apart by
which **physical port** the traffic leaves through. To (re)build the setup:

1. **One USB Ethernet dongle per robot**, plugged into the gamemaster Mac.
   Cable each dongle **directly** to its own robot (no switch/router in between):
   - **purple** robot ↔ dongle #1
   - **green** robot ↔ dongle #2
2. **Configure each dongle manually** (System Settings → Network → the dongle →
   Details → TCP/IP → Configure IPv4: *Manually*). These numbers are FIXED — the
   same everywhere in this project:
   - dongle #1 (purple): IP **192.168.1.50**, subnet mask `255.255.255.0`,
     router (default gateway) and DNS/nameserver left **empty**
   - dongle #2 (green): IP **192.168.1.51**, subnet mask `255.255.255.0`,
     router (default gateway) and DNS/nameserver left **empty**
That's it — you do NOT need to know the interface names (`en10`, `en11`, …;
they vary by Mac and USB port). At connect time the relay finds whichever
interface owns `.50` / `.51` and pins that side's sockets to it. If a side
fails with "no local interface has IP 192.168.1.5x", that dongle isn't plugged
in or isn't configured — check with `ifconfig | grep 192.168.1.5`.

Swapped sides (purple GUI moves the green arm)? The cables are crossed — swap
the two robot cables (or the dongles' `.50`/`.51` assignment).

The two sides are **independent** and drive **concurrently**: purple's controller
drives the purple arm while green's controller drives the green arm. There is no
blocking across sides.

Per side the relay still arbitrates: a side must *acquire its arm* and gets an
opaque token + a lease. This stops two tabs of the **same** side from fighting,
but it **never** conflicts across sides (no 409). A per-side watchdog smooth-stops
a side's arm if its holder stops heartbeating. Every command for a side passes the
same safety clamps as the joint / cartesian test machines.

The operator GUI and every endpoint work with **no robot connected** — an arm just
reports `connected:false` and that side's `move`/`pump` fail cleanly.

## Driver

`relay_arm.py` is the unified MG400 driver merging the joint (ServoJ) and
cartesian (ServoP) drivers into one class that owns a single connection and runs
EITHER follower. The relay instantiates it **once per side**. `start_servo(...)`
picks the follower; switching modes stops the old follower and starts the other
while keeping the connection + enabled state intact. `control_mode()` reports
which is running.

**Both arms share ONE robot IP** (Dobot's factory `192.168.1.6`) and are told
apart by **which local network interface** the connection leaves through: every
socket is pinned to its side's interface with the macOS `IP_BOUND_IF` option
(and bound to that interface's local IP) *before* connecting — the same trick as
the `dualdobottest` proof of concept. Without the pin the OS would route both
sides' traffic to one interface and only one arm would ever answer (binding the
source IP alone does not help; routing is destination-based). The interface
**name** is auto-detected at connect time as whichever interface owns the side's
fixed dongle IP, so config and GUI only deal in `.50`/`.51`.

## Contract (what clients depend on)

Sides: `purple`, `green`. Modes: `joint`, `cartesian`. `LEASE_SECS = 2.0`.
Shared robot IP: `192.168.1.6` (both arms). Per-side default links (the fixed
dongle IP each side's sockets are pinned to; interface name auto-detected):
`{"purple": {"local_ip": "192.168.1.50"}, "green": {"local_ip": "192.168.1.51"}}`.

### State

`GET /api/state` (also SSE `GET /api/events`, sampled ~5x/s):

```jsonc
{
  "arms": {
    "purple": {"connected": bool, "enabled": bool, "mode_name": str,
               "joints": [j1,j2,j3,j4], "pose": [x,y,z,r],
               "servo_active": bool, "servo_error": str|null,
               "pump_mode": "off|suck|blow|conflict",
               "control_mode": "joint|cartesian|null",
               "target": [..]|null},
    "green":  { ...same shape... }
  },
  "sides": {
    "purple": {"present": bool, "lease_secs": float},
    "green":  { ...same... }
  }
}
```

`pump_mode` is derived from each arm's digital-out bits: suck = index 2, blow =
index 1; both set = `conflict`. `control_mode` is that arm's running follower.

### Operator endpoints (no token)

| Method | Path | Body | Effect |
|---|---|---|---|
| POST | `/api/connect` | `{side, local_ip?, ip?, iface?}` | Connect THAT side's arm via its pinned dongle, replacing any existing connection for it. Omitted fields fall back to that side's default dongle IP / the shared robot IP; `iface` overrides the auto-detection. |
| POST | `/api/disconnect` | `{side}` | Disconnect that side's arm. |
| POST | `/api/enable` | `{side}` | Enable that side's arm + start its follower in its current mode (else `joint`). Idempotent. Clears the arm's error first. (Also callable by clients.) |
| POST | `/api/kick` | `{side}` | Force-release that side's controller; smooth-stop that side's arm. |

### Client / side endpoints (operate on the side's OWN arm)

| Method | Path | Body | Effect |
|---|---|---|---|
| POST | `/api/acquire` | `{side, mode}` | Acquire THIS side's arm; mint a token. NEVER 409 across sides — both sides can hold concurrently. |
| POST | `/api/release` | `{side, token}` | Release this side's arm. |
| POST | `/api/heartbeat` | `{side, token}` | Refresh this side's lease; returns the full state. Stale token → `{ok:false, error:"stale token"}`. |
| POST | `/api/move` | `{side, token, mode, joints?\|pose?}` | Safety-clamp then set that side's follower target. |
| POST | `/api/pump` | `{side, token, mode}` | Set that side's pump `suck\|blow\|off`. |
| POST | `/api/hold` | `{side, token}` | Smooth-stop that side's arm, keep its lease. |

Player relay clients may also call `/api/connect` for their side if the operator
has not connected that arm yet. This lets a player sandbox bring up its own arm
through the relay without first opening the operator page. Requests whose
authenticated roles are only team roles (see the hub's `shared_api` door) are
rejected with 403 unless `side` is their own team.

Tokens are opaque strings (`f"{side}-{counter}"`). A new `acquire` for a side
invalidates that side's old token; any token mismatch on
`release`/`heartbeat`/`move`/`pump`/`hold` fails with `"stale token"`.

### Programmatic API (for other machines via the hub)

- `arm_state(side)` → that side's arm sub-object (same shape as `state["arms"][side]`).
- `side_holder(side)` → the opaque token currently holding `side`, or `None`.
- `full_state()` → the full relay state (same shape as `GET /api/state`).

## Safety notes

- **Per-side ownership.** Each side has its own lease + token; two tabs of the
  same side can't fight (a fresh `acquire` invalidates the old token). The two
  sides never block each other.
- **Per-side watchdog (~5 Hz).** If a side's holder lease expires (no contact
  within `LEASE_SECS`), THAT side's arm is smooth-stopped (`hold()`) and the side
  is freed. The other side is unaffected.
- **No software E-STOP.** Stopping is mechanical — use each robot's hardware
  E-stop button. The relay has no global software stop/latch to get stuck in.
- **Safety clamps** (per arm) mirror the test machines exactly:
  - joint: each angle clamped to `JOINT_LIMITS`
    (J1 ±160, J2 −25…85, J3 −25…105, J4 ±160 deg);
  - cartesian: Z clamped to −150…230 mm, R to ±160°, and X/Y to the reachable
    annulus (radius 150…440 mm) then the ±450 mm box.
- Keep each hardware E-stop within reach and start with a low speed. Put each
  robot in API mode first — see `../../docs/operations/dobot-api-mode.md`.
