#!/usr/bin/env python3
"""Show — and optionally kill — running hub.py processes.

The hub sometimes lingers (an orphaned copy, or a second instance on another
port) which makes "why won't it connect / why is the arm still held" hard to
debug. This lists every hub.py process with the TCP port(s) it is listening on,
and can kill them.

Usage:
    python3 hubctl.py             # list hub.py processes
    python3 hubctl.py --kill      # SIGTERM them, then report any survivors
    python3 hubctl.py --kill -9   # SIGKILL them (force)
"""
import os
import re
import signal
import subprocess
import sys
import time


def hub_pids():
    """[(pid, command), ...] for every running hub.py — never this script itself."""
    out = subprocess.run(
        ["ps", "-axww", "-o", "pid=,command="],
        capture_output=True, text=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        line = line.strip()
        pid_s, _, cmd = line.partition(" ")
        if not pid_s.isdigit():
            continue
        pid = int(pid_s)
        if pid == os.getpid():
            continue
        parts = cmd.split()
        if not parts:
            continue
        # The EXECUTABLE (first token) must be a python interpreter — this rejects
        # shells/editors whose arguments merely contain the text "hub.py" (e.g. the
        # command that launched this very script).
        exe = os.path.basename(parts[0]).lower()
        if not exe.startswith("python"):
            continue
        if not any(os.path.basename(p) == "hub.py" for p in parts):
            continue
        rows.append((pid, cmd))
    return rows


def port_of(cmd):
    """The hub's configured port from its command line (hub.py defaults to 8000)."""
    m = re.search(r"--port[=\s]+(\d+)", cmd)
    return m.group(1) if m else "8000 (default)"


def started(pid):
    return subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True, text=True,
    ).stdout.strip()


def main():
    args = sys.argv[1:]
    do_kill = "--kill" in args or "-k" in args
    hard = "-9" in args or "--force" in args

    rows = hub_pids()
    if not rows:
        print("No hub.py processes running.")
        return

    print(f"{len(rows)} hub.py process(es):\n")
    for pid, cmd in rows:
        print(f"  PID {pid}  port={port_of(cmd)}  started={started(pid)}")
        print(f"      {cmd}")

    if not do_kill:
        print("\n(run with --kill to stop them, or --kill -9 to force)")
        return

    sig = signal.SIGKILL if hard else signal.SIGTERM
    print(f"\nSending {sig.name} to {len(rows)} process(es)...")
    for pid, _ in rows:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  PID {pid}: permission denied")
    time.sleep(1.0)

    survivors = hub_pids()
    if survivors:
        print("Still alive:", ", ".join(str(p) for p, _ in survivors),
              "— try: python3 hubctl.py --kill -9")
    else:
        print("All hub.py processes stopped.")


if __name__ == "__main__":
    main()
