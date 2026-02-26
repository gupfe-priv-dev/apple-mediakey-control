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

# ── Build if not already built ────────────────────────────────────────────────
if [[ ! -d "$APP" ]]; then
    echo ""
    echo "  App not built yet — running build.sh first..."
    "$DIR/build.sh"
fi

# ── Install ───────────────────────────────────────────────────────────────────
echo ""
echo "  Installing to $DEST..."

pkill -x "$APP_NAME" 2>/dev/null || true
sleep 0.5

rm -rf "$DEST"
cp -r "$APP" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo "  ✓  Installed."
echo ""
echo "  Launch: open '$DEST'"
echo ""
