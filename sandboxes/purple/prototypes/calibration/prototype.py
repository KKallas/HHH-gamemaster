"""
Calibration — player capture tool.

Thin client: serves the capture UI (controller.html). All session state lives in
the gamemaster's calibration machine (/s/gamemaster/p/calibration); this page
talks to it over the hub's shared-API door, reads the shared webcam's ArUco tags,
and drives THIS side's own cartesian-xyz-test arm. Active only while the game
master has selected this side for calibration.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Calibration",
    "description": "Capture this side's camera-pixel + robot-XYZ for the four corner "
                   "markers, when the game master selects you for calibration.",
    "default_page": "",
    "pages": [{"path": "", "label": "Capture"}],
}
bp = Blueprint("calibration", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
