"""
Player view for the Auto Pick and Place game.

Mounted in a team sandbox. The player enters a name first, then drives XYZ +
the air pump through this team's cartesian relay controller to move the block
from one square to the other. The gamemaster logs the time to CSV.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED_PLAYER_DIR = os.path.abspath(
    os.path.join(HERE, "..", "..", "..", "green", "prototypes", "auto-pickup-game")
)

MANIFEST = {
    "name": "Auto Pick and Place",
    "description": "Player view for the pick-and-place game: enter name, "
                   "watch the live feed, drive XYZ + pump, then finish.",
    "default_page": "",
    "pages": [{"path": "", "label": "Auto Pick and Place"}],
}
bp = Blueprint("player_auto_pickup_game", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(SHARED_PLAYER_DIR, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/calibrate")
def calibrate():
    resp = send_from_directory(SHARED_PLAYER_DIR, "calibrate.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
