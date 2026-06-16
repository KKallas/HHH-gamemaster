"""
Pick & Place v2 — player controller (click-to-place).

Serves controller.html and drives THIS side's own cartesian-xyz-test arm. The
player loads their team's calibration CSV; clicking the (shared) camera sends the
tool to that workspace X/Y via a 4-point corner-pin homography, at a move height
a fixed offset above the calibrated pickup height. The game master watches from a
referee page in the gamemaster sandbox.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Pick & Place v2",
    "description": "Click the camera to send your arm there (corner-pin calibration), "
                   "with a calibrated pickup height and a move-height offset.",
    "default_page": "",
    "pages": [{"path": "", "label": "Controller"}],
}
bp = Blueprint("pick_place_v2", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "controller.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
