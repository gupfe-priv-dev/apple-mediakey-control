#!/bin/bash
# release-asset.sh — build and upload the release asset to the matching GitHub release
#
# Run this locally after triggering the release workflow on GitHub:
#   1. Go to Actions → Release → Run workflow
#   2. Once it completes (tag + GitHub Release created), run:
#        ./release-asset.sh

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MediaKeyControl"
REPO="gupfe-priv-dev/apple-mediakey-control"

# ── Build ─────────────────────────────────────────────────────────────────────
"$DIR/build.sh"

# ── Derive version from built app ─────────────────────────────────────────────
VERSION=$(defaults read "$DIR/$APP_NAME.app/Contents/Info.plist" CFBundleShortVersionString)
TAG="v${VERSION}"
ZIP="${APP_NAME}-${TAG}.zip"

echo ""
echo "  Packaging ${ZIP}..."

# ── Create zip ────────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
cp -r "$DIR/$APP_NAME.app" "$TMP/"
cp "$DIR/install.sh" "$TMP/"
(cd "$TMP" && zip -r "$DIR/$ZIP" .)
rm -rf "$TMP"

# ── Upload to GitHub release ──────────────────────────────────────────────────
echo "  Uploading to GitHub release ${TAG}..."
gh release delete-asset "$TAG" "$ZIP" --repo "$REPO" -y 2>/dev/null || true
gh release upload "$TAG" "$DIR/$ZIP" --repo "$REPO"

# ── Clean up ──────────────────────────────────────────────────────────────────
rm "$DIR/$ZIP"

echo "  ✓  Asset uploaded to ${TAG}"
echo ""
