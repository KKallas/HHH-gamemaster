"""
Tag-game prototype — the referee's controller for the camera-confirmed tag game.

This machine owns the GAME, not the playfield: the zones it plays on belong to
the playfield-areas prototype, and the live camera/robot state comes from the
webcam and dobot-mg400-relay prototypes. It serves two pages and has no API or
state of its own — all game flow runs in the browser against those prototypes:

  * controller.html — the referee panel the hub embeds in its tab: reset the
                      playfield to the shared pickup/deposit zones and open the
                      fullscreen game view.
  * game.html       — the fullscreen 90 second game screen over the webcam feed
                      (player/tag setup, robot calibration, scoring).

This module is loaded by hub.py and registered under /p/tag-game.
"""

import os

from flask import Blueprint, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))

# Every prototype exposes these two names for the hub:
MANIFEST = {
    "name": "Tag Game",
    "description": "Referee controls for the camera-confirmed tag game: set up "
                   "the pickup/deposit zones on the playfield and open the "
                   "fullscreen game screen.",
    "default_page": "controller",   # what the hub embeds in its tab
    "pages": [
        {"path": "controller", "label": "Referee"},
        {"path": "game", "label": "Open game screen ↗", "newtab": True},
    ],
}
bp = Blueprint("tag_game", __name__)


@bp.route("/")
@bp.route("/controller")
def controller():
    return send_from_directory(HERE, "controller.html")


@bp.route("/game")
def game():
    return send_from_directory(HERE, "game.html")
