"""
Player 2P Tag Game controls.

This page is mounted in a team sandbox and reads the gamemaster 2P Tag Game state.
The gamemaster assigns the player name. Once the countdown finishes and this
team is active, the page unlocks J1/J2/J3 controls and forwards them to the
team's existing joint-angles-test relay controller.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "2P Tag Game",
    "description": "Player view for the two-player tag game: view assigned name "
                   "and live feed, wait for the shared countdown, then drive J1/J2/J3.",
    "default_page": "",
    "pages": [{"path": "", "label": "2P Tag Game"}],
}
bp = Blueprint("player_two_player_tag_game", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
