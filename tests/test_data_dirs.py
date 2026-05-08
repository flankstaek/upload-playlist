import pytest
from upload_playlist import Plugin


@pytest.fixture
def plugin():
    return Plugin()


def test_windows_uses_appdata(plugin, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    dirs = plugin._nicotine_data_dirs()
    assert len(dirs) == 1
    assert dirs[0].startswith(r"C:\Users\test\AppData\Roaming")
    assert dirs[0].endswith("nicotine")


def test_windows_without_appdata_returns_empty(plugin, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    assert plugin._nicotine_data_dirs() == []


def test_macos_uses_application_support(plugin, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    dirs = plugin._nicotine_data_dirs()
    assert dirs == ["/Users/test/Library/Application Support/nicotine"]


def test_linux_with_xdg_data_home(plugin, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
    dirs = plugin._nicotine_data_dirs()
    assert dirs[0] == "/custom/data/nicotine"
    assert "/home/test/.var/app/org.nicotine_plus.Nicotine/data/nicotine" in dirs
    assert "/home/test/.nicotine" in dirs


def test_linux_without_xdg_falls_back_to_local_share(plugin, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    dirs = plugin._nicotine_data_dirs()
    assert dirs[0] == "/home/test/.local/share/nicotine"


def test_linux_returns_flatpak_and_legacy_paths(plugin, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    dirs = plugin._nicotine_data_dirs()
    assert len(dirs) == 3
