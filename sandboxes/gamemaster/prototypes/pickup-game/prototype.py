"""
Pick-and-Place game — gamemaster master controller.

Two players (green + purple), each independent. A player enters their name and
presses Start whenever they like; their clock runs until the GAMEMASTER marks
that team finished (the block has reached its square). No ArUco / vision — the
gamemaster judges the field by eye. Every finished run is appended to
``pickup-log.csv``.

Player controllers (green/purple sandboxes) drive their own arm via
joint-angles-test and forward name/start here; only the gamemaster can mark a
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
LOG_PATH = os.path.join(HERE, "pickup-log.csv")
LOG_FIELDS = [
    "logged_at", "player", "team", "elapsed_seconds",
    "started_at", "completed_at",
]
TEAMS = ("green", "purple")

MANIFEST = {
    "name": "Pick & Place",
    "description": "Two-player pick-and-place game: each player times their own "
                   "run, the gamemaster marks finishes, all logged to CSV.",
    "default_page": "game",
    "pages": [{"path": "game", "label": "Game screen"}],
}
bp = Blueprint("pickup_game", __name__)

_state_lock = threading.Lock()
_live = live.LiveState()


def _team_state():
    return {
        "player": "",
        "phase": "idle",            # idle | ready | running | done
        "started_at": None,         # epoch seconds
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


def _public_state_locked():
    out = dict(_state)
    out["teams"] = {t: dict(_state["teams"][t]) for t in TEAMS}
    out["server_time"] = time.time()
    return out


def _public_state():
    with _state_lock:
        return _public_state_locked()


@bp.route("/")
@bp.route("/game")
def game():
    resp = send_from_directory(HERE, "game.html")
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


@bp.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    team = _requested_team(data)
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "player team required"}), 403
    with _state_lock:
        ts = _state["teams"][team]
        if not ts["player"]:
            return jsonify({"ok": False, "error": "enter a name first"}), 409
        now = time.time()
        ts.update({
            "phase": "running", "started_at": now,
            "completed_at": None, "elapsed_seconds": None,
        })
        _state["updated_at"] = now
        out = _public_state_locked()
    _live.bump()
    return jsonify(out)


@bp.route("/api/finish", methods=["POST"])
def api_finish():
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


@bp.route("/api/reset", methods=["POST"])
def api_reset():
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
        headers={"Content-Disposition": "attachment; filename=pickup-log.csv"},
    )


_seed_best_from_log()
