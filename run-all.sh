#!/usr/bin/env bash
# Launch the game-master + both player sandboxes on this machine, each on its
# own port. Ctrl-C stops everything.
#
# Usage:
#   ./run-all.sh
#
# Override ports / sandbox locations via env vars:
#   GM_PORT      game-master port            (default 8000)
#   PURPLE_PORT  purple sandbox port         (default 8001)
#   GREEN_PORT   green sandbox port          (default 8002)
#   PURPLE_DIR   purple HHH-player checkout  (default ../HHH-player-purple)
#   GREEN_DIR    green  HHH-player checkout  (default ../HHH-player-green)
#
# Each player normally clones their own HHH-player; point *_DIR at wherever
# they cloned it.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

GM_PORT="${GM_PORT:-8000}"
PURPLE_PORT="${PURPLE_PORT:-8001}"
GREEN_PORT="${GREEN_PORT:-8002}"
PURPLE_DIR="${PURPLE_DIR:-$HERE/../HHH-player-purple}"
GREEN_DIR="${GREEN_DIR:-$HERE/../HHH-player-green}"

pids=()
cleanup() { echo; echo "stopping..."; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup INT TERM EXIT

echo "game-master  : http://localhost:$GM_PORT   (relay + webcam + playfield)"
( cd "$HERE/prototypes" && python3 hub.py --port "$GM_PORT" ) &
pids+=($!)

start_player() {  # label dir port
  local label="$1" dir="$2" port="$3"
  if [ -d "$dir/prototypes" ]; then
    echo "$label sandbox : http://localhost:$port   ($dir)"
    ( cd "$dir/prototypes" && python3 hub.py --port "$port" ) &
    pids+=($!)
  else
    echo "WARN: $label sandbox not found at $dir — skipping. Clone HHH-player there (or set ${label^^}_DIR)."
  fi
}
start_player purple "$PURPLE_DIR" "$PURPLE_PORT"
start_player green  "$GREEN_DIR"  "$GREEN_PORT"

echo
echo "All started. In each sandbox, open Game Link → pick team + host http://localhost:$GM_PORT,"
echo "then drive from Joint Angles / Cartesian (relay fields pre-filled). Ctrl-C to stop all."
wait
