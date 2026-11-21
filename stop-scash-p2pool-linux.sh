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
if command -v fuser >/dev/null 2>&1; then
    fuser -k 8345/tcp >/dev/null 2>&1 || true
    if ! pgrep -x scash-qt >/dev/null 2>&1; then
        fuser -k 8344/tcp >/dev/null 2>&1 || true
    fi
fi
if [ "$(id -u)" -ne 0 ] && command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -Eq ':(8344|8345)'; then
    echo "Port 8344/8345 is held by a previous sudo/root P2Pool process -- clearing with sudo..."
    sudo sh -c "pkill -9 -f 'run_p2pool.py|start_scash_p2pool.py' 2>/dev/null || true; fuser -k 8344/tcp 8345/tcp 2>/dev/null || true"
fi
echo "Done! All headless Scash P2Pool processes are stopped."
