"""
Launcher — runs the hub engine over the three sandboxes in THIS repo.

The engine lives in `hub/`; the content it hosts is the machines under
`sandboxes/<name>/prototypes/` (gamemaster, green, purple). Passwords and the
port live in `hub-config.json` (created on first run; the startup banner
prints each sandbox's URL + password).

Run:
    pip install -r requirements.txt
    python hub.py            # then open http://localhost:8000

Flags:
    --host  (default 0.0.0.0)
    --port  (default: the port in hub-config.json, normally 8000)
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hub import Hub


def main():
    parser = argparse.ArgumentParser(description="Manual Override — sandbox hub launcher")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None,
                        help="override the port in hub-config.json")
    args = parser.parse_args()
    Hub(root_dir=ROOT).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
