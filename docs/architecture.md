# Architecture

## What this is

A Nicotine+ plugin that writes a live M3U playlist of audio files other Soulseek users download from you. Every successful upload is appended to the playlist in real time, so you can open it in VLC/foobar2000/etc. to replay "what got shared."

## Repo layout

```
upload-playlist/
├── PLUGININFO          # Nicotine+ plugin metadata
├── __init__.py         # All plugin code (single-file by convention)
├── install.sh          # Copies plugin into Windows-side Nicotine+ plugins dir
└── docs/
    ├── architecture.md                    # This file
    ├── roadmap.md                         # Planned work
    └── nicotine-plugin-dev-reference.md   # Condensed plugin API reference
```

The plugin folder *is* the repo — Nicotine+ treats each plugin folder as self-contained, and the folder name is the internal plugin ID. We use the repo directly rather than nesting under a subfolder.

## Dev environment

- Repo lives in WSL (`/home/conan/dev/upload-playlist/`)
- Nicotine+ runs natively on Windows, reading plugins from `C:\Users\conan\AppData\Roaming\nicotine\plugins\upload_playlist\`
- Windows can't follow Linux symlinks, so `install.sh` copies `PLUGININFO` and `__init__.py` into the Windows plugins dir
- After running `install.sh`, toggle the plugin off/on in Nicotine+ Preferences → Plugins to reload

## Tooling and tests

The plugin's *runtime* is stdlib-only — Nicotine+ ships its own Python and can't install packages, so nothing we add to dev tooling reaches end users.

**Dev stack:**
- `uv` for environment + dependency management (one Rust binary; replaces `pip` + `venv` + `pyenv` + `pip-tools`)
- `pytest` for unit tests
- `ruff` for lint + format (replaces `flake8` + `black` + `isort`)
- `pyproject.toml` for all config

Common commands: `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run ruff format`.

**Why no `src/` layout:** Nicotine+ uses the plugin folder name as the internal plugin ID and loads `__init__.py` directly from it. Moving `__init__.py` under a subdirectory would break the install. So `__init__.py` stays at the repo root, tests live in `tests/`, and the test harness imports the repo root as the package.

**`BasePlugin` shim:** `pynicotine` isn't pip-installable — it's a desktop application, not a library. Importing `__init__.py` outside Nicotine+ fails with `ModuleNotFoundError: No module named 'pynicotine'`. `tests/conftest.py` works around this by inserting a fake `pynicotine.pluginsystem` module into `sys.modules` before the plugin is imported. The fake `BasePlugin` is a no-op stub with empty `__init__`, `log`, and `output` methods.

**Testing model (what is tested where):**

| Surface | How |
|---|---|
| DB schema creation + idempotency | `pytest` (`test_history_db.py`) |
| `_record_upload` write-time dedup via `UNIQUE` index | `pytest` (`test_history_db.py`) |
| `_regenerate_m3u` output: chronological order, NULL-ts ordering, extension filter, dedup on/off | `pytest` (`test_history_db.py`) |
| `_import_uploads_json` idempotency, status filtering, `st_mtime`/NULL ts | `pytest` (`test_history_db.py`) |
| `init()` lifecycle: four cases (DB × M3U existence matrix) | `pytest` (`test_init_lifecycle.py`) |
| Live hook end-to-end: append to M3U, record in DB, dedup-on skip | `pytest` (`test_init_lifecycle.py`) |
| Extension filter (`_is_playable`) | `pytest` (`test_extensions.py`) |
| Cross-platform data-dir discovery | `pytest` (`test_data_dirs.py`) with mocked `sys.platform` |
| Plugin loads inside Nicotine+, settings appear in UI | Manual smoke test |
| Live event delivery (`upload_finished_notification` actually fires) | Manual smoke test against a real Soulseek upload |
| External player behavior on M3U rewrite (relevant in `by-album` mode) | Manual — open in target player, observe behavior |

We deliberately don't try to integration-test against real Nicotine+ from CI. It would require a headless display, a real install, and a fake-event harness, all to validate the same things that are trivially observable with one manual toggle. Manual smoke is the right tool for the API-binding bugs; pytest is the right tool for the logic.

**What we explicitly skip:** type checking (overkill at this size), coverage metrics (vanity at this size), `tox`/`nox` (single Python version targeted), pre-commit hooks (solo project — running `ruff format` manually before commits is fine). All easy to add later if scale or contributors change the calculus.

## Plugin lifecycle

| Stage | What happens |
|---|---|
| `__init__` | Defines `settings`, `metasettings`, `commands`. Settings values are NOT loaded yet. |
| `init` | Resolves the playlist path, ensures the history DB exists (`CREATE TABLE IF NOT EXISTS`), and decides whether to backfill or regenerate based on which files already exist (see "Init cases" below). |
| `upload_finished_notification` | Fires on every successful upload. Records the event to the DB unconditionally; appends to the M3U only if the file extension is allowed and (when dedup is on) the file isn't already represented. |
| `disable` | Clears the stored playlist path. No long-lived file or DB handles to release. |

### Init cases

| DB | M3U | Behavior |
|---|---|---|
| missing | missing | Create DB, run `uploads.json` backfill into DB, regenerate M3U. (Fresh install.) |
| exists | exists | Use as-is. Don't touch the M3U — that's what `/playlist-reload` is for. |
| exists | missing | Regenerate M3U from DB. (Playlist deleted, history intact.) |
| missing | exists | Create empty DB. Don't back-parse the M3U — `#EXTINF` is lossy (no size, no structured timestamp). Pre-DB entries live only in the M3U; new events flow through both. |

## Settings

| Key | Type | Default | Purpose |
|---|---|---|---|
| `playlist_path` | string | `~/soulseek_uploads.m3u8` | Where to write the playlist. History DB is `<playlist_path>.history.db`. |
| `audio_extensions` | list string | `mp3, flac, m4a, aac, ogg, opus, wav, aiff, aif, wma, ape, wv` | Extensions to include in the M3U projection; everything else is recorded in the DB but never written to the M3U |
| `dedup` | bool | `false` | When on, the M3U lists each `real_path` at most once. DB still records every event. Run `/playlist-reload` after toggling. |

## Commands

- `/playlist-path` — Prints the current playlist file path
- `/playlist-backfill` — Re-imports Nicotine+'s `uploads.json(.old)` into the history DB (idempotent via `INSERT OR IGNORE`), then regenerates the M3U
- `/playlist-reload` — Regenerates the M3U from the history DB. Use after changing `dedup` or recovering a deleted playlist file.

## Key design decisions

### SQLite is the source of truth; M3U is a projection
Every upload event lands in `uploads` (a single SQLite table) regardless of extension. The M3U is regenerated from a single `SELECT` whenever projection rules change (`dedup` toggled, `/playlist-reload`, recovery from a deleted M3U). The live hot path keeps the M3U append-only — DB insert plus one `#EXTINF` pair — so chronological mode stays cheap. Full regenerations write to `<playlist_path>.tmp` and use `os.replace` so external players never observe a partial file.

We picked SQLite over a flat JSONL because the upcoming features (ordering, dedup, stats, per-user playlists) all map naturally to `ORDER BY`, `GROUP BY`, `UNIQUE` indexes, and indexed lookups. A flat file would force us to reimplement those by hand. `sqlite3` is stdlib so the runtime stays dependency-free.

### Schema and write-time dedup
```sql
CREATE TABLE uploads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT,         -- "YYYY-MM-DD HH:MM:SS", sortable as text; NULL for backfill rows where the file is gone
    user         TEXT NOT NULL,
    virtual_path TEXT NOT NULL,
    real_path    TEXT NOT NULL,
    size         INTEGER,
    source       TEXT NOT NULL -- 'live' | 'backfill'
);
CREATE UNIQUE INDEX idx_uploads_dedup ON uploads(user, virtual_path, real_path);
```
The `UNIQUE` index gives write-time dedup for free — backfill becomes idempotent via `INSERT OR IGNORE`, no in-memory `seen` set, no per-row check before insert. Backfill timestamps come from `os.stat(real_path).st_mtime`; if the file is gone we record `NULL` and sort those rows first ("history first, then new captures").

### Connection lifecycle: open-per-write
No long-lived `sqlite3.Connection` on `self` — every live event does `connect → INSERT OR IGNORE → commit → close` (hundreds of microseconds, negligible at upload frequency). Backfill wraps all inserts in a single transaction (~100× faster than per-row commit). WAL mode (`PRAGMA journal_mode=WAL`) so future stats queries don't block live inserts. Mirrors the same open-per-write rationale the M3U already uses.

### Dedup is a projection setting, not an event filter
With `dedup` on, the DB still records every event; only the M3U collapses. The live hook checks `SELECT 1 FROM uploads WHERE real_path = ?` before appending and skips the append on a hit. Toggling `dedup` is therefore a regen-only operation (`/playlist-reload`) — no data is lost when going from on to off. The M3U entry that survives a dedup collapse uses the **first** upload's metadata (`MIN(id)` per `real_path`), so once a track is in the playlist it stays in its original position rather than bubbling to the bottom on re-shares; external players see stable line ordering in chronological mode.

### Append mode, not overwrite
The playlist is opened with `"a"` and the `#EXTM3U` header is only written when the file is new or empty. This means the playlist persists across plugin reloads and Nicotine+ restarts. Earlier iterations used `"w"` (truncate), which wiped the log on every reload.

### Open-per-write, no long-lived file handle
We don't hold the playlist file open between writes. Each upload opens it in append mode, writes two lines, and closes. On Windows this matters because holding a file handle open can block other readers (e.g. a media player trying to load the playlist while Nicotine+ is running). The open/close overhead is negligible at upload frequency. An earlier iteration kept the handle open for the plugin's whole lifetime — it worked, but made the playlist effectively unreadable in external players until the plugin was disabled.

### Filter by file extension
Soulseek users download whole album folders — including cover art, logs, cue sheets, .nfo files, ZIPs, etc. An M3U should only list playable media, so both the live hook and the backfill gate writes through `_is_playable(path)`, which checks the extension against the configurable `audio_extensions` set.

### Backfill merges all history sources
`_find_uploads_sources()` returns *every* existing history file (not just the largest). `_write_backfill()` reads each, deduplicates rows on the `(user, virtual_path, real_dir)` tuple, then writes the merged set. This handles the case where `uploads.json` has current-session data and `uploads.json.old` has the previous session's — both can contribute.

### `.m3u8` extension for UTF-8 path encoding
The default playlist extension is `.m3u8`, not `.m3u`. Python always writes the file as UTF-8, but by informal convention `.m3u` is interpreted by players as the system's local codepage (cp1252 on Windows), while `.m3u8` is explicitly UTF-8. Paths containing non-ASCII characters (em dashes, middle dots, accented letters, etc.) round-trip correctly only under the `.m3u8` convention; under `.m3u` the player decodes UTF-8 bytes as cp1252 and looks for a file that doesn't exist on disk. We hit this in practice with a folder containing U+200E, U+00B7, and U+2014 — ASCII-only tracks in the same playlist played fine, non-ASCII ones silently failed.

### Cross-platform data-dir discovery
`_nicotine_data_dirs()` branches on `sys.platform` to return the standard Nicotine+ data locations:

| Platform | Location |
|---|---|
| Windows | `%APPDATA%\nicotine\` (read from env var, not hardcoded) |
| macOS | `~/Library/Application Support/nicotine/` |
| Linux (standard) | `$XDG_DATA_HOME/nicotine/`, defaulting to `~/.local/share/nicotine/` per XDG Base Directory spec |
| Linux (Flatpak) | `~/.var/app/org.nicotine_plus.Nicotine/data/nicotine/` |
| Linux (legacy) | `~/.nicotine/` for very old installs |

Nicotine+'s `uploads.json` is **data**, not config, so it lives under `XDG_DATA_HOME` (default `~/.local/share`) on Linux — not `~/.config`. The plugins directory itself (`~/.local/share/nicotine/plugins/`) confirms this.

We don't ask the running Nicotine+ for its own data path via `self.config`, even though that'd be more authoritative. The `self.config` API surface isn't documented in our reference, so we rely on platform conventions instead. If discovery breaks on someone's system, introspecting `self.config` is the fallback to investigate.

### Auto-backfill only when playlist is new
`init()` runs backfill automatically only when the playlist file is missing or zero-bytes. This makes first-time enable "just work" without cluttering reloads. Manual `/playlist-backfill` remains available for re-triggering.

## Lessons learned

### `uploads.json` is rolling state, not a log
This is the big one. Nicotine+ uses `uploads.json` as current-session state and `uploads.json.old` as a single-generation backup from the previous save. When Nicotine+ starts a new session, it rotates: the previous `uploads.json` becomes `.old`, overwriting whatever was there before, and the older `.old` is lost permanently.

**Consequence:** backfill only works against whatever's currently in those two files. If you install the plugin and don't backfill immediately, prior upload history is likely already gone. We confirmed this the hard way — inspected 434 finished uploads in `uploads.json.old` one session, then lost them on the next rotation before we could import them.

**Implication for future work:** we can't rely on `uploads.json` as a historical source. For persistent history, the plugin needs to own the store (its own JSON/SQLite file updated on every `upload_finished_notification`).

### `virtual_path` uses backslashes regardless of OS
Soulseek protocol paths always use `\` as separator. When constructing a real path from `uploads.json`, we split `virtual_path` on `\` to get the filename, then `os.path.join` it with `real_dir` (which is already a native Windows path on this setup). Don't use `os.path.basename` on a Soulseek virtual path on Linux — it won't split on backslashes.

### `real_path` vs `virtual_path` in the live hook
`upload_finished_notification` receives both. Always use `real_path` in the playlist — it's the actual local file path. `virtual_path` is the network-visible path and won't play anywhere.

### Plugin settings UI has no action button
Nicotine+'s plugin settings only support data widgets (bool, int, float, string, list, radio, dropdown). There's no way to add a clickable "Run Backfill" button in Preferences. Idiomatic plugins expose actions via chat commands (`/playlist-backfill`), which is what we do.

### WSL → Windows dev flow needs a copy step
Windows can't follow Linux symlinks, so editing in WSL requires an explicit sync to the Windows plugins dir. `install.sh` handles this. After each edit: run `./install.sh`, toggle the plugin in Preferences to reload.

### `str.split("\\")[-1]` over `os.path.basename` for cross-OS paths
When the filename separator is known to be backslash (e.g. Soulseek virtual paths), splitting manually is more reliable than `os.path.basename`, which is OS-dependent.
