"""
Pick & Click — simplified pick-and-place control.

Click anywhere on the live camera to send the arm's tool to that X/Y, and use a
single slider for Z (up / down). Built so students spend their attention
*coordinating the two arms* instead of fighting four joint sliders — "just get
the head to go where I want."

There is no arm backend here: motion runs on this sandbox's own
``cartesian-xyz-test`` machine (Connect + Enable it from this page). The
pixel -> workspace mapping is a homography the user calibrates in-browser by
capturing a few (camera-click, arm-pose) pairs; it lives in localStorage.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

MANIFEST = {
    "name": "Pick & Click",
    "description": "Click the camera to place the arm in X/Y; one slider for Z. "
                   "Drives this sandbox's cartesian-xyz-test arm through a "
                   "calibrated pixel->workspace homography.",
    "default_page": "",
    "pages": [{"path": "", "label": "Controller"}],
}
bp = Blueprint("pick_click", __name__)


@bp.route("/")
def index():
    resp = send_from_directory(HERE, "index.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
