# upload-playlist

A [Nicotine+](https://nicotine-plus.github.io/) plugin that writes a live M3U playlist of audio files other Soulseek users download from you. Every successful upload is appended in real time, so you can open the playlist in VLC/foobar2000/etc. to replay "what got shared."

## Repos

- **Primary (active development):** https://tangled.org/flankstaek.me/upload-playlist
- **Mirror (posterity):** https://github.com/flankstaek/upload-playlist

## Features

- Captures every successful upload via `upload_finished_notification`
- Configurable audio extension filter (skips cover art, logs, cue sheets, ZIPs, etc.)
- Owns its history in a small SQLite DB next to the playlist (`<playlist>.history.db`) — the M3U is a regeneratable projection
- Optional dedup mode collapses repeated uploads of the same file to a single playlist entry
- Playlist persists across Nicotine+ restarts (append mode for the hot path; atomic temp-file swap on full regenerations)
- External players can read the playlist while Nicotine+ is running (open-per-write, no long-lived file handle)
- One-time backfill from Nicotine+'s `uploads.json` on first install — auto-runs when playlist is new, or re-triggerable via `/playlist-backfill`

## Commands

- `/playlist-path` — print the current playlist file path
- `/playlist-backfill` — import historical uploads from Nicotine+'s `uploads.json` into the history DB and regenerate the playlist
- `/playlist-reload` — regenerate the playlist from the history DB (use after toggling settings like `dedup`)

## Settings

- `playlist_path` — where to write the playlist (default: `~/soulseek_uploads.m3u8`; `.m3u8` signals UTF-8 so non-ASCII paths resolve correctly). The history DB lives at `<playlist_path>.history.db`.
- `audio_extensions` — which file types to include (default: mp3, flac, m4a, aac, ogg, opus, wav, aiff, aif, wma, ape, wv)
- `dedup` — collapse repeated uploads of the same file into a single playlist entry (default: off). The DB still records every event. Run `/playlist-reload` after toggling.
- `ordering` — how to order playlist entries (default: `by-album-chronological`). Options: `by-album-chronological` (group tracks by folder; folders ordered by when the album first appeared), `chronological` (uploads in time order, no grouping), `by-album` (group by folder, folders sorted alphabetically). Run `/playlist-reload` after changing.

## Install

Nicotine+ loads plugins from a per-platform data directory. The plugin folder must be named `upload_playlist` (Nicotine+ uses the folder name as the internal plugin ID).

| Platform | Plugins directory |
|---|---|
| Windows | `%APPDATA%\nicotine\plugins\` |
| macOS | `~/Library/Application Support/nicotine/plugins/` |
| Linux | `~/.local/share/nicotine/plugins/` |

After installing, enable the plugin: Nicotine+ → Preferences → Plugins → "Upload Playlist".

### Option A — download a release (simplest)

1. Download `upload_playlist.zip` from the [latest release](https://github.com/flankstaek/upload-playlist/releases/latest)
2. Extract into your plugins directory (see table above)
3. Enable the plugin in Preferences

To update, download the new release and extract over the existing folder.

### Option B — clone directly into the plugins directory

For users who prefer git-based updates (`git pull` to update).

```
cd ~/.local/share/nicotine/plugins    # or the equivalent path from the table above
git clone https://tangled.org/flankstaek.me/upload-playlist upload_playlist
```

Note the rename: the repo is `upload-playlist` (dash) but the cloned folder must be `upload_playlist` (underscore).

### Option C — clone anywhere, sync with `install.sh`

Use this when your working copy can't live inside the plugins directory — most commonly when developing in WSL against a Windows-native Nicotine+, since Windows can't follow Linux symlinks. Also fine if you just prefer your source organized under a `~/dev/` root.

```
git clone https://tangled.org/flankstaek.me/upload-playlist
cd upload-playlist
./install.sh
```

`install.sh` auto-detects the destination:

- **Under WSL:** reads `%APPDATA%` from Windows via `cmd.exe` and `wslpath`, writes to `$APPDATA/nicotine/plugins/upload_playlist/`
- **Anywhere else:** set `NICOTINE_PLUGINS_DIR` to override

```
NICOTINE_PLUGINS_DIR=~/.local/share/nicotine/plugins ./install.sh
```

Re-run `install.sh` after each edit, then toggle the plugin off/on in Preferences to reload.

## Dev

Requires [`uv`](https://docs.astral.sh/uv/).

```
uv sync                    # install dev deps into .venv/
uv run pytest              # run tests
uv run ruff check          # lint
uv run ruff format         # format
```

Tests use a `pynicotine.pluginsystem.BasePlugin` shim in `tests/conftest.py` so `__init__.py` is importable outside Nicotine+. See [`docs/architecture.md`](docs/architecture.md) for what's covered by pytest vs. manual smoke testing.

### CI/CD

CI runs on both platforms:
- **Tangled** (primary): [Spindle](https://docs.tangled.org/spindles) workflow in `.tangled/workflows/ci.yml`
- **GitHub** (mirror): Actions workflow in `.github/workflows/ci.yml`

Both run `ruff check`, `ruff format --check`, and `pytest` on push/PR to main.

Releases are handled by GitHub Actions (`.github/workflows/release.yml`): when a CalVer tag (`v2026.05.26`) is pushed, CI runs as a gate, then `PLUGININFO` + `__init__.py` are packaged into `upload_playlist.zip` and attached to a GitHub Release.

### Releasing

```
./release.sh               # tags as v<today's date>, pushes to both remotes
./release.sh v2026.05.26.1 # explicit version for same-day follow-ups
```

The script updates `PLUGININFO` version, commits, tags, and pushes. If the tag already exists (e.g. a failed release), it deletes and retags at HEAD.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — how it works, design decisions, and hard-won lessons
- [`docs/roadmap.md`](docs/roadmap.md) — planned work, ordered by priority
- [`docs/nicotine-plugin-dev-reference.md`](docs/nicotine-plugin-dev-reference.md) — condensed reference for the Nicotine+ plugin API
