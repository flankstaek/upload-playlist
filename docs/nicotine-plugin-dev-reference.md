# Nicotine+ Plugin Development Reference
> Condensed guide for building a Nicotine+ plugin — focused on the upload playlist tracker use case.

---

## Table of Contents
1. [File Structure](#1-file-structure)
2. [Plugin Lifecycle](#2-plugin-lifecycle)
3. [Available Attributes](#3-available-attributes)
4. [Settings & UI Config](#4-settings--ui-config)
5. [Key Hooks & Notifications](#5-key-hooks--notifications)
6. [Utility Methods](#6-utility-methods)
7. [M3U Playlist Format](#7-m3u-playlist-format)
8. [Minimal Working Example (Upload Playlist)](#8-minimal-working-example-upload-playlist)
9. [Gotchas & Best Practices](#9-gotchas--best-practices)
10. [Reference Links](#10-reference-links)

---

## 1. File Structure

Every plugin lives in its own folder. The folder name is the internal plugin ID.

```
~/.local/share/nicotine/plugins/
└── upload_playlist/
    ├── PLUGININFO       # Metadata
    └── __init__.py      # Plugin code
```

### PLUGININFO
```ini
Version = "2024-01-01r00"
Authors = ["Your Name"]
Name = "Upload Playlist"
Description = "Generates a live M3U playlist of files others have downloaded from you."
```

### __init__.py (skeleton)
```python
from pynicotine.pluginsystem import BasePlugin

class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define settings structure here (values NOT available yet)
        self.settings = {}

    def init(self):
        # Settings ARE available here — do setup logic here
        pass

    def disable(self):
        # Clean up resources when plugin is disabled
        pass
```

**Install:** Go to Preferences → Plugins → click `+` → point to folder. No restart needed.

---

## 2. Plugin Lifecycle

```
__init__()          → Settings NOT available. Define settings dict + instance vars.
    ↓
init()              → Settings ARE available. Do setup, open files, init state.
    ↓
loaded_notification() → Plugin fully loaded, commands registered.
    ↓
[plugin runs, hooks fire]
    ↓
disable()           → Plugin unloading. Close files, cancel timers.
    ↓
unloaded_notification() → Final cleanup.
    ↓
shutdown_notification() → App is exiting.
```

---

## 3. Available Attributes

| Attribute | Type | Description |
|---|---|---|
| `self.internal_name` | str | Folder name (technical ID). Read-only. |
| `self.human_name` | str | Name from PLUGININFO. Read-only. |
| `self.path` | str | Absolute path to plugin folder. Read-only. |
| `self.core` | Core | Access to users, rooms, transfers, etc. |
| `self.config` | Config | Global Nicotine+ config. |
| `self.parent` | PluginHandler | Plugin system handler. |
| `self.settings` | dict | Your plugin's user-configurable settings. |
| `self.metasettings` | dict | Describes how settings appear in the UI. |
| `self.commands` | dict | Commands your plugin registers. |

---

## 4. Settings & UI Config

Define defaults in `__init__`, describe UI display in `metasettings`:

```python
self.settings = {
    "playlist_path": "~/uploads.m3u",
    "enabled": True,
}

self.metasettings = {
    "playlist_path": {
        "description": "Path to write the M3U playlist file",
        "type": "string"
    },
    "enabled": {
        "description": "Enable playlist tracking",
        "type": "bool"
    }
}
```

### Supported Setting Types
| Type | UI Widget |
|---|---|
| `"bool"` | Checkbox |
| `"integer"` | Integer spinner (supports `minimum`, `maximum`) |
| `"float"` | Float spinner (supports `minimum`, `maximum`, `stepsize`) |
| `"string"` | Text input |
| `"list string"` | List of strings |
| `"radio"` | Radio buttons — value is integer index; provide `options` tuple |
| `"dropdown"` | Dropdown — value is string; provide `options` tuple |

---

## 5. Key Hooks & Notifications

### Events vs Notifications
- **Events** (`_event` suffix): Can modify or block data. **Time-critical — keep fast or UI freezes.**
- **Notifications** (`_notification` suffix): Informational only. Can be slow. **Prefer these.**

### Transfer Notifications — what you need

```python
def upload_queued_notification(self, user, virtual_path, real_path):
    """Fires when a user queues a download from you."""
    pass

def upload_started_notification(self, user, virtual_path, real_path):
    """Fires when an upload to a user begins."""
    pass

def upload_finished_notification(self, user, virtual_path, real_path):
    """Fires when a user has successfully downloaded a file from you.
    
    Args:
        user (str):         The Soulseek username of the downloader.
        virtual_path (str): The path as seen on the network (e.g. '\\Music\\track.mp3').
        real_path (str):    The actual local path on disk — USE THIS for the playlist.
    """
    pass

def download_finished_notification(self, user, virtual_path, real_path):
    """Fires when YOU finish downloading from someone else."""
    pass
```

### Other Useful Notifications

```python
def server_connect_notification(self):
    """Connected to Soulseek server."""
    pass

def server_disconnect_notification(self, userchoice):
    """Disconnected. userchoice=True if user-initiated."""
    pass

def search_request_notification(self, searchterm, user, token):
    """Someone searched your shares."""
    pass
```

### Chat Notifications (for adding commands)

```python
def incoming_public_chat_notification(self, room, user, line):
    pass

def incoming_private_chat_notification(self, user, line):
    pass
```

### Return Codes (Events only)
```python
from pynicotine.pluginsystem import returncode

returncode["pass"]   # 2 — Pass to other plugins + Nicotine+ (default)
returncode["break"]  # 0 — Don't pass to other plugins, DO let Nicotine+ handle
returncode["zap"]    # 1 — Block entirely — don't pass anywhere
```

---

## 6. Utility Methods

### Logging
```python
self.log("Something happened")          # Appears in N+ console with plugin name prefix
```

### Commands (registered in __init__)
```python
self.commands = {
    "playlist-open": {
        "description": "Open the current upload playlist",
        "callback": self.cmd_open_playlist
    }
}

def cmd_open_playlist(self, args, **kwargs):
    self.output(f"Playlist at: {self.playlist_path}")
    return True
```

### Sending Messages
```python
self.send_public("room_name", "message")          # To a chat room
self.send_private("username", "message")          # Private message
self.output("text")                               # To wherever command was run
self.echo_message("text", message_type="local")   # Local display only, not sent
```

---

## 7. M3U Playlist Format

Standard extended M3U — supported by VLC, Winamp, foobar2000, and most players. Plain text, no libraries needed.

```
#EXTM3U

#EXTINF:-1,Artist - Track Title
/absolute/path/to/file.mp3

#EXTINF:-1,Another Track
/absolute/path/to/other.flac
```

- First line: `#EXTM3U` header (write once on init)
- Per track: `#EXTINF:<duration>,<display name>` then the file path on the next line
- Duration of `-1` means unknown — fine for this use case
- Use `os.path.basename(real_path)` to extract a display name from the path

---

## 8. Minimal Working Example (Upload Playlist)

```python
import os
from datetime import datetime
from pynicotine.pluginsystem import BasePlugin

class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {
            "playlist_path": os.path.join(os.path.expanduser("~"), "soulseek_uploads.m3u")
        }
        self.metasettings = {
            "playlist_path": {
                "description": "Path to save the M3U playlist file",
                "type": "string"
            }
        }

        self.commands = {
            "playlist-path": {
                "description": "Show the current playlist file path",
                "callback": self.cmd_show_path
            }
        }

        self._playlist_file = None

    def init(self):
        path = self.settings["playlist_path"]
        self._playlist_file = open(path, "w", encoding="utf-8")
        self._playlist_file.write("#EXTM3U\n")
        self._playlist_file.flush()
        self.log(f"Upload playlist started at: {path}")

    def upload_finished_notification(self, user, virtual_path, real_path):
        if not self._playlist_file:
            return

        display_name = os.path.basename(real_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._playlist_file.write(f"#EXTINF:-1,{display_name} [uploaded to {user} at {timestamp}]\n")
        self._playlist_file.write(f"{real_path}\n")
        self._playlist_file.flush()  # Write immediately so playlist is always valid

        self.log(f"Added to playlist: {display_name} (downloaded by {user})")

    def disable(self):
        if self._playlist_file:
            self._playlist_file.close()
            self._playlist_file = None
            self.log("Upload playlist closed.")

    def cmd_show_path(self, args, **kwargs):
        self.output(f"Playlist file: {self.settings['playlist_path']}")
        return True
```

---

## 9. Gotchas & Best Practices

| # | Gotcha / Practice | Detail |
|---|---|---|
| 1 | **No historical data** | No uploads before the plugin was enabled are tracked. This is by design. |
| 2 | **Keep _event handlers fast** | Slow event handlers freeze the UI. Use `_notification` hooks for anything non-trivial. |
| 3 | **Single file preferred** | Can't easily import relative modules without path injection hacks. Keep everything in `__init__.py`. |
| 4 | **Flush after every write** | Call `file.flush()` after each entry so the M3U is always in a valid, playable state mid-session. |
| 5 | **Always close in `disable()`** | Don't rely on garbage collection — close file handles explicitly in `disable()`. |
| 6 | **Use `real_path` not `virtual_path`** | `virtual_path` is the network-visible path; `real_path` is the actual local path needed for the playlist. |
| 7 | **Settings in `__init__`, logic in `init()`** | Settings dict must be defined in `__init__()` but values aren't loaded until `init()` is called. |
| 8 | **No restart needed** | You can install/update plugins without restarting Nicotine+. |
| 9 | **Python stdlib only** | You can't install third-party packages into Nicotine+ itself. Stick to stdlib (`os`, `datetime`, etc.). |

---

## 10. Reference Links

| Resource | URL |
|---|---|
| Plugin Getting Started Guide | https://www.mintlify.com/nicotine-plus/nicotine-plus/development/plugins/getting-started |
| Plugin API Reference (all hooks) | https://www.mintlify.com/nicotine-plus/nicotine-plus/development/plugins/api-reference |
| Plugin Examples | https://www.mintlify.com/nicotine-plus/nicotine-plus/development/plugins/examples |
| `pluginsystem.py` source (ground truth) | https://github.com/nicotine-plus/nicotine-plus/blob/master/pynicotine/pluginsystem.py |
| `more-upload-stats` plugin (best reference) | https://github.com/Nachtalb/more-upload-stats |
| Leech Detector (upload hook example) | https://github.com/nicotine-plus/nicotine-plus/blob/master/pynicotine/plugins/leech_detector/__init__.py |
| Plugin template (dev workflow tools) | https://github.com/Nachtalb/nicotine_plus_plugin_template |
| Nicotine+ GitHub | https://github.com/nicotine-plus/nicotine-plus |
