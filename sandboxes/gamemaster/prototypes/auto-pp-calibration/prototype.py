"""
Auto PP calibration operator tab.

This is a separate gamemaster tab for the Auto Pick and Place calibration flow.
It reuses the calibration APIs owned by the auto-pickup-game prototype.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Auto PP calibration",
    "description": "Operator controls for Auto Pick and Place calibration: "
                   "create playfield calibration tags, enable one player at a time, "
                   "and re-enable both arms when calibration is complete.",
    "default_page": "",
    "pages": [{"path": "", "label": "Auto PP calibration"}],
}
bp = Blueprint("auto_pp_calibration_operator", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
