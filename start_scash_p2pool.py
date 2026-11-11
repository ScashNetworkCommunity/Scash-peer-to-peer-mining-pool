#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.2.0-beta.4).
Publisher: magicalgirlsunite | Community: ScashNetworkCommunity
Compatible with BOTH PyPy 2.7 (bundled runtime) and Python 3.x!
"""
from __future__ import print_function
import argparse
import atexit
import base64
import ctypes
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import webbrowser

try:
    import urllib.request as urllib_req
    import urllib.error as urllib_err
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
except ImportError:
    import urllib2 as urllib_req
    import urllib2 as urllib_err
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from urlparse import urlparse, parse_qs

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, ROOT_DIR)
from p2pool import scash_nodes
from p2pool import xmrig_manager

_NO_PROXY_OPENER = urllib_req.build_opener(urllib_req.ProxyHandler({}))


def _enable_ansi_colors():
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if platform.system() == "Windows":
        try:
            k32 = ctypes.windll.kernel32
            h_out = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(h_out, ctypes.byref(mode)):
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                if k32.SetConsoleMode(h_out, mode.value | 0x0004):
                    return True
        except Exception:
            pass
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON"))
    return os.environ.get("TERM", "") != "dumb"


def render_kawaii_ascii_banner(use_color=False):
    """
    Renders the Scash QtKawaii Anime Catgirl Mascot holding her glowing `[ S c a s h ]`
    pixel sign in 100% 7-bit ASCII (<= 75 cols wide so it never wraps on 80-col cmd.exe),
    compatible with both PyPy 2.7 and Python 3.x!
    """
    c = {
        "r": "\033[0m" if use_color else "",
        "c": "\033[96m" if use_color else "",   # Cosmic cyan stars & frame
        "p": "\033[95m" if use_color else "",   # Neon magenta/lavender ($ flower & Scash sign)
        "y": "\033[93m" if use_color else "",   # Twinkling gold stars & dress trim
        "g": "\033[92m" if use_color else "",   # Mascot's emerald green anime eyes
        "b": "\033[91m" if use_color else "",   # Rosy cheek blush & ribbon bow
        "h": "\033[94m" if use_color else "",   # Deep cosmic indigo hair & cat ears
        "w": "\033[97m" if use_color else "",   # Bright white pixel lettering
    }
    templates = [
        "   {y}*{r}  {c}.{r}     {h}/\\{r}   {p}*{r}   {h}/\\{r}     {c}.{r}  {y}*{r}       {p}+{r}   {c}*{r}   {y}.{r}   {p}+{r}   {c}*{r}   {y}.{r}   {p}+{r}   {c}*{r}",
        "     {p}+{r}    {h}//^{r} {h}\\_____/{r} {h}^\\\\{r}        {c}+{r}  {c}.----------------------------------.{r}",
        "   {c}.{r}     {h}//{r} {p}($){r}{h}/   \\{r} {p}*{r}  {h}\\\\{r}    {y}*{r}     {c}|{r}  {y}*{r}   {w}S C A S H   P 2 P O O L{r}  {y}*{r}  {c}|{r}",
        "      {y}*{r} {h}||   /|{r}{g}o   o{r}{h}|\\   ||{r}  {c}.{r}   {p}+{r}  {c}|{r}   {p}QtKawaii Edition v0.2.0-beta.4{r} {c}|{r}",
        "    {p}+{r}   {h}||   |{r}({b}\"{r} v {b}\"{r}){h}|   ||{r}    {y}*{r}    {c}'----------------------------------'{r}",
        "   {c}.{r}    {h}||   \\{r} `---' {h}/   ||{r}  {p}+{r}    {c}*{r}    {p}+==================+{r}   {y}*{r}  {c}.{r}",
        "      {y}*{r}  {h}\\\\  /{r}`-{b}><{r}--'{h}\\  //{r} {c}.{r}    {c}+{r}      {p}| {c}*{r} {w}[ S c a s h ]{r}  {p}|{r}  {p}+{r}     {y}*{r}",
        "    {p}+{r}    {h}/ \\/{r}  {y}/   \\{r}  {h}\\/ \\{r}    {y}*{r}   ___  {p}+==================+{r}    {c}.{r}",
        "   {c}.{r}    {h}/  /{r}  {y}/     \\{r}  {h}\\  \\{r}______/ _/   {c}Publisher{r} : {w}magicalgirlsunite{r}",
        "      {y}*{r} {h}`--'{r} {y}/~{p}*{y}~{c}*{y}~{p}*{y}~\\{r}  {h}`---------'{r}     {c}Community{r} : {w}ScashNetworkCommunity{r}",
        "   {c}.{r}   {p}+{r}    {y}`---------'{r}   {y}*{r}   {c}.{r}         {c}Node Core{r} : {w}Scash 2.3.0 (Core 30.4){r}",
        "  {c}========================================================================={r}",
    ]
    return "\n".join([t.format(**c) for t in templates])


def print_kawaii_ascii_banner():
    print(render_kawaii_ascii_banner(use_color=_enable_ansi_colors()))
    print("")


def is_port_open(host, port, timeout=1.2):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        s.close()
        return True
    except Exception:
        return False


def jsonrpc_call(host, port, user, password, method, params=None, timeout=5.0):
    url = "http://%s:%d/" % (host, int(port))
    payload = json.dumps({
        "jsonrpc": "1.0",
        "id": "scash-launcher",
        "method": method,
        "params": params or [],
    }).encode("utf-8")
    auth_raw = ("%s:%s" % (user, password)).encode("utf-8")
    auth_hdr = "Basic " + base64.b64encode(auth_raw).decode("ascii")
    req = urllib_req.Request(url, payload, {
        "Content-Type": "application/json",
        "Authorization": auth_hdr,
    })
    try:
        resp = _NO_PROXY_OPENER.open(req, timeout=timeout)
        body = json.loads(resp.read().decode("utf-8", "replace"))
        if body.get("error") is not None:
            return False, None, body.get("error")
        return True, body.get("result"), None
    except urllib_err.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8", "replace"))
            err_obj = err_body.get("error") or {"code": e.code, "message": str(e)}
            return False, None, err_obj
        except Exception:
            return False, None, {"code": e.code, "message": str(e)}
    except Exception as e:
        return False, None, {"code": -999, "message": str(e)}


def is_mainnet_node_synced(bc_info, net_info=None, allow_unsynced=False):
    if not isinstance(bc_info, dict):
        return False
    if allow_unsynced:
        return True
    chain = bc_info.get("chain", "scash")
    blks = int(bc_info.get("blocks", 0))
    hdrs = int(bc_info.get("headers", 0))
    ibd = bool(bc_info.get("initialblockdownload", True))
    peers = int((net_info or {}).get("connections", 0)) if isinstance(net_info, dict) else 0

    if chain in ("scash", "main"):
        if hdrs <= 0 or blks <= 0:
            return False
        if ibd:
            return False
        if blks < hdrs - 1:
            return False
        if peers <= 0 and blks < 100000:
            return False
        return True

    return (not ibd) and blks >= hdrs


def probe_working_credentials(host, port, datadirs, conf_user, conf_pass):
    candidates = [(conf_user, conf_pass)]
    for dd in datadirs:
        cu, cp = scash_nodes.read_cookie_credentials(dd)
        if cu and cp and (cu, cp) not in candidates:
            candidates.insert(0, (cu, cp))
    for u, pw in candidates:
        ok, res, err = jsonrpc_call(host, port, u, pw, "getblockchaininfo", timeout=3.0)
        if ok or (err and err.get("code") not in (401, 403, -999)):
            return u, pw, ok, res, err
    return conf_user, conf_pass, False, None, {"code": -999, "message": "RPC unreachable"}


def find_scashd_binary(custom_bin=None):
    if custom_bin and os.path.isfile(custom_bin):
        return os.path.abspath(custom_bin)
    is_win = platform.system() == "Windows"
    daemon_names = ["scashd.exe"] if is_win else ["scashd"]
    search_dirs = [
        os.path.join(ROOT_DIR, "node"),
        os.path.join(ROOT_DIR, "bin"),
        ROOT_DIR,
    ]
    if is_win:
        for env_k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_k, "")
            if base:
                search_dirs.append(os.path.join(base, "Scash", "daemon"))
                search_dirs.append(os.path.join(base, "Scash"))
    else:
        search_dirs.extend([
            os.path.expanduser("~/.local/bin"),
            "/usr/local/bin",
            "/usr/bin",
        ])
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p:
            search_dirs.append(p)

    for name in daemon_names:
        for d in search_dirs:
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return os.path.abspath(cand)
    return None


def start_bundled_scashd(scashd_bin, datadir, rpc_port=8342):
    cmd = [
        scashd_bin,
        "-datadir=%s" % datadir,
        "-chain=scash",
        "-server=1",
        "-listen=1",
        "-dnsseed=1",
        "-rpcport=%d" % int(rpc_port),
        "-rpcbind=127.0.0.1",
        "-rpcallowip=127.0.0.1",
    ]
    for peer in scash_nodes.DEFAULT_SCASH_ADDNODES[:8]:
        cmd.append("-addnode=%s" % peer)
    if platform.system() != "Windows":
        cmd.append("-daemon=0")
    kwargs = {}
    if platform.system() == "Windows":
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NO_WINDOW
    devnull = open(os.devnull, "wb")
    kwargs["stdout"] = devnull
    kwargs["stderr"] = devnull
    return subprocess.Popen(cmd, **kwargs)


def kick_peer_connections(host, port, user, pw):
    for peer in scash_nodes.DEFAULT_SCASH_ADDNODES:
        jsonrpc_call(host, port, user, pw, "addnode", [peer, "add"], timeout=1.5)
        jsonrpc_call(host, port, user, pw, "addnode", [peer, "onetry"], timeout=1.5)


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def make_sync_handler(sync_state, ctrl):
    web_static_dir = os.path.join(ROOT_DIR, "web-static")

    class SyncHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send_json(self, obj, code=200):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/":
                self.send_response(302)
                self.send_header("Location", "/static/")
                self.end_headers()
                return

            if path in ("/node_sync_status", "/local_stats"):
                self._send_json(sync_state)
                return

            if path == "/miner_status":
                st = ctrl.get_status()
                st["node_syncing"] = True
                self._send_json(st)
                return

            if path == "/miner_start":
                w = qs.get("wallet", [None])[0]
                t = qs.get("threads", [None])[0]
                wk = qs.get("worker", [None])[0]
                ctrl.save_wallet_settings(w or ctrl.wallet, threads=t, worker=wk)
                st = ctrl.get_status()
                st["running"] = False
                st["queued_after_sync"] = True
                st["node_syncing"] = True
                self._send_json(st)
                return

            if path == "/miner_stop":
                self._send_json(ctrl.stop_mining())
                return

            if path == "/nodes_list":
                self._send_json({
                    "addnodes": scash_nodes.DEFAULT_SCASH_ADDNODES,
                    "dns_seeds": scash_nodes.DEFAULT_DNS_SEEDS,
                })
                return

            if path.startswith("/static"):
                rel = path[len("/static"):].lstrip("/") or "index.html"
                fp = os.path.abspath(os.path.join(web_static_dir, rel))
                if fp.startswith(os.path.abspath(web_static_dir)) and os.path.isfile(fp):
                    ext = os.path.splitext(fp)[1].lower()
                    ctype = "text/html; charset=utf-8"
                    if ext == ".js":
                        ctype = "application/javascript"
                    elif ext == ".css":
                        ctype = "text/css"
                    elif ext == ".svg":
                        ctype = "image/svg+xml"
                    elif ext == ".png":
                        ctype = "image/png"
                    raw = open(fp, "rb").read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

            self.send_response(404)
            self.end_headers()

    return SyncHTTPHandler


def main():
    parser = argparse.ArgumentParser(description="One-Click Scash Node + P2Pool + Launcher")
    parser.add_argument("--wallet", default=None, help="Optional scash1... wallet address")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads for local mining")
    parser.add_argument("--peer", action="append", default=[], help="Additional P2Pool peer address (host:8344)")
    parser.add_argument("--scashd-bin", default=None, help="Custom path to scashd binary")
    parser.add_argument("--datadir", default=None, help="Custom Scash Core data directory")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--allow-unsynced", action="store_true", help="Start P2Pool without waiting for Mainnet block sync")
    args, unknown = parser.parse_known_args()

    print_kawaii_ascii_banner()

    ctrl = xmrig_manager.GLOBAL_XMRIG
    if args.wallet:
        ctrl.save_wallet_settings(args.wallet, threads=args.threads)
    elif args.threads:
        ctrl.save_wallet_settings(ctrl.wallet, threads=args.threads)

    primary_datadir = args.datadir or scash_nodes.get_scash_datadir()
    conf_path, rpc_user, rpc_pass, rpc_port = scash_nodes.configure_scash_conf(custom_datadir=primary_datadir)
    print("[1/3] Configured scash.conf with active Scash peers:", conf_path)

    active_datadir = primary_datadir
    spawned_proc = [None]
    active_creds = [rpc_user, rpc_pass, rpc_port]

    def _cleanup_scashd():
        if spawned_proc[0] is not None and spawned_proc[0].poll() is None:
            print("\n[Shutdown] Stopping bundled Scash Core 30.4 node cleanly...")
            jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "stop", timeout=3.0)
            for _ in range(15):
                if spawned_proc[0].poll() is not None:
                    break
                time.sleep(0.5)

    atexit.register(_cleanup_scashd)

    u, pw, ok, info, err = probe_working_credentials(
        "127.0.0.1", rpc_port, [primary_datadir], rpc_user, rpc_pass
    )
    if ok or (err and err.get("code") != -999):
        active_creds[0], active_creds[1] = u, pw
        print("[1/3] Connected to running local Scash node on 127.0.0.1:%d." % rpc_port)
    else:
        scashd_bin = find_scashd_binary(args.scashd_bin)
        if not scashd_bin:
            print("[ERROR] Bundled scashd binary not found and 127.0.0.1:%d is offline." % rpc_port)
            sys.exit(1)

        print("[1/3] Spinning up bundled local Scash Core 30.4 node (%s)..." % os.path.basename(scashd_bin))
        proc = start_bundled_scashd(scashd_bin, active_datadir, active_creds[2])
        spawned_proc[0] = proc

        connected = False
        used_fallback = False
        for _ in range(120):
            if proc.poll() is not None and not used_fallback:
                used_fallback = True
                fallback_dd = os.path.join(ROOT_DIR, "node_data")
                print("[1/3] Notice: Default Scash folder is in use by another wallet window.")
                print("      Spinning up dedicated P2Pool Scash node in:", fallback_dd)
                active_datadir = fallback_dd
                _, rpc_user, rpc_pass, rpc_port = scash_nodes.configure_scash_conf(custom_datadir=active_datadir)
                active_creds = [rpc_user, rpc_pass, rpc_port]
                proc = start_bundled_scashd(scashd_bin, active_datadir, active_creds[2])
                spawned_proc[0] = proc
                time.sleep(1.5)
            u, pw, ok, info, err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir, primary_datadir], active_creds[0], active_creds[1]
            )
            if ok or (err and err.get("code") != -999):
                active_creds[0], active_creds[1] = u, pw
                connected = True
                break
            time.sleep(0.5)

        if not connected:
            print("[ERROR] Local Scash node did not open RPC port 127.0.0.1:%d." % active_creds[2])
            print("        Check debug.log in:", active_datadir)
            sys.exit(1)

    ui_url = "http://127.0.0.1:8345/static/"
    browser_opened = [False]

    _, init_bc, _ = jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "getblockchaininfo", timeout=4.0)
    _, init_net, _ = jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "getnetworkinfo", timeout=4.0)
    already_synced = is_mainnet_node_synced(init_bc, init_net, allow_unsynced=args.allow_unsynced)
    if already_synced:
        gbt_ok, gbt_res, _ = jsonrpc_call(
            "127.0.0.1", active_creds[2], active_creds[0], active_creds[1],
            "getblocktemplate", [{"mode": "template", "rules": ["segwit"]}], timeout=5.0
        )
        already_synced = bool(gbt_ok and isinstance(gbt_res, dict))

    if not already_synced:
        sync_state = {
            "syncing": True,
            "blocks": 0,
            "headers": 0,
            "progress_pct": 0.0,
            "connections": 0,
            "status_text": "Connecting to Scash Mainnet peers on :8343...",
        }
        sync_srv = None
        try:
            sync_srv = _ReusableHTTPServer(("127.0.0.1", 8345), make_sync_handler(sync_state, ctrl))
            srv_thread = threading.Thread(target=sync_srv.serve_forever)
            srv_thread.daemon = True
            srv_thread.start()
            print("[2/3] QtKawaii Sync Dashboard live at:", ui_url)
            if not args.no_browser:
                webbrowser.open(ui_url)
                browser_opened[0] = True
        except Exception as e:
            print("[2/3] Note: Port 8345 busy during sync check:", e)

        print("      Waiting for local Scash node to finish syncing before starting P2Pool sharechain...")
        last_kick = 0.0
        synced_height = 0
        while True:
            u, pw, bc_ok, bc_info, bc_err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir, primary_datadir], active_creds[0], active_creds[1]
            )
            active_creds[0], active_creds[1] = u, pw
            _, net_info, _ = jsonrpc_call(
                "127.0.0.1", active_creds[2], u, pw, "getnetworkinfo", timeout=3.0
            )
            peers = (net_info or {}).get("connections", 0) if isinstance(net_info, dict) else 0

            if peers == 0 and (time.time() - last_kick) >= 15.0:
                last_kick = time.time()
                t_kick = threading.Thread(target=kick_peer_connections, args=("127.0.0.1", active_creds[2], u, pw))
                t_kick.daemon = True
                t_kick.start()

            if bc_ok and isinstance(bc_info, dict):
                blks = int(bc_info.get("blocks", 0))
                hdrs = int(bc_info.get("headers", 0))
                pct = round((100.0 * blks / hdrs), 1) if hdrs > 0 else 0.0
                if hdrs == 0 and peers == 0:
                    msg = "Connecting to Scash Mainnet peers on :8343... (Peers: 0 — discovering network headers)"
                elif hdrs == 0:
                    msg = "Connected to %d Scash peer(s) — downloading block headers..." % peers
                else:
                    msg = "Syncing Scash blockchain: %d / %d blocks (%.1f%%) | Peers: %d" % (blks, hdrs, pct, peers)
                sync_state.update({
                    "syncing": True,
                    "blocks": blks,
                    "headers": hdrs,
                    "progress_pct": pct,
                    "connections": peers,
                    "status_text": msg,
                })
                print("      [Scash Node]", msg)
                if is_mainnet_node_synced(bc_info, net_info, allow_unsynced=args.allow_unsynced):
                    gbt_ok2, gbt_res2, _ = jsonrpc_call(
                        "127.0.0.1", active_creds[2], u, pw,
                        "getblocktemplate", [{"mode": "template", "rules": ["segwit"]}], timeout=5.0
                    )
                    if gbt_ok2 and isinstance(gbt_res2, dict):
                        synced_height = blks
                        break
            else:
                warm_msg = (bc_err or {}).get("message", "Starting Scash node...")
                sync_state["status_text"] = "Scash node warming up: %s" % warm_msg
                print("      [Scash Node] Warming up:", warm_msg)

            time.sleep(5)

        if sync_srv is not None:
            sync_srv.shutdown()
            sync_srv.server_close()
            time.sleep(0.4)
        print("[2/3] Local Scash node is synced at block #%d and serving SegWit block templates!" % synced_height)
    else:
        print("[2/3] Local Scash node is already synced at block #%d!" % int((init_bc or {}).get("blocks", 0)))

    ctrl._load_saved_wallet()
    active_wallet = ctrl.wallet or "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2"

    def _post_p2pool_ready():
        for _ in range(45):
            if is_port_open("127.0.0.1", 8345):
                if (not args.no_browser) and (not browser_opened[0]):
                    webbrowser.open(ui_url)
                    browser_opened[0] = True
                if ctrl.wallet and ctrl.wallet.lower().startswith(("scash1", "tcash1")):
                    try:
                        start_url = "http://127.0.0.1:8345/miner_start?wallet=%s&threads=%d" % (
                            ctrl.wallet, int(ctrl.threads)
                        )
                        _NO_PROXY_OPENER.open(start_url, timeout=5.0).read()
                        print("[3/3] Auto-started local worker on 127.0.0.1:8345 for:", ctrl.wallet)
                    except Exception as e:
                        print("[3/3] Note: Start worker from Web UI (%s)" % e)
                break
            time.sleep(1.0)

    t_ready = threading.Thread(target=_post_p2pool_ready)
    t_ready.daemon = True
    t_ready.start()

    print("[3/3] Launching Scash P2Pool Sharechain Node on :8344 (P2P) & :8345 (Stratum + QtKawaii UI)...")
    p2pool_cmd = [
        sys.executable,
        os.path.join(ROOT_DIR, "run_p2pool.py"),
        "--net", "scash",
        "--disable-upnp",
        "--bitcoind-address", "127.0.0.1",
        "--bitcoind-rpc-port", str(active_creds[2]),
        "--bitcoind-p2p-port", "8343",
        "-a", active_wallet,
    ]
    for peer in args.peer:
        p2pool_cmd.extend(["-n", peer])
    p2pool_cmd.extend(unknown)
    p2pool_cmd.extend([str(active_creds[0]), str(active_creds[1])])

    rc = subprocess.call(p2pool_cmd)
    sys.exit(rc)


if __name__ == "__main__":
    main()
