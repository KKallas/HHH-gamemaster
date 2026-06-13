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

import os
import threading
import time

from flask import Blueprint, jsonify, request, send_from_directory

import live

HERE = os.path.dirname(os.path.abspath(__file__))

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


def _public_state():
    with _state_lock:
        out = dict(_state)
        out["players"] = dict(_state.get("players") or {})
        out["ready"] = dict(_state.get("ready") or {})
    out["server_time"] = time.time()
    return out


def _patch_state(data):
    with _state_lock:
        for key in (
            "phase", "active_team", "tag_id", "active_radius_mm", "target_pose",
            "distance_mm", "pickup_state", "countdown_started_at", "game_started_at",
        ):
            if key in data:
                _state[key] = data[key]
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
    return send_from_directory(HERE, "game.html")


@bp.route("/api/state")
def api_state():
    return jsonify(_public_state())


@bp.route("/api/events")
def api_events():
    return _live.stream(_public_state, interval=0.2)


@bp.route("/api/player", methods=["POST"])
def api_player():
    data = request.get_json(silent=True) or {}
    if _is_operator():
        team = data.get("team") if data.get("team") in ("purple", "green") else _player_team()
    else:
        team = _player_team()
    if team not in ("purple", "green"):
        return jsonify({"ok": False, "error": "player team required"}), 403
    name = str(data.get("name") or "")[:32].strip()
    return jsonify(_patch_state({"players": {team: name}}))


@bp.route("/api/ready", methods=["POST"])
def api_ready():
    team = _player_team()
    if team not in ("purple", "green"):
        return jsonify({"ok": False, "error": "player team required"}), 403
    data = request.get_json(silent=True) or {}
    return jsonify(_patch_state({"ready": {team: bool(data.get("ready", True))}}))


@bp.route("/api/operator", methods=["POST"])
def api_operator():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    if data.get("phase") == "countdown" and not data.get("game_started_at"):
        now = time.time()
        data["countdown_started_at"] = now
        data["game_started_at"] = now + 5
    return jsonify(_patch_state(data))
