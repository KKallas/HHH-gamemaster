"""
Auto PP calibration player tab.

Serves the shared Auto Pick and Place calibration UI as its own first-class tab.
"""

import os

from flask import Blueprint, send_from_directory

SHARED_PLAYER_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                 "green", "prototypes", "auto-pickup-game")
)

MANIFEST = {
    "name": "Auto PP calibration",
    "description": "Player calibration for Auto Pick and Place.",
    "default_page": "",
    "pages": [{"path": "", "label": "Auto PP calibration"}],
}
bp = Blueprint("player_auto_pp_calibration", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(SHARED_PLAYER_DIR, "calibrate.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
