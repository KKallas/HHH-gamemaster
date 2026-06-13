# HHH-gamemaster

The **single host** for the HHH game: ONE server (the [Manual Override](https://github.com/KKallas/manual-override)-derived hub engine in `hub/`) serving **three password-protected sandboxes**, each with its own folder of machines:

| Sandbox | URL | Machines |
|---|---|---|
| `gamemaster` | `/s/gamemaster/` | `dobot-mg400-relay`, `webcam`, `playfield-areas`, `tag-game`, `atom-manager`, `joint-angles-test`, `cartesian-xyz-test` |
| `green` | `/s/green/` | `tag-game`, `game-link`, `joint-angles-test`, `cartesian-xyz-test`, `playfield-areas` |
| `purple` | `/s/purple/` | `tag-game`, `game-link`, `joint-angles-test`, `cartesian-xyz-test`, `playfield-areas` |

The machines live under `sandboxes/<name>/prototypes/`. The hub engine is shared — there is exactly one server process and one port.

## Run

```bash
pip install -r requirements.txt
python hub.py            # or ./run-all.sh — http://localhost:8000
```

The landing page at `/` links the three sandboxes. The startup banner prints each sandbox's URL **and password**.

## Access control

Passwords live in `hub-config.json` (created on first run, git-ignored, freely editable — restart after editing). Logging in at a sandbox sets a signed cookie:

* **green / purple** are team sandboxes and unlock only their own side — teams cannot open each other's panels, nor the gamemaster's pages or APIs.
* **gamemaster** unlocks all three as the referee and operator.

Player controllers still drive their arm through the gamemaster's relay: the hub admits their server-side calls to the relay's API (a per-sandbox service token, see `shared_api` in `hub-config.json`), and the relay **enforces side = your team**, so a green controller can never acquire, move, or kick the purple arm. Note the trust model is per-sandbox code execution: importing a setup zip runs that sandbox's `prototype.py` files on this host.

## Export / import a working setup

Each sandbox dashboard has **⤓ export** / **⤒ import** in the header (next to the prototype count):

* **Export** downloads `hhh-<sandbox>-setup.zip` — the sandbox's whole `prototypes/` folder, runtime settings included.
* **Import** uploads such a zip (or any zip of `<machine>/prototype.py` folders): the current setup is kept server-side as `sandboxes/<name>/prototypes.prev`, the zip replaces `prototypes/`, and the hub restarts itself to load it.

This replaces the old per-player git clones: players carry their setup as a zip.

### Operator takeover

The two direct controllers (`joint-angles-test`, `cartesian-xyz-test` in the gamemaster sandbox) let the gamemaster referee/operator step in and drive an arm by hand. **Only one thing can hold an arm connection at a time**, so to take over: **disable the `dobot-mg400-relay` machine** (toggle it off in the gamemaster dashboard — this drops the relay's arm connections; the watchdog smooth-stops first), then open a direct controller in **Direct** mode and connect to the arm IP. Re-enable the relay to hand control back to the sides.

Open the **Dobot MG400 Relay** tab (operator view): connect each side's arm (defaults `192.168.1.6` purple / `192.168.1.7` green), enable them, and the two sides can then acquire control from their own controllers.

### How a player connects

A player opens `http://<host>:8000/s/green/` (or `/s/purple/`), enters their team password, and uses **Game Link** to confirm the connection (team + host default to their own sandbox and this server). The joint / cartesian controllers pre-fill from it; Connect acquires their side's arm through the relay. If a controller goes quiet, its lease expires (~2 s) and that arm smooth-stops and frees the side.

### PlatformIO for ESP firmware

PlatformIO is installed repo-locally in `.venv/`. Use the repo-local core
directory so PlatformIO stores packages inside this checkout instead of
`~/.platformio`:

```bash
PLATFORMIO_CORE_DIR="$PWD/.platformio" PLATFORMIO_SETTING_ENABLE_TELEMETRY=no .venv/bin/pio --version

cd ESP/atom-image-server
PLATFORMIO_CORE_DIR="../../.platformio" PLATFORMIO_SETTING_ENABLE_TELEMETRY=no ../../.venv/bin/pio run

cd ../wt32-image-server
PLATFORMIO_CORE_DIR="../../.platformio" PLATFORMIO_SETTING_ENABLE_TELEMETRY=no ../../.venv/bin/pio run
```

## The engine

`hub/` is the engine (discovery, mounting, dashboard, auth, export/import); `hub/README.md` documents the machine contract. It started as a vendored copy of Manual Override's engine but has since diverged (multi-sandbox + auth), so the old `upgrade.py` flow no longer applies.
