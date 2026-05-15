#!/usr/bin/env bash
# Jednorázová instalace GTG na Raspberry Pi.
# Spusť: bash setup.sh
set -euo pipefail

REPO_URL="https://github.com/DeziderMesko/gogtg.git"
REPO_DIR="$HOME/gogtg"

# ── uv ───────────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "Instaluji uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

# ── repozitář ────────────────────────────────────────────────────────────────
if [ -d "$REPO_DIR/.git" ]; then
    echo "Repozitář již existuje: $REPO_DIR"
else
    git clone "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
uv sync

# ── datové adresáře ──────────────────────────────────────────────────────────
mkdir -p data/history

echo ""
echo "Hotovo. Další kroky:"
echo "  1. Nakonfiguruj ngrok token:"
echo "     ngrok config add-authtoken <TVUJ_TOKEN>"
echo "  2. Zkontroluj config.yaml (časové okno, cviky, ntfy topic)"
echo "  3. Spusť aplikaci:"
echo "     $REPO_DIR/scripts/start.sh"
