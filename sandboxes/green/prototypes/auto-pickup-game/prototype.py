"""
Player view for the Auto Pick and Place game.

Mounted in a team sandbox. The page registers a default player name for this
team, opens directly to the play screen, then drives J1-J4 + the air pump
through this team's joint-angles-test relay controller to move the block from
one square to the other. The gamemaster logs the time to CSV.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Auto Pick and Place",
    "description": "Player view for the pick-and-place game: auto-register, "
                   "watch the live feed, drive J1-J4 + pump, then finish.",
    "default_page": "",
    "pages": [{"path": "", "label": "Auto Pick and Place"}],
}
bp = Blueprint("player_auto_pickup_game", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
