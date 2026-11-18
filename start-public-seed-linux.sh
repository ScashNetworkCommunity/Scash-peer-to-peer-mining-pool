#!/usr/bin/env bash
# 1-Command Headless Public Bootstrap Seed Node Launcher for Scash P2Pool (v0.3.2)
# Usage:
#   ./start-public-seed-linux.sh              # Starts in background -> seed-p2pool.log
#   ./start-public-seed-linux.sh --foreground # Runs in foreground (for systemd)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -x "$DIR/runtime/pypy2/bin/pypy" ]; then
  PY_BIN="$DIR/runtime/pypy2/bin/pypy"
elif command -v pypy >/dev/null 2>&1; then
  PY_BIN="pypy"
else
  PY_BIN="python3"
fi

echo "=================================================================="
echo " Scash P2Pool v0.3.2 — Public Bootstrap & Mesh Seed Node (:8344)"
echo " Reminder: Open inbound TCP 8344 & UDP 8344 on firewall/router:"
echo "   sudo ufw allow 8344/tcp && sudo ufw allow 8344/udp"
echo " (Keep port 8345 private on 127.0.0.1 or behind read-only Apache!)"
echo "=================================================================="

if [ "${1:-}" = "--foreground" ]; then
  shift
  exec "$PY_BIN" "$DIR/start_scash_p2pool.py" --no-browser --no-banner "$@" -- --max-conns 120 --outgoing-conns 16
fi

nohup "$PY_BIN" "$DIR/start_scash_p2pool.py" --no-browser --no-banner "$@" -- --max-conns 120 --outgoing-conns 16 > "$DIR/seed-p2pool.log" 2>&1 &
SEED_PID=$!
echo "$SEED_PID" > "$DIR/seed-p2pool.pid"
echo "[OK] Scash P2Pool Seed Node started in background (PID: $SEED_PID)"
echo "     Live logs : tail -f $DIR/seed-p2pool.log"
echo "     Stop node : ./stop-scash-p2pool-linux.sh"
