import pytest
from upload_playlist import Plugin


@pytest.fixture
def plugin(tmp_path):
    p = Plugin()
    p.settings["playlist_path"] = str(tmp_path / "playlist.m3u8")
    p.init()
    return p


@pytest.mark.parametrize(
    "path",
    [
        "song.mp3",
        "track.flac",
        "tune.m4a",
        "song.OGG",
        "/abs/path/to/song.opus",
        r"C:\Users\x\song.wav",
        "weird name with spaces.aiff",
    ],
)
def test_playable_extensions(plugin, path):
    assert plugin._is_playable(path)


@pytest.mark.parametrize(
    "path",
    [
        "cover.jpg",
        "log.txt",
        "archive.zip",
        "playlist.m3u",
        "no_extension",
        "",
        ".",
        "song",
    ],
)
def test_unplayable_extensions(plugin, path):
    assert not plugin._is_playable(path)


def test_double_extension_uses_last(plugin):
    assert not plugin._is_playable("song.flac.txt")
