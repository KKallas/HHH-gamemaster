"""
Player Tag Game controls.

This page is mounted in a team sandbox and reads the gamemaster Tag Game state.
The gamemaster assigns the player name. Once the countdown finishes and this
team is active, the page unlocks J1/J2/J3 controls and forwards them to the
team's existing joint-angles-test relay controller.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Tag Game",
    "description": "Player view for the tag game: view assigned name and live "
                   "feed, wait for the gamemaster countdown, then drive J1/J2/J3.",
    "default_page": "",
    "pages": [{"path": "", "label": "Tag Game"}],
}
bp = Blueprint("player_tag_game", __name__)


@bp.route("/")
def index():
    return send_from_directory(HERE, "controller.html")
