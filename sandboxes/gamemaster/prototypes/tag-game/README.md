# Tag Game (referee controller + game screen)

The camera-confirmed tag pickup/deposit game, separated from the playfield
editor. This machine owns the **game flow**; the zones it plays on belong to
the [playfield-areas](../playfield-areas/) prototype, the camera feed and tag
tracking come from the [webcam](../webcam/) prototype, and the robot state from
the [dobot-mg400-relay](../dobot-mg400-relay/) prototype. It has no server
state of its own — both pages drive those prototypes' APIs from the browser.

## Pages

- `controller.html` — the **referee panel** the hub embeds in its tab. Two
  controls: **Reset to tag game areas** replaces the playfield with the two
  shared zones named `pickup` and `deposit` (ArUco hidden on both), and
  **Open game screen ↗** opens the fullscreen game view. The status line shows
  live whether the game zones are in place on the playfield.
- `game.html` — the fullscreen 90 second game screen.

## Game flow

The referee resets the playfield to the game areas, repositions them on the
playfield controller if needed, then opens the game screen.

The **game screen** uses the Webcam prototype's live feed as its display layer.
Before the round starts, it asks for the player name and lets you choose the
physical ArUco tag id to track, including the Webcam prototype's Atom-screen
ids `100`-`105`. The game stores the player name, tag id, active radius, player
stats, and the confirmed robot deposit-center pose in browser storage so they
come back after a restart. The playfield screen is cleared when the game page
opens and whenever a new setup starts. Press **Turn on target for calibration**
only when the green target is needed for calibration, then move the robot to its
center and press **Confirm robot at green center** to save or replace that arm
calibration. On that confirm press, the game samples the visible green target
once and places the green circular scoring overlay around it, so the circle
matches the robot arm tip/drop-off center. It does not keep tracking the green
square live after calibration.

Once the round starts, the setup controls disappear, the playfield is cleared,
and the game creates only the blue `pickup` area at its fixed game location. The
play view keeps the countdown, restart button, and robot scoring panel over the
webcam feed. The green `deposit` area and active-area overlay stay hidden until
the configured tag has been blocked from camera view for 3 continuous seconds,
which usually means the robot has picked it up. At that point the game creates
the green destination square at its fixed game location and shows the saved
active drop-off circle from calibration. The scoring panel shows the saved
target coordinates, live arm coordinates, distance to target, active radius,
suction state, player, rounds, wins, losses, best win time, average win time,
and last improvement. The distance turns green once the arm is inside the win
radius, so the player knows that releasing suction should finish the game.

The purple player uses the robot manually to pick up the physical tag from
inside the blue `pickup` area and deposit it inside the green `deposit` area.
During the round the game polls both the Webcam prototype and the Dobot MG400
Relay state. It prefers the relay's purple arm pose, matching the **Pose
X/Y/Z/R** shown on the relay page, and falls back to the relay target only if
live feedback is blank. The game is won when the arm pose is inside the
configured radius around the confirmed deposit center, suction has been used
and then released, and the camera does not see the configured tag outside the
green active-area overlay. If the robot blocks the camera and the tag is not
visible at scoring time, that is treated as a valid visual confirmation rather
than a failure. Both the `pickup` and `deposit` playfield areas remain fixed at
size 3 for the whole round.

## Files

- `prototype.py` — page-serving blueprint only (no API), mounted by the hub
  under `/p/tag-game`. See [../README.md](../README.md).
- `controller.html` — referee panel: reset game zones + open the game screen
- `game.html` — fullscreen 90 second tag pickup/deposit game screen
