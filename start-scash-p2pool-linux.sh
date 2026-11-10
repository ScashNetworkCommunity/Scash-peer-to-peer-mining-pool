#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "=================================================================="
echo "  Scash Peer-to-Peer Mining Pool (Standalone Linux x64 Runtime)"
echo "=================================================================="
if [ -x "./runtime/pypy2/bin/pypy" ]; then
    ./runtime/pypy2/bin/pypy start_scash_p2pool.py "$@"
else
    python start_scash_p2pool.py "$@"
fi
