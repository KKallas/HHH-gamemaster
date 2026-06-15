"""
Tag-game prototype — the gamemaster referee/operator controller for the
camera-confirmed tag game.

This machine owns the GAME, not the playfield: the zones it plays on belong to
the playfield-areas prototype, and the live camera/robot state comes from the
webcam and dobot-mg400-relay prototypes. It serves two pages and has no API or
state of its own — all game flow runs in the browser against those prototypes:

  * game.html       — the embedded 90 second game screen over the webcam feed
                      with the gamemaster desk for team/player/tag setup,
                      robot calibration, round control, scoring, and high
                      scores.
  * controller.html — a setup helper page: reset the playfield to the shared
                      pickup/deposit zones and jump back to the game screen.

This module is loaded by hub.py and registered under /p/tag-game.
"""

import datetime as _dt
import json
import os
import threading
import time

from flask import Blueprint, jsonify, request, send_from_directory

import live

HERE = os.path.dirname(os.path.abspath(__file__))
HIGH_SCORE_LOG = os.path.join(HERE, "high-score-log.jsonl")

# Every prototype exposes these two names for the hub:
MANIFEST = {
    "name": "Tag Game",
    "description": "Gamemaster referee/operator controls for the camera-confirmed "
                   "tag game: configure, calibrate, start, monitor, and score "
                   "purple and green team rounds.",
    "default_page": "game",   # what the hub embeds in its tab
    "pages": [
        {"path": "game", "label": "Game screen"},
        {"path": "controller", "label": "Setup zones"},
    ],
}
bp = Blueprint("tag_game", __name__)

_state_lock = threading.Lock()
_live = live.LiveState()
_state = {
    "phase": "setup",
    "active_team": "purple",
    "players": {"purple": "", "green": ""},
    "ready": {"purple": False, "green": False},
    "tag_id": 42,
    "active_radius_mm": 30,
    "target_pose": None,
    "distance_mm": None,
    "pickup_state": "Waiting",
    "player_webcam_rotate180": False,
    "player_webcam_rotate180_by_team": {"purple": False, "green": False},
    "round_result": None,
    "countdown_started_at": None,
    "game_started_at": None,
    "updated_at": time.time(),
}


def _roles():
    return request.environ.get("hhh.roles") or set()


def _is_operator():
    return "gamemaster" in _roles()


def _player_team():
    roles = _roles()
    if "green" in roles:
        return "green"
    if "purple" in roles:
        return "purple"
    return None


def _requested_team(data):
    requested = data.get("team")
    roles = _roles()
    if requested in ("purple", "green") and (_is_operator() or requested in roles):
        return requested
    return _player_team()


def _public_state():
    with _state_lock:
        out = dict(_state)
        out["players"] = dict(_state.get("players") or {})
        out["ready"] = dict(_state.get("ready") or {})
        if out.get("phase") == "setup":
            out["countdown_started_at"] = None
            out["game_started_at"] = None
    out["server_time"] = time.time()
    return out


def _public_state_locked():
    out = dict(_state)
    out["players"] = dict(_state.get("players") or {})
    out["ready"] = dict(_state.get("ready") or {})
    if out.get("phase") == "setup":
        out["countdown_started_at"] = None
        out["game_started_at"] = None
    out["server_time"] = time.time()
    return out


def _patch_state(data):
    with _state_lock:
        requested_phase = data.get("phase")
        current_phase = _state.get("phase")
        explicit_reset = (
            requested_phase == "setup"
            and data.get("countdown_started_at", "__missing__") is None
            and data.get("game_started_at", "__missing__") is None
            and isinstance(data.get("ready"), dict)
        )
        if current_phase in ("countdown", "running") and requested_phase == "setup" and not explicit_reset:
            return _public_state_locked()
        for key in (
            "phase", "active_team", "tag_id", "active_radius_mm",
            "distance_mm", "pickup_state", "player_webcam_rotate180",
            "player_webcam_rotate180_by_team", "countdown_started_at", "game_started_at",
        ):
            if key in data:
                _state[key] = data[key]
        if "round_result" in data:
            result = data.get("round_result")
            _state["round_result"] = result if isinstance(result, dict) else None
        if isinstance(data.get("target_pose"), dict):
            _state["target_pose"] = data["target_pose"]
        if _state.get("phase") == "setup":
            _state["countdown_started_at"] = None
            _state["game_started_at"] = None
        players = data.get("players")
        if isinstance(players, dict):
            current = dict(_state.get("players") or {})
            for team in ("purple", "green"):
                if team in players:
                    current[team] = str(players.get(team) or "")[:32]
            _state["players"] = current
        ready = data.get("ready")
        if isinstance(ready, dict):
            current = dict(_state.get("ready") or {})
            for team in ("purple", "green"):
                if team in ready:
                    current[team] = bool(ready.get(team))
            _state["ready"] = current
        _state["updated_at"] = time.time()
    _live.bump()
    return _public_state()


@bp.route("/controller")
def controller():
    return send_from_directory(HERE, "controller.html")


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
    if team not in ("purple", "green"):
        return jsonify({"ok": False, "error": "player team required"}), 403
    name = str(data.get("name") or "")[:32].strip()
    return jsonify(_patch_state({"players": {team: name}}))


@bp.route("/api/ready", methods=["POST"])
def api_ready():
    data = request.get_json(silent=True) or {}
    team = _requested_team(data)
    if team not in ("purple", "green"):
        return jsonify({"ok": False, "error": "player team required"}), 403
    return jsonify(_patch_state({"ready": {team: bool(data.get("ready", True))}}))


@bp.route("/api/operator", methods=["POST"])
def api_operator():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    if data.get("phase") == "countdown":
        target_pose = data.get("target_pose")
        if not isinstance(target_pose, dict):
            with _state_lock:
                target_pose = _state.get("target_pose")
        if not isinstance(target_pose, dict):
            return jsonify({"ok": False, "error": "target calibration required"}), 400
    if data.get("phase") == "countdown" and not data.get("game_started_at"):
        now = time.time()
        data["countdown_started_at"] = now
        data["game_started_at"] = now + 5
    return jsonify(_patch_state(data))


@bp.route("/api/high-score-log", methods=["POST"])
def api_high_score_log():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    entry = {
        "logged_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "team": str(data.get("team") or "")[:16],
        "player": str(data.get("player") or "")[:32],
        "state": str(data.get("state") or "")[:16],
        "elapsed_seconds": data.get("elapsed_seconds"),
        "player_best_win_seconds": data.get("player_best_win_seconds"),
        "overall_best_win_seconds": data.get("overall_best_win_seconds"),
        "overall_best_player": str(data.get("overall_best_player") or "")[:32],
        "overall_best_team": str(data.get("overall_best_team") or "")[:16],
        "wins": data.get("wins"),
    }
    with _state_lock:
        with open(HIGH_SCORE_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return jsonify({"ok": True, "path": os.path.basename(HIGH_SCORE_LOG)})
