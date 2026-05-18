import json
import sqlite3

import pytest
from upload_playlist import Plugin


@pytest.fixture
def plugin(tmp_path):
    p = Plugin()
    p.settings["playlist_path"] = str(tmp_path / "playlist.m3u8")
    p._playlist_path = p.settings["playlist_path"]
    p._db_init()
    return p


def _insert(plugin, user, vpath, rpath, ts="2026-05-17 12:00:00", size=1000, source="live"):
    conn = plugin._db_connect()
    try:
        rc = plugin._record_upload(user, vpath, rpath, size, source, ts, conn)
        conn.commit()
        return rc
    finally:
        conn.close()


def _read_m3u(plugin):
    with open(plugin._playlist_path, encoding="utf-8") as f:
        return f.read()


def test_db_init_creates_schema(plugin):
    conn = sqlite3.connect(plugin._history_db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(uploads)")}
        assert cols == {"id", "ts", "user", "virtual_path", "real_path", "size", "source"}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1
    finally:
        conn.close()


def test_db_init_is_idempotent(plugin):
    plugin._db_init()
    plugin._db_init()
    _insert(plugin, "alice", "music\\a.mp3", "/x/a.mp3")
    conn = sqlite3.connect(plugin._history_db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_record_upload_unique_dedup(plugin):
    rc1 = _insert(plugin, "alice", "music\\a.mp3", "/x/a.mp3")
    rc2 = _insert(plugin, "alice", "music\\a.mp3", "/x/a.mp3")
    assert rc1 == 1
    assert rc2 == 0


def test_record_upload_different_users_not_deduped(plugin):
    _insert(plugin, "alice", "music\\a.mp3", "/x/a.mp3")
    _insert(plugin, "bob", "music\\a.mp3", "/x/a.mp3")
    conn = sqlite3.connect(plugin._history_db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_regenerate_m3u_chronological(plugin):
    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v\\b.mp3", "/x/b.mp3", ts="2026-05-17 11:00:00")
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.startswith("#EXTM3U\n")
    assert content.index("a.mp3") < content.index("b.mp3")


def test_regenerate_m3u_nulls_first(plugin):
    _insert(plugin, "alice", "v\\new.mp3", "/x/new.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "alice", "v\\old.mp3", "/x/old.mp3", ts=None)
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.index("old.mp3") < content.index("new.mp3")


def test_regenerate_m3u_filters_non_playable(plugin):
    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3")
    _insert(plugin, "alice", "v\\cover.jpg", "/x/cover.jpg")
    _insert(plugin, "alice", "v\\info.nfo", "/x/info.nfo")
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert "a.mp3" in content
    assert "cover.jpg" not in content
    assert "info.nfo" not in content


def test_regenerate_m3u_dedup_off_keeps_duplicates(plugin):
    _insert(plugin, "alice", "v1\\a.mp3", "/x/a.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v2\\a.mp3", "/x/a.mp3", ts="2026-05-17 11:00:00")
    plugin._regenerate_m3u()
    assert _read_m3u(plugin).count("/x/a.mp3") == 2


def test_regenerate_m3u_dedup_on_collapses_real_path(plugin):
    _insert(plugin, "alice", "v1\\a.mp3", "/x/a.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v2\\a.mp3", "/x/a.mp3", ts="2026-05-17 11:00:00")
    plugin.settings["dedup"] = True
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.count("/x/a.mp3") == 1
    assert "alice" in content
    assert "bob" not in content


def test_regenerate_m3u_uses_temp_file(plugin, tmp_path):
    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3")
    plugin._regenerate_m3u()
    assert not (tmp_path / "playlist.m3u8.tmp").exists()


def test_regenerate_m3u_dedup_keeps_first_occurrence_even_with_null_ts(plugin):
    # First insert has no timestamp (backfill of a missing file);
    # second insert has a real timestamp. MIN(id) should keep the NULL-ts row.
    _insert(plugin, "alice", "v1\\a.mp3", "/x/a.mp3", ts=None, source="backfill")
    _insert(plugin, "bob", "v2\\a.mp3", "/x/a.mp3", ts="2026-05-17 10:00:00")
    plugin.settings["dedup"] = True
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.count("/x/a.mp3") == 1
    assert "alice" in content
    assert "2026-05-17" not in content  # first-occurrence (NULL ts) wins


def _write_uploads_json(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_import_uploads_json_inserts_rows(plugin, tmp_path, monkeypatch):
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    _write_uploads_json(
        data_dir / "uploads.json",
        [
            ["alice", "music\\a.mp3", str(tmp_path), "Finished", 1024],
            ["bob", "music\\b.flac", str(tmp_path), "Finished", 2048],
        ],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    inserted = plugin._import_uploads_json()
    assert inserted == 2


def test_import_uploads_json_is_idempotent(plugin, tmp_path, monkeypatch):
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    _write_uploads_json(
        data_dir / "uploads.json",
        [["alice", "music\\a.mp3", str(tmp_path), "Finished"]],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    assert plugin._import_uploads_json() == 1
    assert plugin._import_uploads_json() == 0


def test_import_uploads_json_skips_unfinished(plugin, tmp_path, monkeypatch):
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    _write_uploads_json(
        data_dir / "uploads.json",
        [
            ["alice", "music\\a.mp3", str(tmp_path), "Finished"],
            ["bob", "music\\b.mp3", str(tmp_path), "Aborted"],
            ["carol", "music\\c.mp3", str(tmp_path), "Cancelled"],
        ],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    assert plugin._import_uploads_json() == 1


def test_import_uploads_json_uses_mtime_when_file_exists(plugin, tmp_path, monkeypatch):
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    real_file = tmp_path / "a.mp3"
    real_file.write_bytes(b"fake audio")
    _write_uploads_json(
        data_dir / "uploads.json",
        [["alice", "music\\a.mp3", str(tmp_path), "Finished"]],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    plugin._import_uploads_json()
    conn = sqlite3.connect(plugin._history_db_path)
    try:
        ts, size = conn.execute("SELECT ts, size FROM uploads").fetchone()
    finally:
        conn.close()
    assert ts is not None
    assert size == len(b"fake audio")


def test_import_uploads_json_merges_multiple_sources(plugin, tmp_path, monkeypatch):
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    _write_uploads_json(
        data_dir / "uploads.json",
        [["alice", "music\\new.mp3", str(tmp_path), "Finished"]],
    )
    _write_uploads_json(
        data_dir / "uploads.json.old",
        [
            ["alice", "music\\new.mp3", str(tmp_path), "Finished"],  # dup across sources
            ["bob", "music\\old.mp3", str(tmp_path), "Finished"],  # unique to .old
        ],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    inserted = plugin._import_uploads_json()
    assert inserted == 2


def test_import_uploads_json_null_ts_when_file_missing(plugin, tmp_path, monkeypatch):
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    _write_uploads_json(
        data_dir / "uploads.json",
        [["alice", "music\\gone.mp3", str(tmp_path), "Finished"]],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    plugin._import_uploads_json()
    conn = sqlite3.connect(plugin._history_db_path)
    try:
        ts, size = conn.execute("SELECT ts, size FROM uploads").fetchone()
    finally:
        conn.close()
    assert ts is None
    assert size is None
