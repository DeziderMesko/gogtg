#!/usr/bin/env bash
# Stáhne novou verzi a restartuje aplikaci.
# Použití: ./scripts/update.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "Stahuji aktualizace..."
git pull

echo "Synchronizuji závislosti..."
uv sync

# restart jen pokud aplikace běžela
if pkill -f "gtg.scheduler" 2>/dev/null; then
    echo "Aplikace zastavena. Spouštím znovu..."
    nohup ./scripts/start.sh >/tmp/gtg-app.log 2>&1 &
    echo "Spuštěno na pozadí. Log: /tmp/gtg-app.log"
else
    echo "Aplikace nebyla spuštěna. Spusť ji ručně: ./scripts/start.sh"
fi
