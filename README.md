# upload-playlist

A [Nicotine+](https://nicotine-plus.github.io/) plugin that builds a live M3U
playlist of the audio files other Soulseek users download from you. Every
successful upload is added in real time, so you can open the playlist in
VLC / foobar2000 / etc. and replay "what got shared."

By default tracks are grouped by album folder, with albums ordered by when they
first appeared — so the playlist reads as a running history of cohesive listens.

## Install

Nicotine+ loads plugins from a per-platform data directory. **The plugin folder
must be named `upload_playlist`** — Nicotine+ uses the folder name as the
plugin's internal ID.

| Platform | Plugins directory |
|---|---|
| Windows | `%APPDATA%\nicotine\plugins\` |
| macOS | `~/Library/Application Support/nicotine/plugins/` |
| Linux | `~/.local/share/nicotine/plugins/` |

### Option A — download a release (simplest)

1. Download `upload_playlist.zip` from the [latest release](https://github.com/flankstaek/upload-playlist/releases/latest).
2. Extract it into your plugins directory (see table above). You should end up
   with a `upload_playlist/` folder containing `__init__.py` and `PLUGININFO`.
3. In Nicotine+: **Preferences → Plugins → enable "Upload Playlist"**.

To update later, download the new release and extract over the existing folder.

### Option B — clone into the plugins directory (git-based updates)

```
cd ~/.local/share/nicotine/plugins    # or the equivalent path from the table above
git clone https://tangled.org/flankstaek.me/upload-playlist upload_playlist
```

Note the rename: the repo is `upload-playlist` (dash) but the cloned folder must
be `upload_playlist` (underscore). `git pull` to update.

### Option C — clone anywhere, sync with `install.sh`

Use this when your working copy can't live inside the plugins directory — most
commonly developing in WSL against a Windows-native Nicotine+, since Windows
can't follow Linux symlinks.

```
git clone https://tangled.org/flankstaek.me/upload-playlist
cd upload-playlist
./install.sh
```

`install.sh` auto-detects the destination: under WSL it reads `%APPDATA%` from
Windows and writes to `$APPDATA/nicotine/plugins/upload_playlist/`. Anywhere
else, point it at your plugins dir explicitly:

```
NICOTINE_PLUGINS_DIR=~/.local/share/nicotine/plugins ./install.sh
```

Re-run `install.sh` after each edit, then toggle the plugin off/on in
Preferences to reload.

## Usage

Once enabled, the plugin works on its own — every audio file someone downloads
from you is added to the playlist automatically. On a fresh install it also does
a one-time import of your existing upload history from Nicotine+'s `uploads.json`.

Open the playlist file (see `playlist_path` below) in any player that reads M3U.

### Commands

Type these in any Nicotine+ chat:

- `/playlist-path` — print the current playlist file path
- `/playlist-reload` — rebuild the playlist from history (use after changing a setting)
- `/playlist-backfill` — re-import historical uploads from Nicotine+'s `uploads.json`, then rebuild

### Settings

Configure under **Preferences → Plugins → Upload Playlist**.

- **`playlist_path`** — where to write the playlist. Default:
  `~/soulseek_uploads.m3u8`. The `.m3u8` extension signals UTF-8 so non-ASCII
  paths resolve correctly in players. A small history database lives alongside
  it at `<playlist_path>.history.db`.
- **`audio_extensions`** — which file types to include (default: mp3, flac, m4a,
  aac, ogg, opus, wav, aiff, aif, wma, ape, wv). Non-audio files others grab
  (cover art, logs, cue sheets, ZIPs) are skipped.
- **`ordering`** — how entries are ordered. `by-album-chronological` (default)
  groups tracks by folder, with folders ordered by when the album first
  appeared; `chronological` lists uploads in plain time order; `by-album` groups
  by folder and sorts folders alphabetically. Run `/playlist-reload` after
  changing.
- **`dedup`** — collapse repeated uploads of the same file into a single
  playlist entry (default: off). History still records every upload; only the
  playlist collapses. Run `/playlist-reload` after toggling.

## How it works (in brief)

The plugin owns a small SQLite database next to the playlist and treats the M3U
as a regeneratable projection of it. New uploads are appended in real time;
changing an ordering/dedup setting or running `/playlist-reload` rebuilds the
whole playlist from the database via an atomic temp-file swap, so external
players never see a half-written file. See
[`docs/architecture.md`](docs/architecture.md) for the full design.

## Repos

- **Primary (active development):** https://tangled.org/flankstaek.me/upload-playlist
- **Mirror:** https://github.com/flankstaek/upload-playlist (also hosts releases)

## Contributing

The runtime is **stdlib-only** — Nicotine+ ships its own Python and can't
install packages, so the plugin imports nothing beyond the standard library. All
dev tooling is separate and never reaches end users.

Requires [`uv`](https://docs.astral.sh/uv/):

```
uv sync                    # install dev deps into .venv/
uv run pytest              # run tests
uv run ruff check          # lint
uv run ruff format         # format
```

Tests use a `pynicotine.pluginsystem.BasePlugin` shim in `tests/conftest.py` so
`__init__.py` can be imported outside Nicotine+. See
[`docs/architecture.md`](docs/architecture.md) for what's covered by pytest
versus manual smoke testing, and the constraints that shape the design.

CI runs `ruff check`, `ruff format --check`, and `pytest` on every push/PR to
`main`, on both [Tangled](https://docs.tangled.org/spindles) (Spindle,
`.tangled/workflows/ci.yml`) and GitHub Actions (`.github/workflows/ci.yml`).
Releases are cut by pushing a CalVer tag (`v2026.05.26`) — see
[`docs/architecture.md`](docs/architecture.md#cicd-and-release-pipeline) and
`release.sh`.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — how it works, design decisions, and hard-won lessons
- [`docs/nicotine-plugin-dev-reference.md`](docs/nicotine-plugin-dev-reference.md) — condensed reference for the Nicotine+ plugin API
</content>
</invoke>
