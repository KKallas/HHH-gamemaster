#!/usr/bin/env bash
# Stop the game-master and player sandbox hubs so the system can restart cleanly.
#
# Usage:
#   ./stop-all.sh
#
# Override ports with the same env vars used by run-all.sh:
#   GM_PORT      game-master port    (default 8000)
#   PURPLE_PORT  purple sandbox port (default 8001)
#   GREEN_PORT   green sandbox port  (default 8002)
#
# If a process is protected and normal kill is denied:
#   USE_SUDO=1 ./stop-all.sh
set -u

GM_PORT="${GM_PORT:-8000}"
PURPLE_PORT="${PURPLE_PORT:-8001}"
GREEN_PORT="${GREEN_PORT:-8002}"
USE_SUDO="${USE_SUDO:-0}"

ports=("$GM_PORT" "$PURPLE_PORT" "$GREEN_PORT")

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

for port in "${ports[@]}"; do
  stop_port "$port"
done

echo "done"
