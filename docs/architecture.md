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

## Plugin lifecycle

| Stage | What happens |
|---|---|
| `__init__` | Defines `settings`, `metasettings`, `commands`. Settings values are NOT loaded yet. |
| `init` | Resolves the playlist path. If file is brand-new or empty, opens it once to write `#EXTM3U` header + run auto-backfill, then closes. |
| `upload_finished_notification` | Fires on every successful upload. If file extension is allowed, opens the playlist in append mode, writes the entry, closes. |
| `disable` | Clears the stored playlist path. No file handle to release. |

## Settings

| Key | Type | Default | Purpose |
|---|---|---|---|
| `playlist_path` | string | `~/soulseek_uploads.m3u8` | Where to write the playlist |
| `audio_extensions` | list string | `mp3, flac, m4a, aac, ogg, opus, wav, aiff, aif, wma, ape, wv` | Extensions to include; everything else is filtered out |

## Commands

- `/playlist-path` — Prints the current playlist file path
- `/playlist-backfill` — Re-runs backfill from Nicotine+'s `uploads.json(.old)` into the current playlist

## Key design decisions

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
