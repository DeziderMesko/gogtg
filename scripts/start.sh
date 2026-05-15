#!/usr/bin/env bash
# Spustí ngrok + GTG scheduler.
# Ponechá běžet v popředí — pro na pozadí použij: nohup ./scripts/start.sh &
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${GTG_PORT:-8765}"
NTFY_LOG="/tmp/ngrok-gtg.log"
PIDFILE="/tmp/gtg-ngrok.pid"

cd "$REPO_DIR"

# ── zastav předchozí instance ────────────────────────────────────────────────
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Zastavuji běžící ngrok (PID $(cat "$PIDFILE"))..."
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
fi
pkill -f "gtg.scheduler" 2>/dev/null || true
sleep 1

# ── ngrok ────────────────────────────────────────────────────────────────────
echo "Spouštím ngrok na portu $PORT..."
ngrok http "$PORT" --log=stdout >"$NTFY_LOG" 2>&1 &
echo $! >"$PIDFILE"

# počkej až ngrok naběhne (max 15 s)
NGROK_URL=""
for i in $(seq 1 15); do
    NGROK_URL=$(curl -sf http://localhost:4040/api/tunnels 2>/dev/null \
        | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(next(u['public_url'] for u in t if u['public_url'].startswith('https')))" \
        2>/dev/null) && break
    sleep 1
done

if [ -z "$NGROK_URL" ]; then
    echo "CHYBA: ngrok nenaběhl. Zkontroluj log: $NTFY_LOG" >&2
    exit 1
fi
echo "ngrok URL: $NGROK_URL"

# ── ověř ntfy ────────────────────────────────────────────────────────────────
NTFY_BASE=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['ntfy']['base_url'])")
NTFY_TOPIC=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['ntfy']['topic'])")
NTFY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$NTFY_BASE/$NTFY_TOPIC/json?poll=1" || true)
if [ "$NTFY_STATUS" = "200" ]; then
    echo "ntfy OK  ($NTFY_BASE/$NTFY_TOPIC)"
else
    echo "VAROVÁNÍ: ntfy status $NTFY_STATUS — notifikace nemusí fungovat"
fi

# ── spusť aplikaci ───────────────────────────────────────────────────────────
echo "Spouštím GTG scheduler..."
GTG_CALLBACK_URL="$NGROK_URL" uv run python -m gtg.scheduler
