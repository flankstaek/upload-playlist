#!/usr/bin/env bash
# Install the upload_playlist plugin into the Nicotine+ plugins directory.
#
# Background: Nicotine+ loads plugins from a per-platform data dir:
#   Windows : %APPDATA%\nicotine\plugins\<plugin_id>\
#   macOS   : ~/Library/Application Support/nicotine/plugins/<plugin_id>/
#   Linux   : $XDG_DATA_HOME/nicotine/plugins/<plugin_id>/
#             (defaults to ~/.local/share/nicotine/plugins/<plugin_id>/)
#
# This script targets the WSL-to-Windows dev flow: the repo lives in WSL, but
# Nicotine+ runs natively on Windows. Windows can't follow Linux symlinks, so
# we copy the plugin files across the /mnt/c boundary on each run.
#
# The destination is auto-detected by reading %APPDATA% from Windows via
# cmd.exe and translating it with `wslpath`. To target a different location
# (e.g. a native Linux install, or a non-standard path), set
# NICOTINE_PLUGINS_DIR to the plugins directory before running:
#
#   NICOTINE_PLUGINS_DIR=~/.local/share/nicotine/plugins ./install.sh

set -euo pipefail

PLUGIN_ID="upload_playlist"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${NICOTINE_PLUGINS_DIR:-}" ]]; then
    DEST_ROOT="$NICOTINE_PLUGINS_DIR"
else
    if ! command -v cmd.exe >/dev/null 2>&1 || ! command -v wslpath >/dev/null 2>&1; then
        echo "error: auto-detection expects WSL (needs cmd.exe and wslpath)." >&2
        echo "       Set NICOTINE_PLUGINS_DIR to your Nicotine+ plugins dir and re-run." >&2
        exit 1
    fi

    WIN_APPDATA="$(cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r')"
    if [[ -z "$WIN_APPDATA" ]]; then
        echo "error: could not read %APPDATA% from Windows." >&2
        exit 1
    fi

    DEST_ROOT="$(wslpath "$WIN_APPDATA")/nicotine/plugins"
fi

DEST_DIR="$DEST_ROOT/$PLUGIN_ID"

if [[ ! -d "$DEST_ROOT" ]]; then
    echo "error: Nicotine+ plugins dir not found at $DEST_ROOT" >&2
    echo "       Is Nicotine+ installed? Run it once to create its config dir." >&2
    exit 1
fi

mkdir -p "$DEST_DIR"
cp "$SRC_DIR/PLUGININFO" "$DEST_DIR/PLUGININFO"
cp "$SRC_DIR/__init__.py" "$DEST_DIR/__init__.py"

echo "installed $PLUGIN_ID -> $DEST_DIR"
echo "in Nicotine+: Preferences -> Plugins -> toggle 'Upload Playlist' off/on to reload."
