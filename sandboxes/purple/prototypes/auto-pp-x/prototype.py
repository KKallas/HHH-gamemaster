"""
Auto PP X player tab.

Serves the shared Auto Pick and Place player UI with the Auto PP X workflow
enabled. The page still talks to the gamemaster auto-pickup-game APIs for
registration, timing, calibration, webcam tags, and scorekeeping.
"""

import os

from flask import Blueprint, send_from_directory

SHARED_PLAYER_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                 "green", "prototypes", "auto-pickup-game")
)

MANIFEST = {
    "name": "Auto PP X",
    "description": "Player Auto Pick and Place workflow using visible ArUco "
                   "source and destination tags.",
    "default_page": "",
    "pages": [{"path": "", "label": "Auto PP X"}],
}
bp = Blueprint("player_auto_pp_x", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(SHARED_PLAYER_DIR, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
