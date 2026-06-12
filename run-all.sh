#!/usr/bin/env bash
# Launch the hub: ONE server hosting all three sandboxes (gamemaster, green,
# purple) on one port. Ctrl-C stops it.
#
# Usage:
#   ./run-all.sh
#
# Override the host/port:
#   HUB_PORT=8000 ./run-all.sh        (or edit hub-config.json)
#   HUB_HOST=0.0.0.0 ./run-all.sh
#
# The startup banner prints each sandbox's URL and password (hub-config.json).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

args=()
[ -n "${HUB_PORT:-}" ] && args+=(--port "$HUB_PORT")
[ -n "${HUB_HOST:-}" ] && args+=(--host "$HUB_HOST")

exec python3 "$HERE/hub.py" "${args[@]}"
