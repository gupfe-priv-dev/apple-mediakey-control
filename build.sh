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

# ── Compile Swift app (menu bar launcher) — universal binary ──────────────────
# arm64: macOS 11.0+ (minimum for Apple Silicon Macs)
# x86_64: macOS 10.15+ (Catalina, includes Swift 5 runtime)
echo "  [1/3] Compiling app launcher (universal)..."
swiftc "$DIR/app.swift" \
    -framework AppKit \
    -framework Foundation \
    -target arm64-apple-macos11.0 \
    -o "$MACOS/${APP_NAME}_arm64"
swiftc "$DIR/app.swift" \
    -framework AppKit \
    -framework Foundation \
    -target x86_64-apple-macos10.15 \
    -o "$MACOS/${APP_NAME}_x86_64"
lipo -create \
    "$MACOS/${APP_NAME}_arm64" \
    "$MACOS/${APP_NAME}_x86_64" \
    -output "$MACOS/$APP_NAME"
rm "$MACOS/${APP_NAME}_arm64" "$MACOS/${APP_NAME}_x86_64"
# Re-sign the executable with the bundle ID as identifier so TCC can match it.
# --sign - (ad-hoc) + explicit --identifier fixes the lipo-slice naming issue
# where the linker would have left the identifier as "MediaKeyControl_arm64".
# We sign only the executable (not --deep) to avoid sealing Resources, which
# would otherwise create a new TCC identity on every rebuild.
codesign --force --sign - \
    --identifier "com.gunnar.mediakeycontrol" \
    "$MACOS/$APP_NAME"
echo "        ✓ $APP_NAME (universal: arm64 + x86_64)"

# ── Compile Swift NX-key helper — universal binary ────────────────────────────
echo "  [2/3] Compiling NX-key helper (universal)..."
swiftc "$DIR/mediakey.swift" -target arm64-apple-macos11.0  -o "$RESOURCES/mediakey_arm64"
swiftc "$DIR/mediakey.swift" -target x86_64-apple-macos10.15 -o "$RESOURCES/mediakey_x86_64"
lipo -create "$RESOURCES/mediakey_arm64" "$RESOURCES/mediakey_x86_64" -output "$RESOURCES/mediakey"
rm "$RESOURCES/mediakey_arm64" "$RESOURCES/mediakey_x86_64"
echo "        ✓ mediakey (universal: arm64 + x86_64)"

# ── Compile Python server (standalone — no Python needed on target) ───────────
echo "  [3/3] Compiling Python server (standalone)..."

BUILD_TMP="$DIR/.build-server"
rm -rf "$BUILD_TMP"

# Use an isolated venv so we never touch the system/Homebrew Python environment
python3 -m venv "$BUILD_TMP/venv"
VENV_PY="$BUILD_TMP/venv/bin/python3"
"$VENV_PY" -m pip install --quiet pyinstaller

"$VENV_PY" -m PyInstaller \
    --onefile \
    --name server \
    --distpath "$BUILD_TMP/dist" \
    --workpath "$BUILD_TMP/work" \
    --specpath "$BUILD_TMP" \
    --noconfirm \
    --log-level WARN \
    "$DIR/server.py"
cp "$BUILD_TMP/dist/server" "$RESOURCES/server"
rm -rf "$BUILD_TMP"
echo "        ✓ server (standalone, $(uname -m))"

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
    <!-- Minimum OS (Catalina for Intel, Big Sur for Apple Silicon) -->
    <key>LSMinimumSystemVersion</key>  <string>10.15</string>
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
