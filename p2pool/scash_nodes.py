"""
Active Community Scash Nodes & Scash Core 30.4.0-Compliant scash.conf Manager.
- Repairs legacy beta config issues (removes unsupported adddnsseed=, Core-30-removed upnp=,
  foreground-breaking daemon=1, unindexed txindex=1, and scopes port/rpcport/rpcbind/addnode
  into both [scash] and [main] sections).
- Injects verified community Scash nodes (port 8343) non-destructively.
- Supports reading both scash.conf rpcuser/rpcpassword and Scash Core .cookie files.
"""
from __future__ import print_function
import os
import platform

DEFAULT_SCASH_ADDNODES = [
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
]

DEFAULT_DNS_SEEDS = [
    "scash.tv",
    "scash.pool-pay.com",
    "satoshicash.cedric-crispin.com",
]

NETWORK_SCOPED_KEYS = ("port", "rpcport", "rpcbind", "addnode", "connect", "seednode", "dnsseed")


def get_scash_datadir():
    sys_name = platform.system()
    if sys_name == "Windows":
        return os.path.join(os.environ.get("APPDATA", ""), "Scash")
    elif sys_name == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Scash")
    return os.path.expanduser("~/.scash")


def _has_existing_txindex(datadir):
    for rel in (
        os.path.join("scash", "indexes", "txindex"),
        os.path.join("indexes", "txindex"),
    ):
        if os.path.isdir(os.path.join(datadir, rel)):
            return True
    return False


def configure_scash_conf(
    custom_datadir=None,
    rpc_user="scashminer",
    rpc_pass="kawaiip2poolpass",
    rpc_port=8342,
    p2p_port=8343,
):
    """
    Repairs or creates a Scash 2.3.0 (Mid-World Core 30.4.0) compliant scash.conf
    and returns (conf_path, effective_rpc_user, effective_rpc_pass, effective_rpc_port).
    """
    datadir = custom_datadir or get_scash_datadir()
    if not os.path.exists(datadir):
        os.makedirs(datadir)
    conf_path = os.path.join(datadir, "scash.conf")

    keep_txindex = _has_existing_txindex(datadir)

    raw_lines = []
    if os.path.exists(conf_path):
        with open(conf_path, "r") as f:
            raw_lines = f.read().splitlines()

    global_lines = []
    scash_section_lines = []
    other_sections = []
    current_section = None

    found_user = None
    found_pass = None
    found_rpcport = None
    found_port = None
    has_chain = False
    has_server = False
    has_rpcallow = False

    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            sec_name = stripped[1:-1].strip().lower()
            if sec_name in ("scash", "main"):
                current_section = "scash"
            else:
                current_section = stripped
                other_sections.append((stripped, []))
            continue

        if stripped.startswith("#"):
            if current_section is None:
                global_lines.append(raw)
            elif current_section == "scash":
                if raw not in scash_section_lines:
                    scash_section_lines.append(raw)
            else:
                other_sections[-1][1].append(raw)
            continue

        key = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else ""
        val = stripped.split("=", 1)[1].strip() if "=" in stripped else ""

        # Strip unsupported adddnsseed, Core-30-removed upnp, process-forking daemon/daemonwait, and unindexed txindex=1
        if key in ("adddnsseed", "daemon", "daemonwait", "upnp"):
            continue
        if key == "txindex" and val == "1" and not keep_txindex:
            continue

        if key == "chain":
            has_chain = True
        elif key == "server" and val == "1":
            has_server = True
        elif key == "rpcuser" and val:
            found_user = val
        elif key == "rpcpassword" and val:
            found_pass = val
        elif key == "rpcallowip":
            has_rpcallow = True
        elif key == "rpcport" and val.isdigit():
            found_rpcport = int(val)
        elif key == "port" and val.isdigit():
            found_port = int(val)

        if current_section is None and key in NETWORK_SCOPED_KEYS:
            if stripped not in scash_section_lines:
                scash_section_lines.append(stripped)
        elif current_section is None:
            global_lines.append(stripped)
        elif current_section == "scash":
            if stripped not in scash_section_lines:
                scash_section_lines.append(stripped)
        else:
            other_sections[-1][1].append(stripped)

    eff_user = found_user or rpc_user
    eff_pass = found_pass or rpc_pass
    eff_rpcport = found_rpcport or int(rpc_port)
    eff_p2pport = found_port or int(p2p_port)

    if not has_chain:
        global_lines.insert(0, "chain=scash")
    if not has_server:
        global_lines.append("server=1")
    if not any(l.startswith("listen=") for l in global_lines):
        global_lines.append("listen=1")
    if not any(l.startswith("maxconnections=") for l in global_lines):
        global_lines.append("maxconnections=64")
    if not found_user:
        global_lines.append("rpcuser=%s" % eff_user)
    if not found_pass:
        global_lines.append("rpcpassword=%s" % eff_pass)
    if not has_rpcallow:
        global_lines.append("rpcallowip=127.0.0.1")

    if not any(l.startswith("rpcport=") for l in scash_section_lines):
        scash_section_lines.insert(0, "rpcport=%d" % eff_rpcport)
    if not any(l.startswith("rpcbind=") for l in scash_section_lines):
        scash_section_lines.insert(1, "rpcbind=127.0.0.1")
    if not any(l.startswith("port=") for l in scash_section_lines):
        scash_section_lines.insert(2, "port=%d" % eff_p2pport)
    if not any(l.startswith("dnsseed=") for l in scash_section_lines):
        scash_section_lines.append("dnsseed=1")

    existing_scash_blob = "\n".join(scash_section_lines)
    for node in DEFAULT_SCASH_ADDNODES:
        if node not in existing_scash_blob:
            scash_section_lines.append("addnode=%s" % node)

    out_lines = (
        list(global_lines)
        + ["", "[scash]"]
        + list(scash_section_lines)
        + ["", "[main]"]
        + list(scash_section_lines)
    )
    for sec_hdr, sec_body in other_sections:
        out_lines.extend(["", sec_hdr] + sec_body)

    new_text = "\n".join(out_lines) + "\n"
    old_text = "\n".join(raw_lines) + ("\n" if raw_lines else "")
    if new_text != old_text:
        with open(conf_path, "w") as f:
            f.write(new_text)

    return conf_path, eff_user, eff_pass, eff_rpcport


def ensure_scash_conf_with_nodes(custom_datadir=None, rpc_user="scashminer", rpc_pass="kawaiip2poolpass"):
    conf_path, _, _, _ = configure_scash_conf(
        custom_datadir=custom_datadir, rpc_user=rpc_user, rpc_pass=rpc_pass
    )
    return conf_path


def read_cookie_credentials(datadir=None):
    base = datadir or get_scash_datadir()
    for rel in (os.path.join("scash", ".cookie"), ".cookie"):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            try:
                raw = open(p, "r").read().strip()
                if ":" in raw:
                    u, pw = raw.split(":", 1)
                    return u, pw
            except Exception:
                pass
    return None, None
