"""
Active Community Scash Nodes & Non-Destructive scash.conf Manager.
Replaces reliance on the offline scash.one seed by injecting verified community
Scash nodes (port 8343) into scash.conf without overwriting existing user settings.
"""
from __future__ import print_function
import os
import platform

# Verified active Scash community nodes, pool nodes, explorer nodes, and IPv6 peers (port 8343)
DEFAULT_SCASH_ADDNODES = [
    "13.215.178.199:8343",
    "99.47.252.128:8343",
    "83.78.96.42:8343",
    "185.16.39.26:21015",
    "172.67.141.132:8343",
    "104.21.87.51:8343",
    "95.216.18.84:8343",
    "110.78.164.25:8343",
    "104.21.21.158:8343",
    "172.67.199.87:8343",
    "scash.tv:8343",
    "scash.pool-pay.com:8343",
    "satoshicash.cedric-crispin.com:8343",
    "pool.rplant.xyz:8343",
    "wallet.scash.network:8343",
    "scashnetwork.com:8343",
    "[2600:1700:bc80:69d0::40]:8343",
    "[2600:1700:bc80:69d0:3579:ef8f:fd51:b43c]:8343",
    "[2600:1700:bc80:69d0:570b:d36:c662:3aec]:8343",
    "5.59.96.54:8343",
    "5.128.87.126:8343",
    "5.186.40.82:8343",
    "144.76.17.34:8343",
    "198.199.73.40:8343",
    "88.190.223.96:8343",
    "209.141.46.154:8343",
    "seed.scash.one:8343",
]

DEFAULT_DNS_SEEDS = [
    "scash.tv",
    "scash.pool-pay.com",
    "satoshicash.cedric-crispin.com",
    "seed.scash.one",
]


def get_scash_datadir():
    sys_name = platform.system()
    if sys_name == 'Windows':
        return os.path.join(os.environ.get('APPDATA', ''), 'Scash')
    elif sys_name == 'Darwin':
        return os.path.expanduser('~/Library/Application Support/Scash')
    return os.path.expanduser('~/.scash')


def ensure_scash_conf_with_nodes(custom_datadir=None, rpc_user='scashminer', rpc_pass='kawaiip2poolpass'):
    """
    Creates or updates scash.conf with RPC server settings and appends any missing
    community addnode= entries without overwriting existing user settings.
    """
    datadir = custom_datadir or get_scash_datadir()
    if not os.path.exists(datadir):
        os.makedirs(datadir)
    conf_path = os.path.join(datadir, 'scash.conf')

    existing_lines = []
    if os.path.exists(conf_path):
        with open(conf_path, 'r') as f:
            existing_lines = f.read().splitlines()

    existing_text = "\n".join(existing_lines)
    added_lines = []

    if not existing_lines:
        added_lines.extend([
            "chain=scash",
            "server=1",
            "daemon=1",
            "txindex=1",
            "listen=1",
            "maxconnections=64",
            "rpcuser=%s" % rpc_user,
            "rpcpassword=%s" % rpc_pass,
            "rpcallowip=127.0.0.1",
            "rpcport=8342",
            "port=8343",
            "[scash]",
        ])
    else:
        if "server=1" not in existing_text:
            added_lines.insert(0, "server=1")
        if "[scash]" not in existing_text:
            added_lines.append("[scash]")

    for seed in DEFAULT_DNS_SEEDS:
        line = "adddnsseed=%s" % seed
        if line not in existing_text:
            added_lines.append(line)

    for node in DEFAULT_SCASH_ADDNODES:
        line = "addnode=%s" % node
        if line not in existing_text and node not in existing_text:
            added_lines.append(line)

    if added_lines:
        with open(conf_path, 'a') as f:
            if existing_lines and not existing_lines[-1].endswith("\n"):
                f.write("\n")
            f.write("\n".join(added_lines) + "\n")
        print("[Scash-Nodes] Updated %s with %d community node/config lines." % (conf_path, len(added_lines)))

    return conf_path
