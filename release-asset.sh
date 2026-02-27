#!/bin/bash
# release-asset.sh — build and upload the release asset to the matching GitHub release
#
# Run this locally after triggering the release workflow on GitHub:
#   1. Go to Actions → Release → Run workflow
#   2. Once it completes (tag + GitHub Release created), run:
#        ./release-asset.sh
#
# Options:
#   --dry-run   Build and package only, skip upload (zip stays in project dir)

set -euo pipefail

DRY_RUN=false
for arg in "$@"; do
    [[ "$arg" == "--dry-run" ]] && DRY_RUN=true
done

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MediaKeyControl"
REPO="gupfe-priv-dev/apple-mediakey-control"

# ── Target the latest existing GitHub release ────────────────────────────────
TAG=$(gh release list --repo "$REPO" --limit 1 --json tagName --jq '.[0].tagName')
VERSION="${TAG#v}"

# ── Build with that exact version ─────────────────────────────────────────────
VERSION="$VERSION" "$DIR/build.sh"
ZIP="${APP_NAME}-${TAG}.zip"

echo ""
echo "  Packaging ${ZIP}..."

# ── Create zip ────────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
cp -r "$DIR/$APP_NAME.app" "$TMP/"
(cd "$TMP" && zip -r "$DIR/$ZIP" .)
rm -rf "$TMP"

# ── Upload or dry-run ─────────────────────────────────────────────────────────
if $DRY_RUN; then
    echo "  Dry run — zip ready for inspection:"
    echo "  $(cd "$DIR" && pwd)/$ZIP"
    echo ""
    echo "  To upload:  ./release-asset.sh"
    echo ""
else
    echo "  Uploading to GitHub release ${TAG}..."
    if ! gh release view "$TAG" --repo "$REPO" &>/dev/null; then
        echo "  Release ${TAG} not found — creating..."
        gh release create "$TAG" --repo "$REPO" --title "$TAG" --notes ""
    fi
    gh release delete-asset "$TAG" "$ZIP" --repo "$REPO" -y 2>/dev/null || true
    gh release upload "$TAG" "$DIR/$ZIP" --repo "$REPO"
    rm "$DIR/$ZIP"
    echo "  ✓  Asset uploaded to ${TAG}"
    echo ""
fi
