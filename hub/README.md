# hub — the engine

This folder is the **engine**: the content-free part that hosts *machines* in
password-protected *sandboxes*. It knows how to discover, mount, gate, and
serve them, but ships none itself. The machines — the local content you build
and edit — live under `../sandboxes/<name>/prototypes/`.

It started as a vendored copy of Manual Override's single-sandbox engine and
has diverged: one server now hosts several sandboxes with auth, service
tokens, and setup export/import.

## What's here

| File             | Role                                                            |
|------------------|-----------------------------------------------------------------|
| `__init__.py`    | `Hub` (config/auth/dispatch) + `Sandbox` (discovery, mounting, dashboard, export/import) |
| `live.py`        | shared push helper (SSE); machines `import live`                |
| `dashboard.html` | the sandbox shell UI (one tab per machine, export/import header)|
| `login.html`     | per-sandbox password page                                       |
| `landing.html`   | `/` — links the sandboxes                                       |
| `theme.css`      | shared visual theme, linked by every machine page (public)      |

## Running

Use the launcher at the repo root:

```bash
pip install -r requirements.txt
python ../hub.py     # http://localhost:8000
```

Or embed the engine directly:

```python
from hub import Hub
Hub(root_dir="/path/to/repo").run(port=8000)   # expects <root>/sandboxes/<name>/prototypes
```

Sandbox names, labels, accents, passwords, the port, and the cookie secret live
in `<root>/hub-config.json`, created on first run (see `DEFAULT_SANDBOXES` in
`__init__.py`). The startup banner prints every sandbox's URL + password.

## URLs and auth

* `/` — landing page (public); `/theme.css` (public).
* `/s/<sandbox>/` — that sandbox's dashboard; `/s/<sandbox>/p/<slug>/...` — its machines.
* `/s/<sandbox>/login`, `/logout` — cookie auth. A sandbox's password unlocks
  it; a sandbox configured `"admin": true` (the gamemaster) unlocks all.
* `shared_api` in a sandbox's config (e.g. `{"dobot-mg400-relay": ["green", "purple"]}`)
  lets the listed roles call that machine's `/api/` endpoints across the sandbox
  boundary. The hub puts the caller's authenticated roles in
  `request.environ["hhh.roles"]` so the machine can enforce finer rules
  (the relay enforces side == team).
* Server-side cross-sandbox calls authenticate with the per-process **service
  token** a machine receives via `hub_init(ctx)` (`ctx.service_token`), sent as
  the `X-HHH-Auth` header.
* `/s/<sandbox>/api/export` (zip download) and `/api/import` (zip upload —
  replaces `prototypes/`, keeps the old one as `prototypes.prev`, restarts the
  hub).

## The machine contract

A machine is any sub-folder of a sandbox's `prototypes/` with a `prototype.py`
that defines:

```python
MANIFEST = { "name", "description", "default_page", "pages": [...] }
bp       = flask.Blueprint(...)   # pages + API, all paths relative to /s/<sandbox>/p/<slug>/
```

Optional: a `hub_init(ctx)` hook receives a `HubContext`:

* `ctx.sandbox` — the sandbox name (a player machine's team);
* `ctx.service_token` — auth for cross-sandbox HTTP calls;
* `ctx.local_base` — this server's own base URL (`http://127.0.0.1:<port>`);
* `ctx.is_enabled()` / `ctx.get_prototype(slug)` / `ctx.is_prototype_enabled(slug)`
  — same-sandbox machine lookups.

Shared helpers like `live` are importable by plain name — the engine puts this
folder on `sys.path` during discovery. A machine's OWN sibling modules
(e.g. `relay_client.py`) import by plain name too; the engine purges them from
`sys.modules` after each machine loads so the same-named copy in another
sandbox loads independently.

Keep page URLs relative (or derive the sandbox prefix from
`location.pathname`, as pickup-game does) — machines are mounted under
`/s/<sandbox>/p/<slug>`, and the prefix is not fixed.
