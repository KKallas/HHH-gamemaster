"""
Player view for the single-player Pick & Place game.

Mounted in a team sandbox. The player enters their name, presses Start (the
gamemaster clock begins), then drives J1-J4 + the air pump through this team's
joint-angles-test relay controller to move the block from one square to the
other. Pressing Done stops the clock; the gamemaster logs the time to CSV.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Pick & Place",
    "description": "Player view for the pick-and-place game: enter name, watch "
                   "the live feed, Start, drive J1-J4 + pump, then Done.",
    "default_page": "",
    "pages": [{"path": "", "label": "Pick & Place"}],
}
bp = Blueprint("player_pickup_game", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
