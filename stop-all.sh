#!/usr/bin/env bash
# Stop the hub (all three sandboxes share one server/port) so it can restart
# cleanly.
#
# Usage:
#   ./stop-all.sh
#
# Override the port with the same env var used by run-all.sh:
#   HUB_PORT=8000 ./stop-all.sh
#
# If the process is protected and normal kill is denied:
#   USE_SUDO=1 ./stop-all.sh
set -u

HUB_PORT="${HUB_PORT:-8000}"
USE_SUDO="${USE_SUDO:-0}"

listening_pids() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u
}

stop_port() {
  local port="$1"
  local pids

  pids="$(listening_pids "$port")"
  if [ -z "$pids" ]; then
    echo "port $port: already clear"
    return
  fi

  echo "port $port: stopping $(echo "$pids" | tr '\n' ' ')"
  if [ "$USE_SUDO" = "1" ]; then
    echo "$pids" | xargs sudo kill -TERM || true
  else
    echo "$pids" | xargs kill -TERM || true
  fi

  for _ in 1 2 3 4 5; do
    sleep 0.2
    pids="$(listening_pids "$port")"
    [ -z "$pids" ] && break
  done

  if [ -n "$pids" ]; then
    echo "port $port: force stopping $(echo "$pids" | tr '\n' ' ')"
    if [ "$USE_SUDO" = "1" ]; then
      echo "$pids" | xargs sudo kill -KILL || true
    else
      echo "$pids" | xargs kill -KILL || true
    fi
  fi

  pids="$(listening_pids "$port")"
  if [ -n "$pids" ]; then
    echo "port $port: still occupied by $(echo "$pids" | tr '\n' ' ')"
    if [ "$USE_SUDO" != "1" ]; then
      echo "port $port: try USE_SUDO=1 ./stop-all.sh"
    fi
  fi
}

stop_port "$HUB_PORT"

echo "done"
