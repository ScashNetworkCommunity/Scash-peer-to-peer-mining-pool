#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
export LD_LIBRARY_PATH="$DIR:$DIR/node/lib:$DIR/miner/lib:${LD_LIBRARY_PATH:-}"
if [ -x "$DIR/runtime/pypy2/bin/pypy" ]; then
    exec "$DIR/runtime/pypy2/bin/pypy" "$DIR/start_scash_p2pool.py" "$@"
elif command -v pypy >/dev/null 2>&1; then
    exec pypy "$DIR/start_scash_p2pool.py" "$@"
else
    exec python "$DIR/start_scash_p2pool.py" "$@"
fi
