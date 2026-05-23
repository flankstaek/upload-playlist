# Roadmap

Iterative plan. Ordered roughly by priority and dependency — earlier items unblock later ones.

## Done: verify the live hook

Confirmed firing on real uploads — entries land in the M3U and play in external players.

## Done: dev tooling + test harness

**Why:** the SQLite work that follows is the first non-trivial logic change to the plugin. Up to now we've shipped on manual smoke tests (toggle plugin in Nicotine+, watch chat log). That worked when the whole plugin was ~30 lines of "open file, append two strings"; it scales badly once we have a DB schema, a regeneration path, ordering modes, and dedup. We want a fast feedback loop *before* we start writing that code, not after.

**Constraints shaping the choice:**
- Runtime stays stdlib-only — Nicotine+ ships its own Python and we can't install packages into it. All tooling is dev-only and never reaches end users.
- "Plugin folder *is* the repo" must hold — Nicotine+ uses the folder name as plugin ID, so we can't move `__init__.py` under a `src/` subdirectory.
- `pynicotine` isn't pip-installable (it's a desktop application, not a library). Tests that import the plugin must shim `pynicotine.pluginsystem.BasePlugin` before import.

**Stack:**
- **`uv`** for environment + dependency management (replaces `pip` + `venv` + `pyenv` + `pip-tools` etc.)
- **`pytest`** for tests (with `tmp_path` fixture for filesystem isolation)
- **`ruff`** for lint + format (replaces `flake8` + `black` + `isort`)
- **`pyproject.toml`** for all config (no `setup.py`, no `setup.cfg`)

Skipping for now: type checking (overkill at this size), coverage tools (vanity at this size), `tox`/`nox` (single Python version), pre-commit hooks (solo project, manual `ruff format` is fine).

**`BasePlugin` shim:** `tests/conftest.py` injects a fake `pynicotine.pluginsystem` module into `sys.modules` before plugin import. Fake `BasePlugin` is ~5 lines (no-op `__init__`, `log`, `output`). We're testing against our model of the API rather than the real one, but lifecycle bugs (e.g. accessing settings before `init()`) get caught by manual smoke-testing in Nicotine+ anyway, which is the right tool for that class of bug.

**What gets tested vs not:**

| Surface | Tested via |
|---|---|
| DB schema creation, idempotency | pytest |
| `_record_upload` dedup behavior under `INSERT OR IGNORE` | pytest |
| `_regenerate_m3u` output for each ordering mode | pytest |
| Backfill idempotency under repeat runs | pytest |
| `_is_playable` extension filtering | pytest |
| Cross-platform data-dir discovery (mock `sys.platform`) | pytest |
| Plugin loads inside Nicotine+, settings appear in UI | manual smoke test |
| `upload_finished_notification` actually fires on real upload | manual smoke test (already passing) |
| External player behavior on M3U rewrite (by-album mode) | manual, deferred to album-ordering work |

**Tasks:**
- [x] Add `pyproject.toml` with `[project]` (dev deps: pytest, ruff), `[tool.pytest.ini_options]`, `[tool.ruff]` sections
- [x] Add `.gitignore` entries for `.venv/`, `.ruff_cache/`, `.pytest_cache/`
- [x] Add `tests/conftest.py` with `BasePlugin` shim
- [x] Add `tests/test_smoke.py` — single test that imports the plugin and instantiates it, proving the shim works
- [x] Add `tests/test_extensions.py` — `_is_playable` cases for the existing audio-extension filter (low-stakes warm-up test)
- [x] Add `tests/test_data_dirs.py` — `_nicotine_data_dirs` cross-platform branches via mocked `sys.platform` and env vars
- [x] Document `uv sync` / `uv run pytest` / `uv run ruff check` in README dev section
- [x] Commit `uv.lock`

Once this lands the SQLite work below can land alongside its tests in the same PR, instead of as a one-shot manual-smoke-tested change.

## Done: own our history (SQLite store)

**Why:** `uploads.json(.old)` is rolling state, not a log. Nicotine+ overwrites it on rotation and historical data is lost. To support real dedup, stats, re-exports, or richer playlists, the plugin needs to own its own store.

**Backend:** SQLite (`sqlite3` is stdlib). Chosen over JSONL because the upcoming features (ordering, dedup, stats, per-user playlists) are all naturally SQL queries — `ORDER BY`, `GROUP BY`, `UNIQUE` indexes for write-time dedup, indexed lookups for stats. A flat file would force us to reimplement those by hand. At realistic scale (~180k rows over years for a heavy uploader, ~36 MB) bytes are not the constraint; ergonomics are.

**Storage location:** `<playlist_path>.history.db` — derived from existing `playlist_path` setting, no new setting needed. Moving the playlist moves the history.

**Schema (v1, as shipped):**
```sql
CREATE TABLE uploads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT,                 -- "YYYY-MM-DD HH:MM:SS"; NULL for backfill rows where file is gone
    user         TEXT NOT NULL,
    virtual_path TEXT NOT NULL,        -- backslash-separated, Soulseek-side
    real_path    TEXT NOT NULL,        -- local filesystem path
    size         INTEGER,              -- bytes; NULL if file gone at backfill time
    source       TEXT NOT NULL         -- 'live' | 'backfill'
);
CREATE INDEX idx_uploads_ts        ON uploads(ts);
CREATE INDEX idx_uploads_realpath  ON uploads(real_path);
CREATE UNIQUE INDEX idx_uploads_dedup
    ON uploads(user, virtual_path, real_path);
PRAGMA user_version = 1;
```

The `UNIQUE` index gives write-time dedup for free — re-running backfill becomes idempotent via `INSERT OR IGNORE`. No in-memory `seen` set.

**Connection lifecycle:** open-per-write (mirrors the existing M3U pattern). No long-lived connection on `self`. Per-event: `connect → INSERT OR IGNORE → commit → close` — ~hundreds of microseconds, negligible at upload frequency. Backfill wraps all inserts in a single transaction (~100x faster than per-row commit). WAL mode (`PRAGMA journal_mode=WAL`) so stats queries don't block live inserts.

**Architectural shift — M3U becomes a derived projection:**
- DB is source of truth (append-only via `INSERT OR IGNORE`).
- Live writes do *both*: insert to DB **and** append one entry-pair to the M3U — keeps the chronological hot path append-only.
- Mode-changing operations (ordering setting changed, dedup toggled, `/playlist-reload`) regenerate the entire M3U from a single `SELECT … ORDER BY …`.
- Regenerations use **temp-file + `os.replace`** for atomic swap so external players never see a partial M3U.

**Helpers (as shipped):**
- `_history_db_path` — property derived from `playlist_path` (`<playlist_path>.history.db`)
- `_db_connect()` — opens connection, sets WAL pragma; wrapped at call sites with `contextlib.closing`
- `_db_init()` — `CREATE TABLE IF NOT EXISTS …`, idempotent, called from `init()`
- `_record_upload(user, virtual_path, real_path, size, source, ts, conn)` — single `INSERT OR IGNORE` against a caller-owned connection; used by both live hook (with its own short-lived conn) and backfill (sharing one transaction)
- `_regenerate_m3u()` — writes to `<playlist_path>.tmp`, then `os.replace`. Used by mode changes and `/playlist-reload`.
- `_select_for_ordering(conn)` — reads `dedup` from settings and returns the appropriate SQL cursor (will grow an ordering branch when album mode lands)

**Init / migration cases (as shipped — see `docs/architecture.md#init-cases` for the canonical table):**

| Case | Behavior |
|---|---|
| DB missing, M3U missing | Create DB, run `uploads.json` backfill into DB, then `_regenerate_m3u()`. |
| DB exists, M3U exists | Use as-is. Don't touch M3U unless `/playlist-reload`. |
| DB exists, M3U missing | Regenerate M3U from DB (playlist deleted, history intact). |
| DB missing, M3U exists | Existing user upgrading. Create empty DB. **Don't** parse M3U back — `#EXTINF` is lossy (no size, no structured timestamp). Old entries live only in M3U; new ones flow through both. |
| DB schema older than code | `PRAGMA user_version` check + migration. Out of scope for v1, hook is in place. |

**Backfill timestamps:** `uploads.json` rows don't carry timestamps. Use `os.stat(real_path).st_mtime` if file exists; sentinel/NULL if not. NULLs sort first in chronological view → backfill entries appear at top of playlist (intuitive: history first, then new captures).

**Tasks:**
- [x] Add `_history_db_path` property and `_db_connect`/`_db_init` helpers
- [x] Wire `_db_init()` into `init()` lifecycle
- [x] Add `_record_upload()` and call from `upload_finished_notification` (in addition to existing M3U append)
- [x] Refactor `_write_backfill()` to write to DB inside one transaction, then call `_regenerate_m3u()` once at end
- [x] Implement `_regenerate_m3u()` with temp-file + `os.replace`
- [x] Add `/playlist-reload` command that calls `_regenerate_m3u()`

All subsequent features operate against the owned DB rather than Nicotine+'s rolling state.

## Done: dedup (shipped alongside SQLite store)

**Framing:** the playlist is mostly novelty — an honest log of what got shared. Dedup is opt-in noise reduction for when one album or track gets downloaded repeatedly and drowns out everything else. So it's a setting (`dedup: bool`, default `false`), not the default behavior, and not a one-off command (a command would drift the moment the next upload event arrives).

**Decisions:**
- **Dedup key: `real_path` alone.** "Unique tracks" is the natural meaning for a listening playlist. `(real_path, user)` would still show a track twice when two people grabbed it, which isn't really dedup from a listener standpoint.
- **Position: MIN(ts) / first occurrence.** Tracks stay in their original playlist position; re-shares don't bubble to the bottom. Matches the append-only feel of chronological mode and keeps external-player line indices stable.
- **`#EXTINF` display: first occurrence's metadata.** With MIN(id) selection, the surviving entry keeps the original `[uploaded to <first user> at <first ts>]`. No "shared 3x" formatting needed; no rewrite to entries already in the file.
- **DB still records every event** when dedup is on — only the M3U projection collapses. Toggling dedup off and reloading restores the full view.

**Implementation:** ~10 lines on top of the SQLite work — one setting, a `SELECT 1 WHERE real_path = ?` check in the live hook, and a `WHERE u.id = (SELECT MIN(id) ...)` branch in `_select_for_ordering`.

## Done: album ordering

**Why:** M3U entries land in upload chronological order by default; user wants the option to group tracks by album so the playlist plays as cohesive listens.

**Shipped:**
- New `ordering` dropdown setting, options `chronological` (default, preserves existing behavior) and `by-album`.
- `chronological` → `ORDER BY ts IS NULL DESC, ts ASC, id ASC` (NULL-ts backfill rows first).
- `by-album` → `ORDER BY real_path ASC, id ASC`. Because `real_path` includes the filename, one clause both groups by directory and sorts within by filename — works for properly-named rips with zero deps.
- Live hook branches on ordering: chronological still appends one `#EXTINF` pair (fast path); by-album calls `_regenerate_m3u()` (temp-file + `os.replace`) so new tracks land in the right folder group instead of at the end.
- Setting change → run `/playlist-reload`.

**Tradeoffs considered (decided against, documented in architecture.md):**

A *buffering / deferred-flush* approach (only flush a folder once we "knew" the album was complete) was rejected because: Soulseek has no "album complete" event so any heuristic has real failure modes (last album of session never flushes; concurrent downloads thrash; needs a `threading.Timer` lifecycle); late arrivals fragment albums regardless of buffering; full regen + `os.replace` solves the only real concern (truncated reads by external players) in one line of code.

**Manual smoke test against external player — done:** Windows Media Player kept playing the current track uninterrupted through a `/playlist-reload` regen with the M3U loaded. No audible disruption, no `os.replace` failure (WMP doesn't hold the file handle the way editors do — see the Bugs section above). Debounced-regen fallback not needed for WMP; reassess if a different target player misbehaves.

## Done: handle locked playlist file on Windows

**Symptom:** `PermissionError: [WinError 5] Access is denied: '<playlist>.tmp' -> '<playlist>'` raised from `os.replace`, reproduced with the Zed editor holding the M3U open while running `/playlist-backfill`. Same class of failure applies to the chronological-mode live append (`open(path, "a")`) when the file is similarly locked. Windows refuses operations that need `FILE_SHARE_DELETE` / `FILE_SHARE_WRITE` when another process has the file open without those modes. POSIX systems aren't affected — `rename` and `open("a")` succeed regardless of other holders.

**Considered and rejected:**
- *Retry with backoff:* helps only transient locks (AV scanners, indexers). The realistic trigger is an editor or player holding the handle for the duration of use — no backoff length helps there, and the log line lives somewhere most users wouldn't notice.
- *Truncate-and-rewrite fallback on `PermissionError`:* `open(path, "w")` also needs to truncate, which fails on Windows for the same reason whenever the holder opened with read-only sharing (typical for editors). The fallback would itself fail in the realistic case, while losing atomicity for any case where it didn't.

**Shipped:**
- `_regenerate_m3u()` returns `bool`. On `PermissionError` from `os.replace`, removes the `.tmp` file, logs an actionable message naming the playlist path and `/playlist-reload`, returns `False`.
- Live append in `upload_finished_notification` wraps `open("a")` in `try/except PermissionError`. The DB write that precedes the append already committed, so the upload is still recorded; the log message tells the user to close the program and run `/playlist-reload`.
- `cmd_backfill` and `cmd_reload` check the regen return and surface a distinct chat-output message on failure.
- By-album live regen: `upload_finished_notification` returns early on regen failure so the success log doesn't fire.

**Not addressed:** if the M3U is locked when `init()` runs (e.g. a player auto-loaded the playlist at OS startup), the regen on the "DB exists, M3U missing" branch — or the auto-backfill regen on a truly fresh install — logs and skips. Next user-triggered `/playlist-reload` recovers. We don't proactively poll for the lock to clear; the design assumption is that init is rare and users will notice the log.

## Done: chronological ordering with album grouping

**Why:** plain `by-album` sorts folders alphabetically by full path — a static catalog that throws away the recency signal that's the whole point of an upload log. Plain `chronological` preserves recency but scatters an album across whatever else was uploaded in between. The middle ground: chronological as the primary sort, but group all tracks from the same folder together so an album plays cohesively when you hit one of its tracks.

**Shipped:**
- New `by-album-chronological` option in the `ordering` dropdown, **promoted to default** (replaces `chronological` as default). Plain `by-album` and `chronological` remain as alternatives.
- Folders are ordered by `MIN(ts)` per `real_dir` — first appearance wins, so albums stay in place when someone re-downloads a track. Folders where *every* row has NULL ts (backfill-only, source file gone) sort first (matches chronological mode's backfill-first ordering); folders with a mix of NULL and timestamped rows use the non-NULL `MIN(ts)` and sort normally.
- `MIN(id)` is the tiebreaker on equal `MIN(ts)` (events landing in the same second still resolve by insert order — not alphabetical fallback to `real_path`).
- Within a folder: `ORDER BY real_path ASC, id ASC` — same as plain `by-album`.
- Schema bump to v2: added `real_dir TEXT` column with index, populated on insert from `os.path.dirname(real_path)`. Migration ALTERs the table and backfills `real_dir` for existing rows. Doing the dirname split in Python (on insert) sidesteps SQLite's lack of a stdlib `dirname` and the OS-dependent path separator.
- Live hook regenerates on every event in this mode (same as plain `by-album`), since a new album has to slot in by `MIN(ts)` and a new track for an existing album lands inside that group rather than at the end.

**Why `MIN(ts)` not `MAX(ts)`:** stable position. Once an album lands in the playlist it stays there even if someone re-downloads it months later. Matches existing dedup semantics (`MIN(id)` per `real_path` wins on dedup collapse — "first sight wins"). `MAX(ts)` would make albums bubble up on every re-download — useful as a "recent activity" view, but a different feature; reordering on every event is confusing in a log.

## Then: more commands

Candidates, in no particular order:
- `/playlist-clear` — empty the playlist and the underlying history DB (with confirmation prompt)
- `/playlist-stats` — counts by user, by file type, by album
- `/playlist-open` — launch the playlist in the default player (platform-dependent)

## Later: nice-to-haves

- **Per-user playlists.** Split into `uploads_by_<username>.m3u` files in addition to the master.
- **Duration in `#EXTINF`.** Currently `-1` (unknown). Parsing duration requires reading file headers — could use stdlib `wave`, `aifc` for limited formats, or punt.
- **Richer display names.** Parse metadata tags for `Artist - Title`. Needs stdlib-only parser (no mutagen, since we can't install packages into Nicotine+).
- **Playlist rotation.** Cap the M3U at N entries or bytes, archive older entries. Probably not needed at typical usage.
- **Multiple output formats.** Alongside `.m3u`, optionally write `.m3u8` (UTF-8 explicit) or `.pls`.

## Not doing

- **Parsing `.dbn` share databases** — binary format, fragile, no upside over our own log.
- **Watching `uploads.json` in real time** — the live hook already gives us the event cleanly; no reason to scrape state.
- **Third-party deps** (mutagen, etc.) — Nicotine+ can't install packages, stdlib only.
- **GUI settings beyond what Nicotine+ supports** — we get bool/int/float/string/list/radio/dropdown and chat commands. No custom widgets, no action buttons.
