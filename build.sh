#!/bin/bash
# build.sh — builds MediaKeyControl.app in the project directory
#
# Usage:
#   ./build.sh

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MediaKeyControl"
APP="$DIR/$APP_NAME.app"
# ── Version: latest tag + 1 patch (override with VERSION env var if needed) ───
# On main: tag patch +1 (e.g. v1.0.1 → 1.0.2). Release pipeline creates the tag.
# On other branches: tag.shortcommit-YYMMDDhhmm (e.g. 1.0.1.abc1234-2602261430)
if [[ -z "${VERSION:-}" ]]; then
    LAST_TAG=$(git -C "$DIR" describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    BASE="${LAST_TAG#v}"
    BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    IFS='.' read -r MAJOR MINOR PATCH <<< "$BASE"
    if [[ "$BRANCH" == "main" ]]; then
        VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
    else
        SHORT_COMMIT=$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null || echo "0000000")
        SHORT_DATE=$(date +%y%m%d%H%M)
        VERSION="${BASE}.${SHORT_COMMIT}-${SHORT_DATE}"
    fi
fi

echo ""
echo "  Building $APP_NAME.app..."
echo ""

# ── Clean previous build ───────────────────────────────────────────────────────
rm -rf "$APP"

# ── Create bundle structure ────────────────────────────────────────────────────
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
mkdir -p "$MACOS" "$RESOURCES"

# ── Compile Swift app (menu bar launcher) ─────────────────────────────────────
echo "  [1/3] Compiling app launcher..."
swiftc "$DIR/app.swift" \
    -framework AppKit \
    -framework Foundation \
    -o "$MACOS/$APP_NAME"
echo "        ✓ $APP_NAME"

# ── Compile Swift NX-key helper ───────────────────────────────────────────────
echo "  [2/3] Compiling NX-key helper..."
swiftc "$DIR/mediakey.swift" -o "$RESOURCES/mediakey"
echo "        ✓ mediakey"

# ── Copy Python server ────────────────────────────────────────────────────────
echo "  [3/3] Copying server.py..."
cp "$DIR/server.py" "$RESOURCES/server.py"
echo "        ✓ server.py"

# ── Copy app icon ──────────────────────────────────────────────────────────────
if [[ -f "$DIR/AppIcon.icns" ]]; then
    cp "$DIR/AppIcon.icns" "$RESOURCES/AppIcon.icns"
fi

# ── Info.plist ────────────────────────────────────────────────────────────────
cat > "$CONTENTS/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>      <string>MediaKeyControl</string>
    <key>CFBundleIdentifier</key>      <string>com.gunnar.mediakeycontrol</string>
    <key>CFBundleName</key>            <string>MediaKeyControl</string>
    <key>CFBundleDisplayName</key>     <string>MediaKeyControl</string>
    <key>CFBundleVersion</key>         <string>$VERSION</string>
    <key>CFBundleShortVersionString</key> <string>$VERSION</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>NSPrincipalClass</key>        <string>NSApplication</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>CFBundleIconFile</key>        <string>AppIcon</string>
    <!-- Menu bar only — no Dock icon -->
    <key>LSUIElement</key>             <true/>
    <!-- Accessibility usage description shown in System Settings -->
    <key>NSAccessibilityUsageDescription</key>
    <string>MediaKeyControl needs Accessibility permission to simulate media and brightness keys on your Mac.</string>
</dict>
</plist>
PLIST

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ✓  Built: $APP"
echo ""
echo "  To install:  ./install.sh"
echo "  To run now:  open '$APP'"
echo ""
