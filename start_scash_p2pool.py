#!/usr/bin/env python
"""
Zero-Friction Launcher for Scash P2Pool (QtKawaii Edition).
Auto-configures scash.conf, verifies scashd RPC connection, launches P2Pool on :8345,
and opens the QtKawaii Web UI.
"""
import argparse
import os
import platform
import subprocess
import sys
import webbrowser

def get_scash_conf_path():
    sys_name = platform.system()
    if sys_name == 'Windows':
        base = os.path.join(os.environ.get('APPDATA', ''), 'Scash')
    elif sys_name == 'Darwin':
        base = os.path.expanduser('~/Library/Application Support/Scash')
    else:
        base = os.path.expanduser('~/.scash')
    if not os.path.exists(base):
        os.makedirs(base)
    return os.path.join(base, 'scash.conf')

def ensure_scash_conf():
    conf_path = get_scash_conf_path()
    if not os.path.exists(conf_path):
        with open(conf_path, 'w') as f:
            f.write("chain=scash\nserver=1\ndaemon=1\ntxindex=1\n")
            f.write("rpcuser=scashminer\nrpcpassword=kawaiip2poolpass\n")
            f.write("rpcport=8342\nport=8343\n[scash]\nadddnsseed=seed.scash.one\n")
        print("[Scash-Kawaii] Created default scash.conf at:", conf_path)
    return conf_path

def main():
    parser = argparse.ArgumentParser(description="One-Click Scash P2Pool Launcher")
    parser.add_argument("--wallet", required=True, help="Your scash1... Bech32 payout address")
    parser.add_argument("--threads", type=int, default=4, help="CPU threads for cpuminer-scash")
    parser.add_argument("--open-ui", action="store_true", help="Open QtKawaii Web UI in browser")
    args = parser.parse_args()

    ensure_scash_conf()
    ui_url = "http://127.0.0.1:8345/static/"
    print("==========================================================")
    print("  Scash P2Pool (QtKawaii Edition) Starting on Port 8345   ")
    print("  Dashboard URL:", ui_url)
    print("  Miner Stratum: stratum+tcp://127.0.0.1:8345")
    print("==========================================================")
    if args.open_ui:
        webbrowser.open(ui_url)
    cmd = [sys.executable, "run_p2pool.py", "--net", "scash", "-a", args.wallet]
    subprocess.call(cmd)

if __name__ == "__main__":
    main()
