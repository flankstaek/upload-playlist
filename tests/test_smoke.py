from upload_playlist import Plugin


def test_plugin_instantiates():
    p = Plugin()
    assert "playlist_path" in p.settings
    assert "audio_extensions" in p.settings
    assert "playlist-path" in p.commands
    assert "playlist-backfill" in p.commands
