#!/bin/bash
# install.sh — installs MediaKeyControl.app to /Applications
#
# Usage:
#   ./install.sh          # install (builds first if needed)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MediaKeyControl"
APP="$DIR/$APP_NAME.app"
DEST="/Applications/$APP_NAME.app"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     MediaKeyControl  Installer       ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Build if not already built ────────────────────────────────────────────────
if [[ ! -d "$APP" ]]; then
    echo "  App not built yet — running build.sh first..."
    "$DIR/build.sh"
fi

# ── Ask user ──────────────────────────────────────────────────────────────────
echo "  Install MediaKeyControl to /Applications?"
echo ""
echo "    [Y]  Yes — install now  (recommended)"
echo "    [N]  No  — show manual steps"
echo ""
read -r -p "  Your choice [Y/n]: " answer
answer="${answer:-Y}"
echo ""

if [[ "$answer" =~ ^[Nn] ]]; then
    echo "  To install manually, run these commands in Terminal:"
    echo ""
    echo "    sudo cp -r \"$APP\" /Applications/"
    echo "    xattr -dr com.apple.quarantine /Applications/$APP_NAME.app"
    echo "    open /Applications/$APP_NAME.app"
    echo ""
    echo "  ────────────────────────────────────────"
    echo "  Done. You can close this window."
    echo ""
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────
echo "  Installing to $DEST..."

pkill -x "$APP_NAME" 2>/dev/null || true
sleep 0.5

rm -rf "$DEST"
cp -r "$APP" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo "  ✓  Installed."
echo ""
echo "  Launching..."
open "$DEST"
echo ""
echo "  ────────────────────────────────────────"
echo "  Done. You can close this window."
echo ""
