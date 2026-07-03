import json
import sqlite3

import pytest
from upload_playlist import Plugin


@pytest.fixture
def plugin(tmp_path):
    p = Plugin()
    p.settings["playlist_path"] = str(tmp_path / "playlist.m3u8")
    p.init()
    return p


def _insert(plugin, user, vpath, rpath, ts="2026-05-17 12:00:00", source="live"):
    conn = plugin._db_connect()
    try:
        rc = plugin._record_upload(user, vpath, rpath, source, ts, conn)
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
        assert cols == {
            "id",
            "ts",
            "user",
            "virtual_path",
            "real_path",
            "real_dir",
            "source",
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 2
    finally:
        conn.close()


def test_db_init_migrates_v1_to_v2(tmp_path):
    """A pre-existing v1 DB (no real_dir column) gets the column added and backfilled."""
    from upload_playlist import Plugin

    db_path = tmp_path / "playlist.m3u8.history.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE uploads (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           TEXT,
                user         TEXT NOT NULL,
                virtual_path TEXT NOT NULL,
                real_path    TEXT NOT NULL,
                size         INTEGER,
                source       TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            """
        )
        conn.execute(
            "INSERT INTO uploads (ts, user, virtual_path, real_path, size, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-05-17 10:00:00", "alice", "v\\a.mp3", "/music/Album/01.mp3", 1000, "live"),
        )
        conn.commit()
    finally:
        conn.close()

    p = Plugin()
    p.settings["playlist_path"] = str(tmp_path / "playlist.m3u8")
    p._playlist_path = p.settings["playlist_path"]
    p._history_db_path = p._playlist_path + ".history.db"
    p._db_init()

    conn = sqlite3.connect(str(db_path))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(uploads)")}
        assert "real_dir" in cols
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        row = conn.execute("SELECT real_dir FROM uploads").fetchone()
        assert row[0] == "/music/Album"
    finally:
        conn.close()


def test_record_upload_stores_real_dir(plugin):
    _insert(plugin, "alice", "v\\a.mp3", "/music/Album/01.mp3")
    conn = sqlite3.connect(plugin._history_db_path)
    try:
        row = conn.execute("SELECT real_dir FROM uploads").fetchone()
    finally:
        conn.close()
    assert row[0] == "/music/Album"


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
    plugin.settings["ordering"] = "chronological"
    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v\\b.mp3", "/x/b.mp3", ts="2026-05-17 11:00:00")
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.startswith("#EXTM3U\n")
    assert content.index("a.mp3") < content.index("b.mp3")


def test_regenerate_m3u_nulls_first(plugin):
    plugin.settings["ordering"] = "chronological"
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
    plugin.settings["ordering"] = "chronological"
    _insert(plugin, "alice", "v1\\a.mp3", "/x/a.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v2\\a.mp3", "/x/a.mp3", ts="2026-05-17 11:00:00")
    plugin._regenerate_m3u()
    assert _read_m3u(plugin).count("/x/a.mp3") == 2


def test_regenerate_m3u_dedup_on_collapses_real_path(plugin):
    plugin.settings["ordering"] = "chronological"
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


def test_regenerate_m3u_returns_true_on_success(plugin):
    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3")
    assert plugin._regenerate_m3u() is True


def test_regenerate_m3u_handles_permission_error_on_replace(plugin, tmp_path, monkeypatch):
    """Windows-style lock on the destination: clean up .tmp, log, return False."""
    import upload_playlist

    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3")

    def raising_replace(*args, **kwargs):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(upload_playlist.os, "replace", raising_replace)

    messages = []
    monkeypatch.setattr(plugin, "log", lambda msg: messages.append(msg))

    assert plugin._regenerate_m3u() is False
    assert not (tmp_path / "playlist.m3u8.tmp").exists()
    assert any("/playlist-reload" in m for m in messages)


def test_regenerate_m3u_by_album_groups_by_folder(plugin):
    # Inserted in non-album order; after regen tracks from the same folder must be contiguous
    # and within a folder, sorted by filename.
    _insert(plugin, "alice", "v\\b1.mp3", "/music/AlbumB/01.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "alice", "v\\a2.mp3", "/music/AlbumA/02.mp3", ts="2026-05-17 11:00:00")
    _insert(plugin, "alice", "v\\b2.mp3", "/music/AlbumB/02.mp3", ts="2026-05-17 12:00:00")
    _insert(plugin, "alice", "v\\a1.mp3", "/music/AlbumA/01.mp3", ts="2026-05-17 13:00:00")
    plugin.settings["ordering"] = "by-album"
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    order = [
        content.index(p)
        for p in (
            "/music/AlbumA/01.mp3",
            "/music/AlbumA/02.mp3",
            "/music/AlbumB/01.mp3",
            "/music/AlbumB/02.mp3",
        )
    ]
    assert order == sorted(order)


def test_regenerate_m3u_by_album_chronological_orders_folders_by_first_ts(plugin):
    # AlbumB's first track lands before AlbumA's, so AlbumB should appear first as a group.
    _insert(plugin, "alice", "v\\b1.mp3", "/music/AlbumB/01.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "alice", "v\\a1.mp3", "/music/AlbumA/01.mp3", ts="2026-05-17 11:00:00")
    _insert(plugin, "alice", "v\\b2.mp3", "/music/AlbumB/02.mp3", ts="2026-05-17 12:00:00")
    _insert(plugin, "alice", "v\\a2.mp3", "/music/AlbumA/02.mp3", ts="2026-05-17 13:00:00")
    plugin.settings["ordering"] = "by-album-chronological"
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    order = [
        content.index(p)
        for p in (
            "/music/AlbumB/01.mp3",
            "/music/AlbumB/02.mp3",
            "/music/AlbumA/01.mp3",
            "/music/AlbumA/02.mp3",
        )
    ]
    assert order == sorted(order)


def test_regenerate_m3u_by_album_chronological_stable_on_redownload(plugin):
    # AlbumA arrived first. Later, a fresh AlbumB track lands, *then* a redownload of AlbumA.
    # AlbumA must stay in its original position — MIN(ts), not MAX(ts).
    _insert(plugin, "alice", "v\\a1.mp3", "/music/AlbumA/01.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "alice", "v\\b1.mp3", "/music/AlbumB/01.mp3", ts="2026-05-17 11:00:00")
    _insert(plugin, "bob", "v\\a1b.mp3", "/music/AlbumA/01.mp3", ts="2026-05-17 12:00:00")
    plugin.settings["ordering"] = "by-album-chronological"
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.index("/music/AlbumA/01.mp3") < content.index("/music/AlbumB/01.mp3")


def test_regenerate_m3u_by_album_chronological_tiebreaks_by_insert_order(plugin):
    # Two folders whose first tracks share the same timestamp — insert order (MIN(id)) decides.
    # AlbumB is inserted first so it must appear first despite alphabetical ordering.
    _insert(plugin, "alice", "v\\b1.mp3", "/music/AlbumB/01.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "alice", "v\\a1.mp3", "/music/AlbumA/01.mp3", ts="2026-05-17 10:00:00")
    plugin.settings["ordering"] = "by-album-chronological"
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.index("/music/AlbumB/01.mp3") < content.index("/music/AlbumA/01.mp3")


def test_regenerate_m3u_by_album_chronological_null_ts_folders_first(plugin):
    # NULL-ts (backfill of missing file) folder should sort before timestamped folders.
    _insert(plugin, "alice", "v\\a1.mp3", "/music/Backfilled/01.mp3", ts=None, source="backfill")
    _insert(plugin, "alice", "v\\b1.mp3", "/music/Live/01.mp3", ts="2026-05-17 10:00:00")
    plugin.settings["ordering"] = "by-album-chronological"
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.index("/music/Backfilled/01.mp3") < content.index("/music/Live/01.mp3")


def test_regenerate_m3u_by_album_chronological_with_dedup(plugin):
    # Same track uploaded by two users: dedup collapses to one entry; folder ordering still by
    # MIN(ts) per folder (here, just one folder, so the test is about correctness of the join).
    _insert(plugin, "alice", "v1\\a.mp3", "/music/Album/01.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v2\\a.mp3", "/music/Album/01.mp3", ts="2026-05-17 11:00:00")
    _insert(plugin, "alice", "v3\\b.mp3", "/music/Album/02.mp3", ts="2026-05-17 12:00:00")
    plugin.settings["ordering"] = "by-album-chronological"
    plugin.settings["dedup"] = True
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.count("/music/Album/01.mp3") == 1
    assert content.count("/music/Album/02.mp3") == 1
    assert content.index("/music/Album/01.mp3") < content.index("/music/Album/02.mp3")
    assert "alice" in content
    assert "bob" not in content


def test_regenerate_m3u_by_album_with_dedup(plugin):
    _insert(plugin, "alice", "v1\\a.mp3", "/music/Album/01.mp3", ts="2026-05-17 10:00:00")
    _insert(plugin, "bob", "v2\\a.mp3", "/music/Album/01.mp3", ts="2026-05-17 11:00:00")
    _insert(plugin, "alice", "v3\\b.mp3", "/music/Album/02.mp3", ts="2026-05-17 12:00:00")
    plugin.settings["ordering"] = "by-album"
    plugin.settings["dedup"] = True
    plugin._regenerate_m3u()
    content = _read_m3u(plugin)
    assert content.count("/music/Album/01.mp3") == 1
    assert content.count("/music/Album/02.mp3") == 1
    assert content.index("/music/Album/01.mp3") < content.index("/music/Album/02.mp3")
    assert "alice" in content
    assert "bob" not in content  # first occurrence wins


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


def test_cmd_clear_empties_table_and_playlist(plugin):
    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3")
    _insert(plugin, "bob", "v\\b.mp3", "/x/b.mp3")
    plugin._regenerate_m3u()

    plugin.cmd_clear("")

    conn = sqlite3.connect(plugin._history_db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
    finally:
        conn.close()
    assert _read_m3u(plugin) == "#EXTM3U\n"


def test_cmd_clear_survives_reinit_without_rebackfill(plugin, tmp_path, monkeypatch):
    """Clear keeps the DB file, so a later init() must not auto-backfill from uploads.json."""
    data_dir = tmp_path / "nicotine"
    data_dir.mkdir()
    _write_uploads_json(
        data_dir / "uploads.json",
        [["alice", "music\\a.mp3", str(tmp_path), "Finished"]],
    )
    monkeypatch.setattr(plugin, "_nicotine_data_dirs", lambda: [str(data_dir)])

    _insert(plugin, "alice", "v\\a.mp3", "/x/a.mp3")
    plugin.cmd_clear("")

    # Simulate a Nicotine+ restart: fresh plugin instance, same paths.
    p2 = Plugin()
    p2.settings["playlist_path"] = plugin._playlist_path
    p2._nicotine_data_dirs = lambda: [str(data_dir)]
    p2.init()

    conn = sqlite3.connect(p2._history_db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
    finally:
        conn.close()


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
        (ts,) = conn.execute("SELECT ts FROM uploads").fetchone()
    finally:
        conn.close()
    assert ts is not None


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
        (ts,) = conn.execute("SELECT ts FROM uploads").fetchone()
    finally:
        conn.close()
    assert ts is None
