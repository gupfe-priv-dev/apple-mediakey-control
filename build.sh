#!/bin/bash
# build.sh — builds MediaKeyControl.app in the project directory
#
# Usage:
#   ./build.sh

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MediaKeyControl"
APP="$DIR/$APP_NAME.app"
VERSION="1.1"

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
