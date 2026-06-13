"""
Two-player Tag Game prototype.

This is a separate gamemaster tab from the regular Tag Game. It keeps the same
player-facing API shape where possible, while adding per-team configuration,
calibration, telemetry, and shared start/end timing for purple and green.
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
TEAMS = ("purple", "green")

MANIFEST = {
    "name": "2P Tag Game",
    "description": "Two-player tag game: configure, calibrate, start, monitor, "
                   "and score purple and green teams in one shared round.",
    "default_page": "game",
    "pages": [
        {"path": "game", "label": "Game screen"},
        {"path": "controller", "label": "Setup zones"},
    ],
}
bp = Blueprint("two_player_tag_game", __name__)


def _team_state(tag_id):
    return {
        "tag_id": tag_id,
        "active_radius_mm": 30,
        "target_pose": None,
        "distance_mm": None,
        "pickup_state": "Waiting",
    }


_state_lock = threading.Lock()
_live = live.LiveState()
_state = {
    "mode": "two_player",
    "phase": "setup",
    "active_team": "both",
    "active_teams": list(TEAMS),
    "players": {"purple": "", "green": ""},
    "ready": {"purple": False, "green": False},
    "teams": {"purple": _team_state(42), "green": _team_state(43)},
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
    if requested in TEAMS and (_is_operator() or requested in roles):
        return requested
    return _player_team()


def _public_state_locked():
    out = dict(_state)
    out["players"] = dict(_state.get("players") or {})
    out["ready"] = dict(_state.get("ready") or {})
    out["active_teams"] = list(TEAMS)
    out["teams"] = {
        team: dict((_state.get("teams") or {}).get(team) or _team_state(42 + i))
        for i, team in enumerate(TEAMS)
    }
    if out.get("phase") == "setup":
        out["countdown_started_at"] = None
        out["game_started_at"] = None
    # Compatibility values are purple-biased for older callers; copied 2P
    # player screens read their own team from out["teams"].
    purple = out["teams"]["purple"]
    out["tag_id"] = purple.get("tag_id")
    out["active_radius_mm"] = purple.get("active_radius_mm")
    out["target_pose"] = purple.get("target_pose")
    out["distance_mm"] = purple.get("distance_mm")
    out["pickup_state"] = purple.get("pickup_state")
    out["server_time"] = time.time()
    return out


def _public_state():
    with _state_lock:
        return _public_state_locked()


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

        for key in ("phase", "countdown_started_at", "game_started_at"):
            if key in data:
                _state[key] = data[key]
        _state["mode"] = "two_player"
        _state["active_team"] = "both"
        _state["active_teams"] = list(TEAMS)

        if "round_result" in data:
            result = data.get("round_result")
            _state["round_result"] = result if isinstance(result, dict) else None
        if _state.get("phase") == "setup":
            _state["countdown_started_at"] = None
            _state["game_started_at"] = None

        players = data.get("players")
        if isinstance(players, dict):
            current = dict(_state.get("players") or {})
            for team in TEAMS:
                if team in players:
                    current[team] = str(players.get(team) or "")[:32]
            _state["players"] = current

        ready = data.get("ready")
        if isinstance(ready, dict):
            current = dict(_state.get("ready") or {})
            for team in TEAMS:
                if team in ready:
                    current[team] = bool(ready.get(team))
            _state["ready"] = current

        incoming_teams = data.get("teams")
        if isinstance(incoming_teams, dict):
            current_teams = {
                team: dict((_state.get("teams") or {}).get(team) or _team_state(42 + i))
                for i, team in enumerate(TEAMS)
            }
            for team in TEAMS:
                patch = incoming_teams.get(team)
                if not isinstance(patch, dict):
                    continue
                for key in ("tag_id", "active_radius_mm", "target_pose", "distance_mm", "pickup_state"):
                    if key in patch:
                        current_teams[team][key] = patch[key]
            _state["teams"] = current_teams

        _state["updated_at"] = time.time()
        out = _public_state_locked()
    _live.bump()
    return out


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
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "player team required"}), 403
    name = str(data.get("name") or "")[:32].strip()
    return jsonify(_patch_state({"players": {team: name}, "ready": {team: False}}))


@bp.route("/api/ready", methods=["POST"])
def api_ready():
    data = request.get_json(silent=True) or {}
    team = _requested_team(data)
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "player team required"}), 403
    return jsonify(_patch_state({"ready": {team: bool(data.get("ready", True))}}))


@bp.route("/api/operator", methods=["POST"])
def api_operator():
    if not _is_operator():
        return jsonify({"ok": False, "error": "gamemaster required"}), 403
    data = request.get_json(silent=True) or {}
    if data.get("phase") == "countdown":
        teams = data.get("teams") if isinstance(data.get("teams"), dict) else {}
        with _state_lock:
            stored_teams = _state.get("teams") or {}
        for team in TEAMS:
            target_pose = (teams.get(team) or {}).get("target_pose")
            if not isinstance(target_pose, dict):
                target_pose = (stored_teams.get(team) or {}).get("target_pose")
            if not isinstance(target_pose, dict):
                return jsonify({"ok": False, "error": f"{team} target calibration required"}), 400
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
        "mode": "two_player",
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
