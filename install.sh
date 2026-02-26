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

# ── Language detection ────────────────────────────────────────────────────────
PRIMARY_LANG=$(defaults read -g AppleLanguages 2>/dev/null | grep -m1 -o '"[a-z][a-z]' | tr -d '"' || echo "en")
if [[ "$PRIMARY_LANG" == "de" ]]; then
    T_TITLE="  MediaKeyControl  Installation"
    T_NOT_BUILT="  App noch nicht erstellt — build.sh wird ausgeführt..."
    T_QUESTION="  MediaKeyControl in Programme installieren?"
    T_YES="    [J]  Ja  — jetzt installieren  (empfohlen)"
    T_NO="    [N]  Nein — manuelle Schritte anzeigen"
    T_PROMPT="  Ihre Wahl [J/n]: "
    T_YES_KEYS="^[JjYy]"
    T_MANUAL="  Für die manuelle Installation diese Befehle im Terminal ausführen:"
    T_INSTALLING="  Installiere in Programme..."
    T_INSTALLED="  ✓  Installiert."
    T_LAUNCHING="  Wird gestartet..."
    T_WEBUI="  Web-Oberfläche:"
    T_CLIPBOARD="  (In die Zwischenablage kopiert — im Browser des Telefons einfügen)"
    T_DONE="  Fertig. Dieses Fenster kann geschlossen werden."
else
    T_TITLE="  MediaKeyControl  Installer"
    T_NOT_BUILT="  App not built yet — running build.sh first..."
    T_QUESTION="  Install MediaKeyControl to /Applications?"
    T_YES="    [Y]  Yes — install now  (recommended)"
    T_NO="    [N]  No  — show manual steps"
    T_PROMPT="  Your choice [Y/n]: "
    T_YES_KEYS="^[Yy]"
    T_MANUAL="  To install manually, run these commands in Terminal:"
    T_INSTALLING="  Installing to $DEST..."
    T_INSTALLED="  ✓  Installed."
    T_LAUNCHING="  Launching..."
    T_WEBUI="  Web UI:"
    T_CLIPBOARD="  (copied to clipboard — paste into your phone's browser)"
    T_DONE="  Done. You can close this window."
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  $T_TITLE  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Build if not already built ────────────────────────────────────────────────
if [[ ! -d "$APP" ]]; then
    echo "$T_NOT_BUILT"
    "$DIR/build.sh"
fi

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
    echo "$T_MANUAL"
    echo ""
    echo "    cp -r \"$APP\" /Applications/"
    echo "    xattr -dr com.apple.quarantine /Applications/$APP_NAME.app"
    echo "    open /Applications/$APP_NAME.app"
    echo ""
    echo "  ────────────────────────────────────────"
    (sleep 0.5 && osascript -e 'tell application "Terminal" to close front window') &
    disown
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────
echo "$T_INSTALLING"

pkill -x "$APP_NAME" 2>/dev/null || true
sleep 0.5

rm -rf "$DEST"
cp -r "$APP" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo "$T_INSTALLED"
echo ""

# ── Bonjour URL → clipboard ───────────────────────────────────────────────────
HOST=$(scutil --get LocalHostName 2>/dev/null || hostname)
URL="http://${HOST}.local:8765"
echo "$URL" | pbcopy

echo "$T_LAUNCHING"
open "$DEST"

# ── Write summary file and open it ───────────────────────────────────────────
if [[ "$PRIMARY_LANG" == "de" ]]; then
    SUMMARY="$HOME/Desktop/MediaKeyControl Info.txt"
    cat > "$SUMMARY" << EOF
MediaKeyControl – Installiert
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ App installiert:  /Applications/MediaKeyControl.app
✓ URL (Lesezeichen auf dem Handy speichern):

   $URL

   (bereits in der Zwischenablage)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Erster Start:
  • Bedienungshilfen erlauben, wenn gefragt
  • URL auf dem Handy als Lesezeichen speichern
    oder zum Home-Bildschirm hinzufügen

Die App erscheint in der Menüleiste (⌨ Symbol)
EOF
else
    SUMMARY="$HOME/Desktop/MediaKeyControl Info.txt"
    cat > "$SUMMARY" << EOF
MediaKeyControl – Installed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ App installed:  /Applications/MediaKeyControl.app
✓ Web UI (bookmark this on your phone):

   $URL

   (already copied to clipboard)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
First launch:
  • Grant Accessibility when prompted
  • Bookmark the URL on your phone
    or add it to your Home Screen

The app lives in your menu bar (⌨ icon)
EOF
fi

open "$SUMMARY"

# ── Self-close Terminal window (delay gives TextEdit time to open) ────────────
(sleep 2 && osascript -e 'tell application "Terminal" to close front window') &
disown
exit 0
