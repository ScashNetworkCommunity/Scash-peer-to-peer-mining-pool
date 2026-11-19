#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Stopping Scash P2Pool background worker and headless scashd node..."
pkill -f "start_scash_p2pool.py" 2>/dev/null || true
pkill -f "run_p2pool.py" 2>/dev/null || true
pkill -x "xmrigDaemon" 2>/dev/null || true
pkill -x "xmrigMiner" 2>/dev/null || true
if [ -x "$DIR/node/scash-cli" ]; then
    "$DIR/node/scash-cli" -chain=scash -rpcport=8342 stop >/dev/null 2>&1 || true
    sleep 3
fi
pkill -f "$DIR/node/scashd" 2>/dev/null || true
echo "Done! All headless Scash P2Pool processes are stopped."
