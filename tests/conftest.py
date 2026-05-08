import importlib.util
import sys
import types
from pathlib import Path

_pkg = types.ModuleType("pynicotine")
_plugins = types.ModuleType("pynicotine.pluginsystem")


class _BasePluginStub:
    def __init__(self, *args, **kwargs):
        pass

    def log(self, *args, **kwargs):
        pass

    def output(self, *args, **kwargs):
        pass


_plugins.BasePlugin = _BasePluginStub
_pkg.pluginsystem = _plugins
sys.modules.setdefault("pynicotine", _pkg)
sys.modules.setdefault("pynicotine.pluginsystem", _plugins)

_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("upload_playlist", _ROOT / "__init__.py")
upload_playlist = importlib.util.module_from_spec(_spec)
sys.modules["upload_playlist"] = upload_playlist
_spec.loader.exec_module(upload_playlist)
