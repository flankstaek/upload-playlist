# CLAUDE.md

Guidance for working in this repo. Keep it accurate as the code changes.

## What this is

A single-file [Nicotine+](https://nicotine-plus.github.io/) plugin that writes a
live M3U playlist of audio files other Soulseek users download from you. All
plugin code is in `__init__.py`. Design rationale and lessons live in
[`docs/architecture.md`](docs/architecture.md) — read it before non-trivial
changes; it explains *why* things are the way they are.

## Hard constraints

These shape almost every decision — don't fight them:

- **Runtime is stdlib-only.** Nicotine+ ships its own Python and can't install
  packages, so `__init__.py` must import nothing beyond the standard library
  (`sqlite3`, `json`, `os`, etc.). Dev tooling (pytest, ruff) is separate and
  never ships.
- **The plugin folder *is* the package.** Nicotine+ uses the folder name as the
  plugin ID and loads `__init__.py` directly from it. So: no `src/` layout,
  `__init__.py` stays at the repo root, and the installed folder must be named
  `upload_playlist` (underscore), even though the repo is `upload-playlist`.
- **`pynicotine` isn't pip-installable** (it's a desktop app, not a library).
  Tests import the plugin via a `BasePlugin` shim that `tests/conftest.py`
  injects into `sys.modules` before import.

## Layout

- `__init__.py` — all plugin code (the `Plugin` class).
- `PLUGININFO` — Nicotine+ metadata (name, author, version). Version is managed by `release.sh`.
- `tests/` — pytest suite. `conftest.py` holds the `BasePlugin` shim.
- `install.sh` — copies the plugin into the Nicotine+ plugins dir (handles the WSL→Windows case).
- `release.sh` — bumps `PLUGININFO`, tags (CalVer), pushes to both remotes.
- `docs/` — `architecture.md` (design) and `nicotine-plugin-dev-reference.md` (API reference).

## Dev commands

Requires [`uv`](https://docs.astral.sh/uv/).

```
uv sync                    # install dev deps into .venv/
uv run pytest              # run tests
uv run ruff check          # lint
uv run ruff format         # format
```

Run `ruff format` and `ruff check` before committing — CI gates on both
(`ruff format --check`, `ruff check`, `pytest`) on every push/PR to `main`.

## Testing model

pytest covers the logic: DB schema/migration, write-time dedup, `_regenerate_m3u`
output per ordering mode, the `init()` case matrix, the live hook, extension
filtering, and cross-platform data-dir discovery. It does **not** test against a
real Nicotine+ — anything that depends on the live API binding (plugin loads,
settings appear in the UI, `upload_finished_notification` actually fires,
external-player behavior on M3U rewrite) is verified by a manual smoke test:
`./install.sh`, toggle the plugin in Preferences, exercise it. Use pytest for
logic; use the manual toggle for API-binding bugs.

## Conventions

- Match the existing style in `__init__.py`: open-per-write DB/file access (no
  long-lived handles on `self`), `INSERT OR IGNORE` for idempotency, full
  regeneration via temp-file + `os.replace` for atomic swaps.
- SQLite is the source of truth; the M3U is a regeneratable projection. New
  features should query the DB, not parse the M3U.
- When adding logic, add the matching pytest case in the same change.
</content>
