"""
Pick & Place v2 — game-master referee + scoring.

The PLAYER click-to-place controller lives in the green/purple sandboxes; this
gamemaster page is the referee: a live camera, each side's arm status (read from
the dobot-mg400-relay), per-side kick / reset / speed controls — AND the v2 game
layer (same high-score system as the v1 pickup-game):

  - Each player enters a name (prompted on every page load) and enables their arm.
  - The round timer starts for BOTH teams the moment BOTH have enabled their arms
    — before that the players cannot move.
  - The gamemaster closes each team's timer with "Mark <team> finished"; every
    finished run is appended to ``pickplace-v2-log.csv`` and ranked on the board.

Players report their name + arm-enabled state here; only the gamemaster marks a
run finished.
"""

import csv
import datetime as _dt
import io
import os
import threading
import time

from flask import Blueprint, Response, jsonify, request, send_from_directory

import live

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "pickplace-v2-log.csv")
LOG_FIELDS = [
    "logged_at", "player", "team", "elapsed_seconds",
    "started_at", "completed_at",
]
TEAMS = ("green", "purple")

MANIFEST = {
    "name": "Pick & Place v2",
    "description": "Game-master referee: live camera + both teams' arm status with "
                   "per-side kick / reset / speed, plus the v2 game timer + high "
                   "scores. Players use the controller in their own sandbox.",
    "default_page": "",
    "pages": [{"path": "", "label": "Referee"}],
}
bp = Blueprint("pick_place_v2", __name__)

_state_lock = threading.Lock()
_live = live.LiveState()


def _team_state():
    return {
        "player": "",
        "phase": "idle",            # idle | ready | running | done
        "enabled": False,           # has this team enabled its arm?
        "started_at": None,         # epoch seconds (shared start across teams)
        "completed_at": None,
        "elapsed_seconds": None,
    }


_state = {
    "teams": {t: _team_state() for t in TEAMS},
    "best_seconds": None,
    "best_player": "",
    "best_team": "",
    "updated_at": time.time(),
}


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


def _requested_team(data):
    """The team the caller is allowed to act on: operator may name any team,
    a player only their own."""
    requested = data.get("team")
    if requested in TEAMS and (_is_operator() or requested in _roles()):
        return requested
    return _player_side()


def _read_log_rows():
    if not os.path.exists(LOG_PATH):
        return []
    rows = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    row["elapsed_seconds"] = float(row.get("elapsed_seconds"))
                except (TypeError, ValueError):
                    continue
                rows.append(row)
    except OSError:
        return []
    return rows


def _seed_best_from_log():
    best = None
    best_player = ""
    best_team = ""
    for row in _read_log_rows():
        secs = row.get("elapsed_seconds")
        if best is None or secs < best:
            best = secs
            best_player = row.get("player") or ""
            best_team = row.get("team") or ""
    _state["best_seconds"] = best
    _state["best_player"] = best_player
    _state["best_team"] = best_team


def _maybe_start_locked():
    """If BOTH teams are registered (ready) and have enabled their arms, start the
    round for both at the same instant. Call with _state_lock held."""
    teams = _state["teams"]
    if all(teams[t]["phase"] == "ready" and teams[t]["enabled"] for t in TEAMS):
        now = time.time()
        for t in TEAMS:
            teams[t].update({
                "phase": "running", "started_at": now,
                "completed_at": None, "elapsed_seconds": None,
            })
        _state["updated_at"] = now
        return True
    return False


def _public_state_locked():
    out = dict(_state)
    out["teams"] = {t: dict(_state["teams"][t]) for t in TEAMS}
    out["server_time"] = time.time()
    return out


def _public_state():
    with _state_lock:
        return _public_state_locked()


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "index.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/state")
def api_state():
    return jsonify(_public_state())


@bp.route("/api/events")
def api_events():
    return _live.stream(_public_state, interval=0.2)


@bp.route("/api/player", methods=["POST"])
def api_player():
    """Register (or re-register) a player name for a team. Resets that team to
    'ready' with a fresh, un-enabled run — fired on every page load, so a refresh
    prompts for the next user."""
    data = request.get_json(silent=True) or {}
    team = _requested_team(data)
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "player team required"}), 403
    name = str(data.get("name") or "").strip()[:32]
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    with _state_lock:
        _state["teams"][team] = _team_state()
        _state["teams"][team]["player"] = name
        _state["teams"][team]["phase"] = "ready"
        _state["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/enabled", methods=["POST"])
def api_enabled():
    """A player reports whether their arm is currently enabled. When both teams
    are ready + enabled the round timer starts for both at once."""
    data = request.get_json(silent=True) or {}
    team = _requested_team(data)
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "player team required"}), 403
    on = bool(data.get("enabled"))
    with _state_lock:
        ts = _state["teams"][team]
        # Only meaningful while waiting in the lobby; once running/done it's frozen.
        if ts["phase"] in ("idle", "ready"):
            ts["enabled"] = on
            _state["updated_at"] = time.time()
            _maybe_start_locked()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/finish", methods=["POST"])
def api_finish():
    """Gamemaster closes a team's timer; logs the run + updates the best time."""
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    team = data.get("team")
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "team required"}), 400
    with _state_lock:
        ts = _state["teams"][team]
        if ts["phase"] != "running" or not ts["started_at"]:
            return jsonify({"ok": False, "error": "no run in progress"}), 409
        now = time.time()
        elapsed = round(now - float(ts["started_at"]), 2)
        player = ts["player"]
        entry = {
            "logged_at": _dt.datetime.now(_dt.UTC).isoformat(),
            "player": player,
            "team": team,
            "elapsed_seconds": elapsed,
            "started_at": _dt.datetime.fromtimestamp(ts["started_at"], _dt.UTC).isoformat(),
            "completed_at": _dt.datetime.fromtimestamp(now, _dt.UTC).isoformat(),
        }
        need_header = not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0
        with open(LOG_PATH, "a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
            if need_header:
                writer.writeheader()
            writer.writerow(entry)
        if _state["best_seconds"] is None or elapsed < _state["best_seconds"]:
            _state["best_seconds"] = elapsed
            _state["best_player"] = player
            _state["best_team"] = team
        ts.update({
            "phase": "done", "completed_at": now, "elapsed_seconds": elapsed,
        })
        _state["updated_at"] = now
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


def _remove_log_row(team, started_at_iso):
    """Remove the most recent logged row matching team + started_at (used to undo
    a finish). Returns True if a row was removed."""
    if not os.path.exists(LOG_PATH):
        return False
    try:
        with open(LOG_PATH, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return False
    drop_idx = None
    for i in range(len(rows) - 1, -1, -1):
        if rows[i].get("team") == team and rows[i].get("started_at") == started_at_iso:
            drop_idx = i
            break
    if drop_idx is None:
        return False
    rows.pop(drop_idx)
    with open(LOG_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return True


@bp.route("/api/cancel", methods=["POST"])
def api_cancel():
    """Undo a finish: revert a done run back to running, drop its logged row, and
    keep the original started_at so the counter continues as if never stopped."""
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    team = data.get("team")
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "team required"}), 400
    with _state_lock:
        ts = _state["teams"][team]
        if ts["phase"] != "done" or not ts["started_at"]:
            return jsonify({"ok": False, "error": "no finished run to cancel"}), 409
        started_iso = _dt.datetime.fromtimestamp(ts["started_at"], _dt.UTC).isoformat()
        _remove_log_row(team, started_iso)
        ts.update({
            "phase": "running", "completed_at": None, "elapsed_seconds": None,
        })
        _seed_best_from_log()
        _state["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/reset", methods=["POST"])
def api_reset():
    """Reset a team (or both, operator) back to the lobby — clears name, enabled
    flag and timer so the next players can register."""
    data = request.get_json(silent=True) or {}
    requested = data.get("team")
    with _state_lock:
        if requested in TEAMS and (_is_operator() or requested in _roles()):
            targets = [requested]
        elif _is_operator() and not requested:
            targets = list(TEAMS)            # operator: reset both
        else:
            side = _player_side()            # player: own team only
            targets = [side] if side in TEAMS else []
        if not targets:
            return jsonify({"ok": False, "error": "team required"}), 403
        for team in targets:
            _state["teams"][team] = _team_state()
        _state["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/results")
def api_results():
    rows = _read_log_rows()
    rows.reverse()
    with _state_lock:
        best = {
            "seconds": _state["best_seconds"],
            "player": _state["best_player"],
            "team": _state["best_team"],
        }
    return jsonify({"results": rows[:50], "best": best, "count": len(rows)})


@bp.route("/api/log.csv")
def api_log_csv():
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as fh:
            body = fh.read()
    else:
        buf = io.StringIO()
        csv.DictWriter(buf, fieldnames=LOG_FIELDS).writeheader()
        body = buf.getvalue()
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=pickplace-v2-log.csv"},
    )


_seed_best_from_log()
