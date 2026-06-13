# Tag Game (gamemaster referee/operator + game screen)

The camera-confirmed tag pickup/deposit game, separated from the playfield
editor. This machine owns the **game flow**; the zones it plays on belong to
the [playfield-areas](../playfield-areas/) prototype, the camera feed and tag
tracking come from the [webcam](../webcam/) prototype, and the robot state from
the [dobot-mg400-relay](../dobot-mg400-relay/) prototype. It keeps shared round
state under `/p/tag-game/api/state`, while the browser still drives the
playfield, webcam, and relay APIs directly.

## Pages

- `game.html` — the embedded 90 second game screen with the gamemaster desk
  pinned to the bottom of the Tag Game tab.
- `controller.html` — the **gamemaster referee/operator setup helper**. Two
  controls: **Reset to tag game areas** replaces the playfield with the two
  shared zones named `pickup` and `deposit` (ArUco hidden on both), and
  **Go to game screen** returns to the embedded game view. The status line shows
  live whether the game zones are in place on the playfield.

## Game flow

The gamemaster acts as referee and operator: they use the Tag Game tab to run
the embedded game screen, and can use the setup helper to reset the playfield to
the game areas or reposition them on the playfield controller if needed.

The **game screen** uses the Webcam prototype's live feed as its display layer.
The bottom gamemaster desk is where the referee/operator selects the purple or
green team, enters the player name, chooses the physical ArUco tag id to track,
including the Webcam prototype's Atom-screen ids `100`-`105`, calibrates the
robot, starts or resets the round, and watches live progress plus the current
high-score table. A camera overlay and matching live monitor tiles show the
distance to the target area and whether the tag is still visible, hidden during
pickup, picked up, or delivered. The game stores the team, player name, tag id, active radius,
team/player stats, and the confirmed robot deposit-center pose in browser
storage so they come back after a restart. The playfield screen is cleared when
the game page opens and whenever a new setup starts. Press **Turn on calibration target**
only when the green target is needed for calibration, then move the robot to its
center and press **Confirm robot at green center** to save or replace that arm
calibration. On that confirm press, the game samples the visible green target
once and places the green circular scoring overlay around it, so the circle
matches the robot arm tip/drop-off center. It does not keep tracking the green
square live after calibration.

Once the round starts, the gamemaster desk stays visible for operation and
monitoring. The playfield is cleared and the game creates only the blue `pickup`
area at its fixed game location. The play view keeps the countdown, robot scoring
panel, progress display, and high-score table over the webcam feed. The green
`deposit` area and active-area overlay stay hidden until the configured tag has
been blocked from camera view for 3 continuous seconds, which usually means the
robot has picked it up. At that point the game creates the green destination
square at its fixed game location and shows the saved active drop-off circle
from calibration. The scoring panel shows the saved target coordinates, live arm
coordinates, distance to target, active radius, suction state, team/player,
rounds, wins, losses, best win time, average win time, and last improvement. The
distance turns green once the arm is inside the win radius, so the gamemaster
can confirm that releasing suction should finish the game.

Purple and green are the competing teams. The active team uses the robot manually
to pick up the physical tag from inside the blue `pickup` area and deposit it
inside the green `deposit` area.
During the round the game polls both the Webcam prototype and the Dobot MG400
Relay state. It prefers the selected team's relay arm pose, matching the **Pose
X/Y/Z/R** shown on the relay page, and falls back to the relay target only if
live feedback is blank. The game is won when the selected arm pose is inside the
configured radius around the confirmed deposit center, suction has been used
and then released, and the camera does not see the configured tag outside the
green active-area overlay. If the robot blocks the camera and the tag is not
visible at scoring time, that is treated as a valid visual confirmation rather
than a failure. Both the `pickup` and `deposit` playfield areas remain fixed at
size 3 for the whole round.

## Operator State Updates

The operator `game.html` intentionally uses short JSON polling for playfield
state, player ready/name state, and relay state. Do not change these operator
state readers back to long-lived `EventSource`/SSE streams.

Why: the operator screen already holds a long-lived MJPEG webcam stream, and the
player screens also keep live feeds/events open. In the local threaded hub this
can starve or queue important one-shot requests, especially **Start game**. The
observed failure was: Start became active, the operator countdown appeared but
stayed stuck at `5`, and the Purple player never received the gamemaster
countdown because the shared `/p/tag-game/api/operator` POST did not complete
reliably.

How it is done now:

- Playfield state is polled with `/p/playfield-areas/api/state`.
- Player ready/name state is polled with `/p/tag-game/api/state`.
- Relay state is polled with `/p/dobot-mg400-relay/api/state`.
- Webcam tag setup already polls `/p/webcam/api/tags`; the operator page does
  not open a second webcam SSE connection.

Keep polling intervals modest, around 700-900 ms. These are UI status updates,
not control-loop traffic. If SSE is reconsidered later, test with all real
surfaces open at once: gamemaster operator, Purple player, webcam stream, and
relay connected. The acceptance test is that pressing **Start game** updates the
server state to `phase: "countdown"`, the operator countdown advances past `5`,
and the Purple player sees the countdown.

## Files

- `prototype.py` — page-serving blueprint only (no API), mounted by the hub
  under `/p/tag-game`. See [../README.md](../README.md).
- `controller.html` — referee panel: reset game zones + open the game screen
- `game.html` — fullscreen 90 second tag pickup/deposit game screen
