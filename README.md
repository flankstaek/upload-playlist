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

- `playlist_path` — where to write the playlist (default: `~/soulseek_uploads.m3u8`; `.m3u8` signals UTF-8 so non-ASCII paths resolve correctly)
- `audio_extensions` — which file types to include (default: mp3, flac, m4a, aac, ogg, opus, wav, aiff, aif, wma, ape, wv)

## Install

Nicotine+ loads plugins from a per-platform data directory. Whichever approach you use below, the plugin folder must be named `upload_playlist` (Nicotine+ uses the folder name as the internal plugin ID).

| Platform | Plugins directory |
|---|---|
| Windows | `%APPDATA%\nicotine\plugins\` |
| macOS | `~/Library/Application Support/nicotine/plugins/` |
| Linux | `~/.local/share/nicotine/plugins/` |

After installing, enable the plugin: Nicotine+ → Preferences → Plugins → "Upload Playlist".

### Option A — clone directly into the plugins directory (simplest)

Recommended if your working copy and Nicotine+ are on the same filesystem (native Linux, macOS, or Windows). Edits apply with just a plugin toggle in Preferences — no copy step.

```
cd ~/.local/share/nicotine/plugins    # or the equivalent path from the table above
git clone https://tangled.org/flankstaek.me/upload-playlist upload_playlist
```

Note the rename: the repo is `upload-playlist` (dash) but the cloned folder must be `upload_playlist` (underscore).

### Option B — clone anywhere, sync with `install.sh`

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

## Docs

- [`docs/architecture.md`](docs/architecture.md) — how it works, design decisions, and hard-won lessons
- [`docs/roadmap.md`](docs/roadmap.md) — planned work, ordered by priority
- [`docs/nicotine-plugin-dev-reference.md`](docs/nicotine-plugin-dev-reference.md) — condensed reference for the Nicotine+ plugin API
