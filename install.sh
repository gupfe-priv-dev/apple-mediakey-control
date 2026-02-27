#!/bin/bash
# install.sh — downloads and installs MediaKeyControl
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/gupfe-priv-dev/apple-mediakey-control/main/install.sh)"

set -euo pipefail

REPO="gupfe-priv-dev/apple-mediakey-control"
APP_NAME="MediaKeyControl"
DEST="/Applications/$APP_NAME.app"

# ── Language detection ────────────────────────────────────────────────────────
PRIMARY_LANG=$(defaults read -g AppleLanguages 2>/dev/null | grep -m1 -o '"[a-z][a-z]' | tr -d '"' || echo "en")
if [[ "$PRIMARY_LANG" == "de" ]]; then
    T_TITLE="MediaKeyControl  Installation"
    T_FETCHING="  Neueste Version wird ermittelt..."
    T_DOWNLOADING="  Wird heruntergeladen"
    T_QUESTION="  MediaKeyControl in Programme installieren?"
    T_YES="    [J]  Ja  — jetzt installieren  (empfohlen)"
    T_NO="    [N]  Nein — abbrechen"
    T_YES_KEYS="^[JjYy]"
    T_PROMPT="  Ihre Wahl [J/n]: "
    T_ABORTED="  Abgebrochen."
    T_INSTALLING="  Installiere in /Applications..."
    T_INSTALLED="  ✓  Installiert."
    T_LAUNCHING="  Wird gestartet..."
    T_ACCESSIBILITY="  → Bedienungshilfen erlauben, wenn gefragt"
    T_BOOKMARK="  → URL als Lesezeichen auf dem Handy speichern:"
    T_CLIPBOARD="      (bereits in der Zwischenablage)"
    T_DONE="  Fertig."
else
    T_TITLE="MediaKeyControl  Installer"
    T_FETCHING="  Fetching latest release..."
    T_DOWNLOADING="  Downloading"
    T_QUESTION="  Install MediaKeyControl to /Applications?"
    T_YES="    [Y]  Yes — install now  (recommended)"
    T_NO="    [N]  No  — cancel"
    T_YES_KEYS="^[Yy]"
    T_PROMPT="  Your choice [Y/n]: "
    T_ABORTED="  Aborted."
    T_INSTALLING="  Installing to /Applications..."
    T_INSTALLED="  ✓  Installed."
    T_LAUNCHING="  Launching..."
    T_ACCESSIBILITY="  → Grant Accessibility when prompted"
    T_BOOKMARK="  → Bookmark this URL on your phone:"
    T_CLIPBOARD="      (already copied to clipboard)"
    T_DONE="  Done."
fi

# ── Header ────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  $T_TITLE  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Fetch latest release info ─────────────────────────────────────────────────
echo "$T_FETCHING"
LATEST_JSON=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")
TAG=$(echo "$LATEST_JSON" | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
ZIP_URL=$(echo "$LATEST_JSON" | grep '"browser_download_url"' | grep '\.zip"' | sed 's/.*"browser_download_url": *"\([^"]*\)".*/\1/')
echo "  $TAG"
echo ""

# ── Ask user ──────────────────────────────────────────────────────────────────
echo "$T_QUESTION"
echo ""
echo "$T_YES"
echo "$T_NO"
echo ""
read -r -p "$T_PROMPT" answer
answer="${answer:-Y}"
echo ""

if [[ ! "$answer" =~ $T_YES_KEYS ]]; then
    echo "$T_ABORTED"
    echo ""
    exit 0
fi

# ── Download ──────────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "$T_DOWNLOADING $TAG..."
curl -fsSL "$ZIP_URL" -o "$TMP/release.zip"
unzip -q "$TMP/release.zip" -d "$TMP/extracted"
echo ""

# ── Install ───────────────────────────────────────────────────────────────────
echo "$T_INSTALLING"
pkill -x "$APP_NAME" 2>/dev/null || true
sleep 0.5
rm -rf "$DEST"
cp -r "$TMP/extracted/$APP_NAME.app" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
echo "$T_INSTALLED"
echo ""

# ── Bonjour URL → clipboard ───────────────────────────────────────────────────
HOST=$(scutil --get LocalHostName 2>/dev/null || hostname)
URL="http://${HOST}.local:8765"
echo "$URL" | pbcopy

# ── Launch ────────────────────────────────────────────────────────────────────
echo "$T_LAUNCHING"
open "$DEST"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "  ────────────────────────────────────────"
echo "$T_ACCESSIBILITY"
echo "$T_BOOKMARK"
echo "      $URL"
echo "$T_CLIPBOARD"
echo "  ────────────────────────────────────────"
echo ""
echo "$T_DONE"
echo ""
