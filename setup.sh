#!/bin/bash
# setup.sh — install build dependencies on macOS
#
# Usage:
#   ./setup.sh

set -euo pipefail

echo ""
echo "  Setting up MediaKeyControl build dependencies..."
echo ""

# ── Xcode Command Line Tools ───────────────────────────────────────────────────
if xcode-select -p &>/dev/null; then
    echo "  [1/3] Xcode Command Line Tools ✓"
else
    echo "  [1/3] Installing Xcode Command Line Tools..."
    echo "        (follow the system prompt, then re-run this script)"
    xcode-select --install
    exit 0
fi

# ── Homebrew ───────────────────────────────────────────────────────────────────
if command -v brew &>/dev/null; then
    echo "  [2/3] Homebrew ✓"
else
    echo "  [2/3] Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi

# ── Python 3 ──────────────────────────────────────────────────────────────────
PYTHON=$(command -v python3 2>/dev/null \
      || echo "/usr/bin/python3")

if "$PYTHON" --version &>/dev/null; then
    echo "  [3/3] Python 3 ($("$PYTHON" --version)) ✓"
else
    echo "  [3/3] Installing Python 3..."
    brew install python3
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ✓  All dependencies ready."
echo ""
echo "  Build:    ./build.sh"
echo "  Install:  ./install.sh"
echo ""
