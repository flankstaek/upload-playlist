import json
import os
import sqlite3

import pytest
from upload_playlist import Plugin


@pytest.fixture
def make_plugin(tmp_path, monkeypatch):
    """Builds a Plugin pointed at tmp_path with an isolated (empty) Nicotine+ data dir."""

    def _make(uploads_rows=None):
        p = Plugin()
        p.settings["playlist_path"] = str(tmp_path / "playlist.m3u8")

        nicotine_dir = tmp_path / "nicotine"
        nicotine_dir.mkdir(exist_ok=True)
        if uploads_rows is not None:
            (nicotine_dir / "uploads.json").write_text(json.dumps(uploads_rows), encoding="utf-8")
        monkeypatch.setattr(p, "_nicotine_data_dirs", lambda: [str(nicotine_dir)])
        return p

    return _make


def test_init_fresh_creates_db_and_m3u(make_plugin, tmp_path):
    p = make_plugin()
    p.init()
    assert os.path.exists(p._history_db_path)
    assert os.path.exists(p._playlist_path)
    with open(p._playlist_path, encoding="utf-8") as f:
        assert f.read().startswith("#EXTM3U\n")


def test_init_fresh_with_uploads_json_backfills(make_plugin, tmp_path):
    p = make_plugin(
        uploads_rows=[
            ["alice", "music\\a.mp3", str(tmp_path), "Finished"],
            ["bob", "music\\b.flac", str(tmp_path), "Finished"],
        ]
    )
    p.init()
    with open(p._playlist_path, encoding="utf-8") as f:
        content = f.read()
    assert "a.mp3" in content
    assert "b.flac" in content


def test_init_db_exists_does_not_regen(make_plugin, tmp_path):
    p = make_plugin()
    p.init()  # creates DB + empty M3U

    # Hand-write a custom M3U to detect untouched-ness
    with open(p._playlist_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n#CUSTOM\nshould-survive\n")

    p2 = make_plugin()
    p2.init()  # DB exists, M3U exists → no-op

    with open(p2._playlist_path, encoding="utf-8") as f:
        assert "#CUSTOM" in f.read()


def test_init_db_missing_m3u_exists_preserves_m3u(make_plugin, tmp_path):
    """Existing user upgrading: pre-DB M3U content must not be back-parsed or lost."""
    playlist = tmp_path / "playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXTINF:-1,old.mp3 [uploaded to alice at 2025-01-01 00:00:00]\n/x/old.mp3\n",
        encoding="utf-8",
    )

    p = make_plugin()
    p.init()

    assert os.path.exists(p._history_db_path)
    with open(p._playlist_path, encoding="utf-8") as f:
        content = f.read()
    assert "old.mp3" in content  # original M3U untouched


def test_init_db_exists_m3u_missing_regenerates(make_plugin, tmp_path):
    p = make_plugin()
    p.init()  # creates DB + empty M3U

    # Insert one row, then delete M3U
    conn = p._db_connect()
    try:
        p._record_upload("alice", "v\\a.mp3", "/x/a.mp3", 1000, "live", "2026-05-17 10:00:00", conn)
        conn.commit()
    finally:
        conn.close()
    os.remove(p._playlist_path)

    p2 = make_plugin()
    p2.init()  # DB exists, M3U missing → regen

    with open(p2._playlist_path, encoding="utf-8") as f:
        assert "a.mp3" in f.read()


def test_upload_finished_appends_to_m3u_and_db(make_plugin, tmp_path):
    p = make_plugin()
    p.init()

    real_path = str(tmp_path / "track.mp3")
    p.upload_finished_notification("alice", "music\\track.mp3", real_path)

    with open(p._playlist_path, encoding="utf-8") as f:
        assert "track.mp3" in f.read()

    conn = sqlite3.connect(p._history_db_path)
    try:
        row = conn.execute("SELECT user, real_path, source FROM uploads").fetchone()
    finally:
        conn.close()
    assert row == ("alice", real_path, "live")


def test_upload_finished_non_playable_recorded_but_not_in_m3u(make_plugin, tmp_path):
    p = make_plugin()
    p.init()

    p.upload_finished_notification("alice", "music\\cover.jpg", str(tmp_path / "cover.jpg"))

    with open(p._playlist_path, encoding="utf-8") as f:
        assert "cover.jpg" not in f.read()

    conn = sqlite3.connect(p._history_db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_upload_finished_dedup_off_appends_twice(make_plugin, tmp_path):
    p = make_plugin()
    p.init()
    real_path = str(tmp_path / "track.mp3")
    # Different users so the DB UNIQUE constraint doesn't ignore the second insert.
    p.upload_finished_notification("alice", "v1\\track.mp3", real_path)
    p.upload_finished_notification("bob", "v2\\track.mp3", real_path)

    with open(p._playlist_path, encoding="utf-8") as f:
        assert f.read().count(real_path) == 2


def test_upload_finished_dedup_on_skips_second_append(make_plugin, tmp_path):
    p = make_plugin()
    p.settings["dedup"] = True
    p.init()
    real_path = str(tmp_path / "track.mp3")
    p.upload_finished_notification("alice", "v1\\track.mp3", real_path)
    p.upload_finished_notification("bob", "v2\\track.mp3", real_path)

    with open(p._playlist_path, encoding="utf-8") as f:
        assert f.read().count(real_path) == 1

    conn = sqlite3.connect(p._history_db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    finally:
        conn.close()
    assert count == 2  # both events still recorded in DB


def test_upload_finished_by_album_regenerates_and_groups(make_plugin, tmp_path):
    p = make_plugin()
    p.settings["ordering"] = "by-album"
    p.init()

    album_a = tmp_path / "AlbumA"
    album_b = tmp_path / "AlbumB"
    album_a.mkdir()
    album_b.mkdir()

    # Upload out of album order; the M3U should group by folder after each event.
    p.upload_finished_notification("alice", "v\\b1.mp3", str(album_b / "01.mp3"))
    p.upload_finished_notification("alice", "v\\a1.mp3", str(album_a / "01.mp3"))
    p.upload_finished_notification("alice", "v\\b2.mp3", str(album_b / "02.mp3"))
    p.upload_finished_notification("alice", "v\\a2.mp3", str(album_a / "02.mp3"))

    with open(p._playlist_path, encoding="utf-8") as f:
        content = f.read()
    order = [
        content.index(str(path))
        for path in (
            album_a / "01.mp3",
            album_a / "02.mp3",
            album_b / "01.mp3",
            album_b / "02.mp3",
        )
    ]
    assert order == sorted(order)


def test_cmd_reload_regenerates_from_db(make_plugin, tmp_path):
    p = make_plugin()
    p.init()

    conn = p._db_connect()
    try:
        p._record_upload(
            "alice", "v\\a.mp3", str(tmp_path / "a.mp3"), 1000, "live", "2026-05-17 10:00:00", conn
        )
        conn.commit()
    finally:
        conn.close()

    # Truncate the M3U so we can prove regen rewrote it.
    open(p._playlist_path, "w", encoding="utf-8").close()
    p.cmd_reload(args="")

    with open(p._playlist_path, encoding="utf-8") as f:
        content = f.read()
    assert content.startswith("#EXTM3U\n")
    assert "a.mp3" in content
