#!/usr/bin/env python
"""
Zero-Friction Full-Stack Launcher for Scash P2Pool (QtKawaii + Built-in XMRig Edition).
Starts the entire decentralized 3-layer stack automatically:
  1. Updates scash.conf with active community Scash nodes (port 8343) and starts local scashd (:8342 RPC / :8343 P2P).
  2. Starts your local P2Pool Sharechain node (:8344 peer mesh / :8345 Stratum & QtKawaii Web UI).
  3. Opens the QtKawaii Web UI (http://127.0.0.1:8345/static/) where entering your scash1... wallet address
     automatically launches built-in XMRig (rx/scash) against 127.0.0.1:8345!
"""
from __future__ import print_function
import argparse
import os
import platform
import socket
import subprocess
import sys
import time
import webbrowser

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from p2pool import scash_nodes
from p2pool import xmrig_manager


def is_port_open(host, port, timeout=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def find_scashd_binary(custom_bin=None):
    if custom_bin and os.path.isfile(custom_bin):
        return custom_bin
    names = ['scashd.exe', 'scashd', 'scash-qt.exe', 'scash-qt']
    dirs = [
        os.getcwd(),
        os.path.join(os.getcwd(), 'bin'),
        os.path.expanduser('~/.local/bin'),
        '/usr/local/bin',
        '/usr/bin',
    ] + os.environ.get('PATH', '').split(os.pathsep)
    for n in names:
        for d in dirs:
            if not d:
                continue
            cand = os.path.join(d, n)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def ensure_local_scashd(custom_bin=None):
    if is_port_open('127.0.0.1', 8342):
        print("[1/3] Local Scash node is already online on 127.0.0.1:8342.")
        return True
    binary = find_scashd_binary(custom_bin)
    if not binary:
        print("[1/3] Note: scashd/scash-qt not found on PATH. Start your Scash QtKawaii wallet or pass --scashd-bin.")
        return False
    cmd = [binary, "-chain=scash", "-server=1", "-rpcport=8342", "-port=8343"]
    for node in scash_nodes.DEFAULT_SCASH_ADDNODES[:8]:
        cmd.append("-addnode=%s" % node)
    if 'scash-qt' not in os.path.basename(binary).lower() and platform.system() != 'Windows':
        cmd.append("-daemon=1")
    print("[1/3] Starting local Scash node with %d community seed peers..." % len(scash_nodes.DEFAULT_SCASH_ADDNODES))
    subprocess.Popen(cmd)
    for _ in range(30):
        if is_port_open('127.0.0.1', 8342):
            print("      Local Scash node is online (RPC :8342 / P2P :8343).")
            return True
        time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser(description="One-Click Scash P2Pool + Built-in XMRig Launcher")
    parser.add_argument("--wallet", default=None, help="Optional scash1... wallet address (can also be entered in the Web UI)")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads for built-in XMRig (rx/scash)")
    parser.add_argument("--peer", action="append", default=[], help="Additional P2Pool peer address (host:8344)")
    parser.add_argument("--scashd-bin", default=None, help="Path to scashd or scash-qt binary")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    print("==================================================================")
    print("  Scash P2Pool (QtKawaii Edition) + Built-in XMRig (rx/scash)     ")
    print("==================================================================")

    # Step 1: Inject active community nodes into scash.conf & start local scashd
    conf_path = scash_nodes.ensure_scash_conf_with_nodes()
    print("[1/3] Verified scash.conf with community nodes:", conf_path)
    ensure_local_scashd(args.scashd_bin)

    # Step 2: Check saved wallet or CLI wallet for built-in XMRig auto-start
    ctrl = xmrig_manager.GLOBAL_XMRIG
    if args.wallet:
        ctrl.save_wallet_settings(args.wallet, threads=args.threads)
    elif args.threads:
        ctrl.save_wallet_settings(ctrl.wallet, threads=args.threads)

    active_wallet = ctrl.wallet or "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2"
    if ctrl.wallet and ctrl.wallet.lower().startswith(('scash1', 'tcash1')):
        print("[2/3] Auto-starting built-in XMRig (rx/scash) for wallet:", ctrl.wallet)
        ctrl.start_mining(ctrl.wallet, threads=ctrl.threads)
    else:
        print("[2/3] Open the QtKawaii Web UI and paste your scash1... address to auto-start XMRig!")

    ui_url = "http://127.0.0.1:8345/static/"
    print("[3/3] Launching P2Pool node on :8344 (P2P) & :8345 (Local Stratum + QtKawaii UI):", ui_url)
    if not args.no_browser:
        webbrowser.open(ui_url)

    p2pool_cmd = [
        sys.executable, "run_p2pool.py",
        "--net", "scash",
        "--bitcoind-address", "127.0.0.1",
        "--bitcoind-rpc-port", "8342",
        "--bitcoind-p2p-port", "8343",
        "-a", active_wallet
    ]
    for peer in args.peer:
        p2pool_cmd.extend(["-n", peer])

    subprocess.call(p2pool_cmd)


if __name__ == "__main__":
    main()
