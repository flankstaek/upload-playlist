# upload-playlist

A [Nicotine+](https://nicotine-plus.github.io/) plugin that writes a live M3U playlist of audio files other Soulseek users download from you. Every successful upload is appended in real time, so you can open the playlist in VLC/foobar2000/etc. to replay "what got shared."

## Repos

- **Primary (active development):** https://tangled.org/flankstaek.me/upload-playlist
- **Mirror (posterity):** https://github.com/flankstaek/upload-playlist

## Features

- Captures every successful upload via `upload_finished_notification`
- Configurable audio extension filter (skips cover art, logs, cue sheets, ZIPs, etc.)
- Playlist persists across Nicotine+ restarts (append mode)
- External players can read the playlist while Nicotine+ is running (open-per-write, no long-lived file handle)
- One-time backfill from Nicotine+'s `uploads.json` on first install — auto-runs when playlist is new, or re-triggerable via `/playlist-backfill`

## Commands

- `/playlist-path` — print the current playlist file path
- `/playlist-backfill` — import historical uploads from Nicotine+'s `uploads.json`

## Settings

- `playlist_path` — where to write the `.m3u` (default: `~/soulseek_uploads.m3u`)
- `audio_extensions` — which file types to include (default: mp3, flac, m4a, aac, ogg, opus, wav, aiff, aif, wma, ape, wv)

## Install

### Native (Linux / macOS / Windows)

Copy `PLUGININFO` and `__init__.py` into a folder named `upload_playlist/` inside your Nicotine+ plugins directory:

| Platform | Plugins directory |
|---|---|
| Windows | `%APPDATA%\nicotine\plugins\upload_playlist\` |
| macOS | `~/Library/Application Support/nicotine/plugins/upload_playlist/` |
| Linux | `~/.local/share/nicotine/plugins/upload_playlist/` |

Then: Nicotine+ → Preferences → Plugins → enable "Upload Playlist".

### WSL → Windows (the primary dev flow)

`./install.sh` auto-detects `%APPDATA%` via `cmd.exe` + `wslpath` and copies the plugin files across. After editing, re-run `install.sh` and toggle the plugin off/on in Preferences to reload.

For a non-WSL install, override the destination:

```
NICOTINE_PLUGINS_DIR=~/.local/share/nicotine/plugins ./install.sh
```

## Docs

- [`docs/architecture.md`](docs/architecture.md) — how it works, design decisions, and hard-won lessons
- [`docs/roadmap.md`](docs/roadmap.md) — planned work, ordered by priority
- [`docs/nicotine-plugin-dev-reference.md`](docs/nicotine-plugin-dev-reference.md) — condensed reference for the Nicotine+ plugin API
