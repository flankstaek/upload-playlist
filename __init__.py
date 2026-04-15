import json
import os
import sys
from datetime import datetime

from pynicotine.pluginsystem import BasePlugin


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {
            "playlist_path": os.path.join(os.path.expanduser("~"), "soulseek_uploads.m3u8"),
            "audio_extensions": [
                "mp3", "flac", "m4a", "aac", "ogg", "opus",
                "wav", "aiff", "aif", "wma", "ape", "wv",
            ],
        }
        self.metasettings = {
            "playlist_path": {
                "description": "Path to save the M3U playlist file",
                "type": "string",
            },
            "audio_extensions": {
                "description": "File extensions (without dot) to include in the playlist",
                "type": "list string",
            },
        }

        self.commands = {
            "playlist-path": {
                "description": "Show the current playlist file path",
                "callback": self.cmd_show_path,
            },
            "playlist-backfill": {
                "description": "Import historical uploads from Nicotine+'s uploads.json",
                "callback": self.cmd_backfill,
            },
        }

        self._playlist_path = None

    def init(self):
        self._playlist_path = os.path.expanduser(self.settings["playlist_path"])
        is_new = (
            not os.path.exists(self._playlist_path)
            or os.path.getsize(self._playlist_path) == 0
        )

        if is_new:
            with open(self._playlist_path, "a", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                count = self._write_backfill(f)
            if count:
                self.log(f"Auto-backfill imported {count} historical uploads.")

        self.log(f"Upload playlist ready at: {self._playlist_path}")

    def upload_finished_notification(self, user, virtual_path, real_path):
        if not self._playlist_path:
            return
        if not self._is_playable(real_path):
            return

        display_name = os.path.basename(real_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(self._playlist_path, "a", encoding="utf-8") as f:
            f.write(f"#EXTINF:-1,{display_name} [uploaded to {user} at {timestamp}]\n")
            f.write(f"{real_path}\n")

        self.log(f"Added to playlist: {display_name} (downloaded by {user})")

    def disable(self):
        self._playlist_path = None

    def cmd_show_path(self, args, **kwargs):
        self.output(f"Playlist file: {self._playlist_path}")
        return True

    def cmd_backfill(self, args, **kwargs):
        if not self._playlist_path:
            return True
        with open(self._playlist_path, "a", encoding="utf-8") as f:
            count = self._write_backfill(f)
        self.output(f"Backfill imported {count} historical uploads.")
        return True

    def _write_backfill(self, file):
        sources = self._find_uploads_sources()
        if not sources:
            self.log("Backfill: no uploads history file found.")
            return 0

        seen = set()
        merged = []
        for source in sources:
            try:
                with open(source, "r", encoding="utf-8") as f:
                    rows = json.load(f)
            except (OSError, ValueError) as e:
                self.log(f"Backfill: failed to read {source}: {e}")
                continue
            for row in rows:
                if len(row) < 4 or row[3] != "Finished":
                    continue
                key = (row[0], row[1], row[2])
                if key in seen:
                    continue
                seen.add(key)
                merged.append(row)

        count = 0
        for row in merged:
            user, virtual_path, real_dir = row[0], row[1], row[2]
            filename = virtual_path.replace("/", "\\").split("\\")[-1]
            if not self._is_playable(filename):
                continue
            real_path = os.path.join(real_dir, filename)

            file.write(f"#EXTINF:-1,{filename} [uploaded to {user}] [backfilled]\n")
            file.write(f"{real_path}\n")
            count += 1

        self.log(f"Backfill: imported {count} entries from {len(sources)} source file(s)")
        return count

    def _is_playable(self, path):
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if not ext:
            return False
        allowed = {e.strip().lstrip(".").lower() for e in self.settings["audio_extensions"]}
        return ext in allowed

    def _find_uploads_sources(self):
        sources = []
        for data_dir in self._nicotine_data_dirs():
            for name in ("uploads.json", "uploads.json.old"):
                path = os.path.join(data_dir, name)
                if os.path.exists(path) and os.path.getsize(path) > 2:
                    sources.append(path)
        return sources

    def _nicotine_data_dirs(self):
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            return [os.path.join(appdata, "nicotine")] if appdata else []

        if sys.platform == "darwin":
            return [os.path.expanduser("~/Library/Application Support/nicotine")]

        xdg_data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        return [
            os.path.join(xdg_data_home, "nicotine"),
            os.path.expanduser("~/.var/app/org.nicotine_plus.Nicotine/data/nicotine"),
            os.path.expanduser("~/.nicotine"),
        ]
