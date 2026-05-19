import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime

from pynicotine.pluginsystem import BasePlugin


class Plugin(BasePlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {
            "playlist_path": os.path.join(os.path.expanduser("~"), "soulseek_uploads.m3u8"),
            "audio_extensions": [
                "mp3",
                "flac",
                "m4a",
                "aac",
                "ogg",
                "opus",
                "wav",
                "aiff",
                "aif",
                "wma",
                "ape",
                "wv",
            ],
            "dedup": False,
            "ordering": "chronological",
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
            "dedup": {
                "description": (
                    "Collapse repeated uploads of the same file into a single playlist entry. "
                    "Run /playlist-reload after toggling."
                ),
                "type": "bool",
            },
            "ordering": {
                "description": (
                    "How to order playlist entries. 'chronological' lists uploads in time order; "
                    "'by-album' groups tracks by folder. In by-album mode the playlist is "
                    "rewritten on every upload."
                ),
                "type": "dropdown",
                "options": ("chronological", "by-album"),
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
            "playlist-reload": {
                "description": "Regenerate the playlist from the history database",
                "callback": self.cmd_reload,
            },
        }

        self._playlist_path = None

    @property
    def _history_db_path(self):
        if not self._playlist_path:
            return None
        return self._playlist_path + ".history.db"

    def init(self):
        self._playlist_path = os.path.expanduser(self.settings["playlist_path"])
        db_existed = os.path.exists(self._history_db_path)
        m3u_existed = (
            os.path.exists(self._playlist_path) and os.path.getsize(self._playlist_path) > 0
        )

        self._db_init()

        if not db_existed and not m3u_existed:
            count = self._import_uploads_json()
            self._regenerate_m3u()
            if count:
                self.log(f"Auto-backfill imported {count} historical uploads.")
        elif db_existed and not m3u_existed:
            self._regenerate_m3u()
            self.log("Regenerated playlist from history database.")

        self.log(f"Upload playlist ready at: {self._playlist_path}")

    def upload_finished_notification(self, user, virtual_path, real_path):
        if not self._playlist_path:
            return

        size = None
        try:
            size = os.path.getsize(real_path)
        except OSError:
            pass

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        playable = self._is_playable(real_path)
        dedup_on = bool(self.settings.get("dedup"))

        already_present = False
        with closing(self._db_connect()) as conn:
            if playable and dedup_on:
                cur = conn.execute(
                    "SELECT 1 FROM uploads WHERE real_path = ? LIMIT 1", (real_path,)
                )
                already_present = cur.fetchone() is not None
            self._record_upload(user, virtual_path, real_path, size, "live", ts, conn)
            conn.commit()

        if not playable or already_present:
            return

        display_name = os.path.basename(real_path)
        if self.settings.get("ordering") == "by-album":
            self._regenerate_m3u()
        else:
            with open(self._playlist_path, "a", encoding="utf-8") as f:
                f.write(f"#EXTINF:-1,{display_name} [uploaded to {user} at {ts}]\n")
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
        count = self._import_uploads_json()
        self._regenerate_m3u()
        self.output(f"Backfill imported {count} new entries to history; playlist regenerated.")
        return True

    def cmd_reload(self, args, **kwargs):
        if not self._playlist_path:
            return True
        self._regenerate_m3u()
        self.output("Playlist regenerated from history.")
        return True

    def _db_connect(self):
        conn = sqlite3.connect(self._history_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _db_init(self):
        with closing(self._db_connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts           TEXT,
                    user         TEXT NOT NULL,
                    virtual_path TEXT NOT NULL,
                    real_path    TEXT NOT NULL,
                    size         INTEGER,
                    source       TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_uploads_ts ON uploads(ts);
                CREATE INDEX IF NOT EXISTS idx_uploads_realpath ON uploads(real_path);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_uploads_dedup
                    ON uploads(user, virtual_path, real_path);
                PRAGMA user_version = 1;
                """
            )
            conn.commit()

    def _record_upload(self, user, virtual_path, real_path, size, source, ts, conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO uploads (ts, user, virtual_path, real_path, size, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, user, virtual_path, real_path, size, source),
        )
        return cur.rowcount

    def _select_for_ordering(self, conn):
        by_album = self.settings.get("ordering") == "by-album"
        if by_album:
            order_by = "ORDER BY real_path ASC, id ASC"
        else:
            order_by = "ORDER BY ts IS NULL DESC, ts ASC, id ASC"

        if self.settings.get("dedup"):
            return conn.execute(
                f"""
                SELECT ts, user, real_path
                FROM uploads u
                WHERE id = (
                    SELECT MIN(id) FROM uploads WHERE real_path = u.real_path
                )
                {order_by}
                """
            )
        return conn.execute(
            f"""
            SELECT ts, user, real_path
            FROM uploads
            {order_by}
            """
        )

    def _regenerate_m3u(self):
        tmp_path = self._playlist_path + ".tmp"
        with closing(self._db_connect()) as conn, open(tmp_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ts, user, real_path in self._select_for_ordering(conn):
                if not self._is_playable(real_path):
                    continue
                display_name = os.path.basename(real_path)
                suffix = f"[uploaded to {user} at {ts}]" if ts else f"[uploaded to {user}]"
                f.write(f"#EXTINF:-1,{display_name} {suffix}\n")
                f.write(f"{real_path}\n")
        os.replace(tmp_path, self._playlist_path)

    def _import_uploads_json(self):
        sources = self._find_uploads_sources()
        if not sources:
            self.log("Backfill: no uploads history file found.")
            return 0

        deduped_rows = {}
        for source in sources:
            try:
                with open(source, encoding="utf-8") as f:
                    rows = json.load(f)
            except (OSError, ValueError) as e:
                self.log(f"Backfill: failed to read {source}: {e}")
                continue
            for row in rows:
                if len(row) < 4 or row[3] != "Finished":
                    continue
                user, virtual_path, real_dir = row[0], row[1], row[2]
                deduped_rows.setdefault((user, virtual_path, real_dir), None)

        if not deduped_rows:
            return 0

        inserted = 0
        with closing(self._db_connect()) as conn:
            for user, virtual_path, real_dir in deduped_rows:
                filename = virtual_path.replace("/", "\\").split("\\")[-1]
                real_path = os.path.join(real_dir, filename)
                try:
                    st = os.stat(real_path)
                    ts = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    size = st.st_size
                except OSError:
                    ts = None
                    size = None
                inserted += self._record_upload(
                    user, virtual_path, real_path, size, "backfill", ts, conn
                )
            conn.commit()

        self.log(f"Backfill: imported {inserted} new entries from {len(sources)} source file(s)")
        return inserted

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
