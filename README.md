# HHH-gamemaster

The **game-master host** for the HHH game. It runs the [Manual Override](https://github.com/KKallas/manual-override) hub engine over a fixed set of game-host machines:

| Machine | Role |
|---|---|
| `dobot-mg400-relay` | Owns the MG400 arm; arbitrates control between the **purple** and **green** sides with a safety filter (joint/workspace clamps, lease watchdog, latched E-stop). Remote player controllers connect to it over HTTP. |
| `webcam` | OpenCV capture + ArUco tag detection. |
| `playfield-areas` | The playfield zone visualization. |

This repo is the **gamehost configuration**: the engine is vendored in `hub/`, and the machines it hosts are the three folders under `prototypes/`. Player-side controllers (joint-angles, cartesian) live in Manual Override and connect here by picking **Relay** mode + their side.

## Run

```bash
pip install -r requirements.txt
cd prototypes && python hub.py        # http://localhost:8000
```

Open the **Dobot MG400 Relay** tab (operator view): connect the arm (default `192.168.1.6`), enable it, and the two sides can then acquire control from their own controllers.

### How a player connects

In a Manual Override joint-angles or cartesian controller, switch **Link** to **Relay**, set the host to this machine (e.g. `http://<gamemaster-ip>:8000`), pick **Purple** or **Green**, and Connect. Only one side holds the arm at a time; the other is told who's holding it. If a controller goes quiet, its lease expires (~2s) and the arm smooth-stops and frees the floor.

## Updating the engine

The engine is vendored from Manual Override's `hub/` subdir. To pull a newer engine without touching the machines:

```bash
python hub/upgrade.py --check     # is a newer engine available?
python hub/upgrade.py             # apply it, then restart
```

`hub/hub.json` is already pointed at `KKallas/manual-override` (`engine_path: "hub"`). See `hub/UPDATING.md` for the contribute-back flow. Updating the **machines** (relay/webcam/playfield) is a manual copy from Manual Override for now — they're the game-host content, versioned with this repo.
