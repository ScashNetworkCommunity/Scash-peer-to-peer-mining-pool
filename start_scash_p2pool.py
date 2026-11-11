#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.2.0-beta.5).
Publisher: magicalgirlsunite | Community: ScashNetworkCommunity
Compatible with BOTH PyPy 2.7 (bundled runtime) and Python 3.x!
- Wraps stdout/stderr safely on PyPy 2.7 so Unicode strings from Scash Core 30.4.0
  (e.g. u"Loading block index\u2026") NEVER raise UnicodeEncodeError on cp437!
- Includes Win32 Job Object (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) + ConsoleCtrlHandler
  and Linux PR_SET_PDEATHSIG + SIGHUP/SIGTERM handlers for zero-orphan shutdown.
"""
from __future__ import print_function
import argparse
import atexit
import base64
import codecs
import ctypes
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zlib

# Register cp65001 -> utf-8 alias so PyPy 2.7 on Windows UTF-8 consoles never raises LookupError
try:
    codecs.register(lambda n: codecs.lookup("utf-8") if n.lower().replace("-", "").replace("_", "") in ("cp65001", "65001") else None)
except Exception:
    pass


def ascii_safe(val):
    if val is None:
        return ""
    try:
        u = val.decode("utf-8", "replace") if isinstance(val, bytes) else val
        if not isinstance(u, str) and sys.version_info[0] < 3:
            # Python 2 unicode
            u = (
                u.replace(u"\u2026", u"...")
                .replace(u"\u2014", u"--")
                .replace(u"\u2013", u"-")
                .replace(u"\u2022", u"*")
                .replace(u"\u2018", u"'")
                .replace(u"\u2019", u"'")
                .replace(u"\u201c", u'"')
                .replace(u"\u201d", u'"')
            )
            return u.encode("ascii", "replace")
        if sys.version_info[0] >= 3 and isinstance(u, str):
            return (
                u.replace("\u2026", "...")
                .replace("\u2014", "--")
                .replace("\u2013", "-")
                .replace("\u2022", "*")
            )
        return str(u)
    except Exception:
        try:
            return repr(val)
        except Exception:
            return ""


class _SafeConsoleStream(object):
    """Prevents PyPy 2.7 cp437/cp1252 UnicodeEncodeError on any print() call."""
    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        if sys.version_info[0] < 3:
            try:
                if not isinstance(data, bytes):
                    data = (
                        data.replace(u"\u2026", u"...")
                        .replace(u"\u2014", u"--")
                        .replace(u"\u2013", u"-")
                        .replace(u"\u2022", u"*")
                    )
                    enc = getattr(self._inner, "encoding", None) or "ascii"
                    data = data.encode(enc, "replace")
            except Exception:
                try:
                    data = data.encode("ascii", "replace")
                except Exception:
                    pass
        else:
            if isinstance(data, str):
                try:
                    enc = getattr(self._inner, "encoding", None) or "utf-8"
                    data.encode(enc)
                except Exception:
                    data = ascii_safe(data).encode(enc, "replace").decode(enc, "replace")
        return self._inner.write(data)

    def flush(self):
        try:
            return self._inner.flush()
        except Exception:
            pass

    def __getattr__(self, attr):
        return getattr(self._inner, attr)


if not isinstance(sys.stdout, _SafeConsoleStream):
    sys.stdout = _SafeConsoleStream(sys.stdout)
if not isinstance(sys.stderr, _SafeConsoleStream):
    sys.stderr = _SafeConsoleStream(sys.stderr)

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

_WIN_JOB_HANDLE = None
_WIN_CTRL_HANDLER = None

# Pre-rendered 80x21 24-bit TrueColor ANSI QtKawaii Wallet Terminal Header (WGL4/CP437 safe)
KAWAII_ANSI_BANNER_ZB64 = (
    "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"
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.2.0-beta.5)   Core 30.4.0 |
| [ > Overview ]  [ Stratum :8345 ]  [ P2Pool :8344 ]  [ Scash RPC :8342 ]     |
+------------------------------------------------------------------------------+
|  * SCASH PEER-TO-PEER MINING POOL (Sovereign Node + Sharechain + CPU Miner)  |
|  +------------------------------------------------------------------------+  |
|  | Core  : Scash 2.3.0 (Core 30.4.0)   | UI   : http://127.0.0.1:8345/    |  |
|  | Algo  : RandomX rx/scash (0% Fee)   | Mine : stratum+tcp://127.0.0.1   |  |
|  | Team  : magicalgirlsunite           | Repo : ScashNetworkCommunity     |  |
|  +------------------------------------------------------------------------+  |
+------------------------------------------------------------------------------+"""


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def setup_win32_kill_on_close_job():
    global _WIN_JOB_HANDLE
    if platform.system() != "Windows":
        return None
    if _WIN_JOB_HANDLE is not None:
        return _WIN_JOB_HANDLE
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.SetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        k32.SetHandleInformation.restype = ctypes.c_int
        k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        k32.SetInformationJobObject.restype = ctypes.c_int
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.AssignProcessToJobObject.restype = ctypes.c_int
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = ctypes.c_void_p

        h_job = k32.CreateJobObjectW(None, None)
        if not h_job:
            return None
        HANDLE_FLAG_INHERIT = 0x00000001
        k32.SetHandleInformation(h_job, HANDLE_FLAG_INHERIT, 0)

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        JobObjectExtendedLimitInformation = 9
        if not k32.SetInformationJobObject(h_job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
            return None

        k32.AssignProcessToJobObject(h_job, k32.GetCurrentProcess())
        _WIN_JOB_HANDLE = h_job
        return h_job
    except Exception:
        return None


def assign_popen_to_win32_job(proc):
    if platform.system() != "Windows" or _WIN_JOB_HANDLE is None or proc is None:
        return
    try:
        k32 = ctypes.windll.kernel32
        h_proc = getattr(proc, "_handle", None)
        if h_proc:
            k32.AssignProcessToJobObject(ctypes.c_void_p(_WIN_JOB_HANDLE), ctypes.c_void_p(int(h_proc)))
    except Exception:
        pass


def _make_linux_pdeathsig_preexec():
    if not platform.system().startswith("Linux"):
        return None

    def _preexec():
        try:
            libc = ctypes.CDLL("libc.so.6")
            PR_SET_PDEATHSIG = 1
            libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)
        except Exception:
            pass

    return _preexec


def print_kawaii_terminal_banner(force_ascii=False):
    if force_ascii or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        print(KAWAII_ASCII_FALLBACK)
        return False

    try:
        raw_utf8 = zlib.decompress(base64.b64decode(KAWAII_ANSI_BANNER_ZB64.encode("ascii")))
        u_banner = raw_utf8.decode("utf-8")
    except Exception:
        print(KAWAII_ASCII_FALLBACK)
        return False

    is_win = platform.system() == "Windows"
    if is_win:
        try:
            k32 = ctypes.windll.kernel32
            h_out = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32(0)
            if h_out and h_out != -1 and k32.GetConsoleMode(h_out, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                if k32.SetConsoleMode(h_out, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                    written = ctypes.c_uint32(0)
                    k32.WriteConsoleW(h_out, ctypes.c_wchar_p(u_banner), len(u_banner), ctypes.byref(written), None)
                    return True
        except Exception:
            pass
        if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") or "xterm" in os.environ.get("TERM", "").lower():
            try:
                os.write(1, raw_utf8)
                return True
            except Exception:
                pass
        print(KAWAII_ASCII_FALLBACK)
        return False

    try:
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            os.write(1, raw_utf8)
            return True
    except Exception:
        pass

    print(KAWAII_ASCII_FALLBACK)
    return False


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
        fu, fp = scash_nodes.read_conf_credentials(dd)
        if fu and fp and (fu, fp) not in candidates:
            candidates.append((fu, fp))
    for u, pw in candidates:
        ok, res, err = jsonrpc_call(host, port, u, pw, "getblockchaininfo", timeout=3.0)
        if ok or (err and err.get("code") not in (401, 403, -999)):
            return u, pw, ok, res, err
    return conf_user, conf_pass, False, None, {"code": -999, "message": "RPC unreachable"}


def cleanup_stale_p2pool_processes(rpc_port, all_datadirs, conf_user, conf_pass, primary_datadir):
    if platform.system() != "Windows":
        return
    try:
        ps_cmd = (
            "Get-Process scashd,xmrigMiner,xmrigDaemon -ErrorAction SilentlyContinue | "
            "Select-Object Id,ProcessName,Path | ConvertTo-Json -Compress"
        )
        CREATE_NO_WINDOW = 0x08000000
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            creationflags=CREATE_NO_WINDOW,
        ).decode("utf-8", "replace").strip()
        if not raw:
            return
        parsed = json.loads(raw)
        procs = parsed if isinstance(parsed, list) else [parsed]
        stale_pids = []
        has_stale_scashd = False
        for item in procs:
            if not isinstance(item, dict):
                continue
            pid = item.get("Id")
            pname = (item.get("ProcessName") or "").lower()
            ppath = (item.get("Path") or "").lower()
            if pname in ("xmrigminer", "xmrigdaemon"):
                if "p2pool" in ppath or not ppath:
                    stale_pids.append((pid, pname))
            elif pname == "scashd":
                if ("p2pool" in ppath) or ("\\node\\scashd.exe" in ppath):
                    has_stale_scashd = True
                    stale_pids.append((pid, pname))

        if not has_stale_scashd and any((x.get("ProcessName") or "").lower() == "scashd" for x in procs if isinstance(x, dict)):
            u, pw, ok, info, _ = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass)
            if ok and isinstance(info, dict) and int(info.get("blocks", 0)) == 0 and scash_nodes._has_blocks_dir(primary_datadir):
                has_stale_scashd = True
                for item in procs:
                    if isinstance(item, dict) and (item.get("ProcessName") or "").lower() == "scashd":
                        stale_pids.append((item.get("Id"), "scashd"))

        if not stale_pids:
            return

        print("[1/3] Detected leftover background process from previous P2Pool session -- stopping cleanly...")
        if has_stale_scashd:
            u, pw, ok, _, err = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass)
            if ok or (err and err.get("code") != -999):
                jsonrpc_call("127.0.0.1", rpc_port, u, pw, "stop", timeout=2.5)
                for _ in range(12):
                    if not is_port_open("127.0.0.1", rpc_port, timeout=0.4):
                        break
                    time.sleep(0.4)

        for pid, _ in stale_pids:
            if pid:
                subprocess.call(
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=open(os.devnull, "wb"),
                    stderr=open(os.devnull, "wb"),
                    creationflags=CREATE_NO_WINDOW,
                )
        time.sleep(0.5)
    except Exception:
        pass


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


def start_bundled_scashd(scashd_bin, datadir, rpc_port=8342, p2p_port=None):
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
    if p2p_port is not None:
        cmd.append("-port=%d" % int(p2p_port))
    for peer in scash_nodes.DEFAULT_SCASH_ADDNODES[:8]:
        cmd.append("-addnode=%s" % peer)
    if platform.system() != "Windows":
        cmd.append("-daemon=0")
    kwargs = {}
    if platform.system() == "Windows":
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NO_WINDOW
    else:
        preexec = _make_linux_pdeathsig_preexec()
        if preexec is not None:
            kwargs["preexec_fn"] = preexec
    devnull = open(os.devnull, "wb")
    kwargs["stdout"] = devnull
    kwargs["stderr"] = devnull
    proc = subprocess.Popen(cmd, **kwargs)
    assign_popen_to_win32_job(proc)
    return proc


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
            self.send_header("Connection", "close")
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
                self.send_header("Connection", "close")
                self.end_headers()
                return

            if path == "/node_sync_status":
                self._send_json(sync_state)
                return

            if path == "/local_stats":
                self._send_json({"syncing": True, "p2pool_ready": False}, code=503)
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
                lp = qs.get("large_pages", [None])[0]
                ctrl.save_wallet_settings(w if w is not None else ctrl.wallet, threads=t, worker=wk, large_pages=lp)
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
                    elif ext == ".webp":
                        ctype = "image/webp"
                    raw = open(fp, "rb").read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

            self.send_response(404)
            self.send_header("Connection", "close")
            self.end_headers()

    return SyncHTTPHandler


def main():
    global _WIN_CTRL_HANDLER
    parser = argparse.ArgumentParser(description="One-Click Scash Node + P2Pool + Launcher")
    parser.add_argument("--wallet", default=None, help="Optional scash1... wallet address")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads for local mining")
    parser.add_argument("--peer", action="append", default=[], help="Additional P2Pool peer address (host:8344)")
    parser.add_argument("--scashd-bin", default=None, help="Custom path to scashd binary")
    parser.add_argument("--datadir", default=None, help="Custom Scash Core data directory")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--no-banner", action="store_true", help="Skip QtKawaii terminal header")
    parser.add_argument("--allow-unsynced", action="store_true", help="Start P2Pool without waiting for Mainnet block sync")
    args, unknown = parser.parse_known_args()

    setup_win32_kill_on_close_job()

    if not args.no_banner:
        print_kawaii_terminal_banner()
        print("")

    ctrl = xmrig_manager.GLOBAL_XMRIG
    if args.wallet:
        ctrl.save_wallet_settings(args.wallet, threads=args.threads)
    elif args.threads:
        ctrl.save_wallet_settings(ctrl.wallet, threads=args.threads)

    primary_datadir = args.datadir or scash_nodes.get_scash_datadir()
    conf_path, rpc_user, rpc_pass, rpc_port = scash_nodes.configure_scash_conf(custom_datadir=primary_datadir)
    print("[1/3] Configured scash.conf with active Scash peers:", ascii_safe(conf_path))

    active_datadir = primary_datadir
    all_datadirs = scash_nodes.get_candidate_datadirs(primary_datadir)
    spawned_proc = [None]
    p2pool_proc = [None]
    active_creds = [rpc_user, rpc_pass, rpc_port]
    shutting_down = [False]

    def _graceful_shutdown_all():
        if shutting_down[0]:
            return
        shutting_down[0] = True
        try:
            _NO_PROXY_OPENER.open("http://127.0.0.1:8345/miner_stop", timeout=0.8).read()
        except Exception:
            pass
        try:
            ctrl.stop_mining()
        except Exception:
            pass
        if p2pool_proc[0] is not None and p2pool_proc[0].poll() is None:
            try:
                p2pool_proc[0].terminate()
            except Exception:
                pass
        if spawned_proc[0] is not None and spawned_proc[0].poll() is None:
            try:
                print("\n[Shutdown] Stopping bundled Scash Core 30.4 node cleanly...")
            except Exception:
                pass
            jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "stop", timeout=2.0)
            for _ in range(15):
                if spawned_proc[0].poll() is not None:
                    break
                time.sleep(0.2)
            if spawned_proc[0].poll() is None:
                try:
                    spawned_proc[0].terminate()
                except Exception:
                    pass

    atexit.register(_graceful_shutdown_all)

    if platform.system() == "Windows":
        try:
            CTRL_HANDLER_FUNC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint32)

            def _win_ctrl_cb(ctrl_type):
                if ctrl_type in (0, 1, 2, 5, 6):
                    _graceful_shutdown_all()
                    if ctrl_type in (2, 5, 6):
                        os._exit(0)
                    return 1
                return 0

            _WIN_CTRL_HANDLER = CTRL_HANDLER_FUNC(_win_ctrl_cb)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_WIN_CTRL_HANDLER, 1)
        except Exception:
            pass
    else:
        def _posix_sig_handler(signum, frame):
            _graceful_shutdown_all()
            sys.exit(0)

        for sig_name in ("SIGINT", "SIGTERM", "SIGHUP"):
            sig_val = getattr(signal, sig_name, None)
            if sig_val is not None:
                try:
                    signal.signal(sig_val, _posix_sig_handler)
                except Exception:
                    pass

    cleanup_stale_p2pool_processes(rpc_port, all_datadirs, rpc_user, rpc_pass, primary_datadir)

    u, pw, ok, info, err = probe_working_credentials(
        "127.0.0.1", rpc_port, all_datadirs, rpc_user, rpc_pass
    )
    if ok or (err and err.get("code") != -999):
        active_creds[0], active_creds[1] = u, pw
        print("[1/3] Connected to running local Scash node on 127.0.0.1:%d." % rpc_port)
    else:
        scashd_bin = find_scashd_binary(args.scashd_bin)
        if not scashd_bin:
            print("[ERROR] Bundled scashd binary not found and 127.0.0.1:%d is offline." % rpc_port)
            sys.exit(1)

        print("[1/3] Spinning up bundled local Scash Core 30.4 node (%s)..." % ascii_safe(os.path.basename(scashd_bin)))
        proc = start_bundled_scashd(scashd_bin, active_datadir, active_creds[2])
        spawned_proc[0] = proc

        connected = False
        used_fallback = False
        for _ in range(120):
            if shutting_down[0]:
                sys.exit(0)
            if proc.poll() is not None and not used_fallback:
                used_fallback = True
                fallback_dd = os.path.join(ROOT_DIR, "node_data")
                print("[1/3] Notice: %s is currently locked by an open Scash-Qt Wallet window." % ascii_safe(primary_datadir))
                print("      Tip: Restart Scash-Qt Wallet once (or close it before launching P2Pool)")
                print("      to share your existing synced Scash blocks immediately without re-syncing!")
                print("      Spinning up dedicated P2Pool Scash node in:", ascii_safe(fallback_dd))
                active_datadir = fallback_dd
                _, rpc_user, rpc_pass, rpc_port = scash_nodes.configure_scash_conf(custom_datadir=active_datadir)
                active_creds = [rpc_user, rpc_pass, rpc_port]
                proc = start_bundled_scashd(scashd_bin, active_datadir, active_creds[2])
                spawned_proc[0] = proc
                time.sleep(1.5)
            u, pw, ok, info, err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir] + all_datadirs, active_creds[0], active_creds[1]
            )
            if ok or (err and err.get("code") != -999):
                active_creds[0], active_creds[1] = u, pw
                connected = True
                break
            time.sleep(0.5)

        if not connected:
            print("[ERROR] Local Scash node did not open RPC port 127.0.0.1:%d." % active_creds[2])
            print("        Check debug.log in:", ascii_safe(active_datadir))
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
            "p2pool_ready": False,
            "blocks": 0,
            "headers": 0,
            "progress_pct": 0.0,
            "connections": 0,
            "datadir": active_datadir,
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
            print("[2/3] Note: Port 8345 busy during sync check:", ascii_safe(e))

        print("      Waiting for local Scash node to finish syncing before starting P2Pool sharechain...")
        last_kick = 0.0
        synced_height = 0
        while not shutting_down[0]:
            u, pw, bc_ok, bc_info, bc_err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir] + all_datadirs, active_creds[0], active_creds[1]
            )
            active_creds[0], active_creds[1] = u, pw
            _, net_info, _ = jsonrpc_call(
                "127.0.0.1", active_creds[2], u, pw, "getnetworkinfo", timeout=3.0
            )
            peers = int((net_info or {}).get("connections", 0)) if isinstance(net_info, dict) else 0
            subver = ascii_safe((net_info or {}).get("subversion", "/Scash:30.4.0/")) if isinstance(net_info, dict) else "/Scash:30.4.0/"

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
                    msg = "Connecting to Scash Mainnet peers on :8343... (Peers: 0 - discovering network headers)"
                elif hdrs == 0:
                    msg = "Connected to %d Scash peer(s) - downloading block headers..." % peers
                else:
                    msg = "Syncing Scash blockchain: %d / %d blocks (%.1f%%) | Peers: %d" % (blks, hdrs, pct, peers)
                sync_state.update({
                    "syncing": True,
                    "p2pool_ready": False,
                    "blocks": blks,
                    "headers": hdrs,
                    "progress_pct": pct,
                    "connections": peers,
                    "subversion": subver,
                    "bestblockhash": bc_info.get("bestblockhash", ""),
                    "datadir": active_datadir,
                    "status_text": msg,
                })
                print("      [Scash Node]", ascii_safe(msg))
                if is_mainnet_node_synced(bc_info, net_info, allow_unsynced=args.allow_unsynced):
                    gbt_ok2, gbt_res2, _ = jsonrpc_call(
                        "127.0.0.1", active_creds[2], u, pw,
                        "getblocktemplate", [{"mode": "template", "rules": ["segwit"]}], timeout=5.0
                    )
                    if gbt_ok2 and isinstance(gbt_res2, dict):
                        synced_height = blks
                        break
            else:
                raw_warm = (bc_err or {}).get("message", "Starting Scash node...")
                warm_msg = ascii_safe(raw_warm)
                sync_state.update({
                    "syncing": True,
                    "p2pool_ready": False,
                    "datadir": active_datadir,
                    "status_text": "Scash node warming up: %s" % warm_msg,
                })
                print("      [Scash Node] Warming up:", warm_msg)

            for _ in range(10):
                if shutting_down[0]:
                    break
                time.sleep(0.5)

        if sync_srv is not None:
            sync_srv.shutdown()
            sync_srv.server_close()
            for _ in range(15):
                if not is_port_open("127.0.0.1", 8345, timeout=0.25):
                    break
                time.sleep(0.2)
        if shutting_down[0]:
            sys.exit(0)
        print("[2/3] Local Scash node is synced at block #%d and serving SegWit block templates!" % synced_height)
    else:
        print("[2/3] Local Scash node is already synced at block #%d!" % int((init_bc or {}).get("blocks", 0)))

    ctrl._load_saved_wallet()
    # Internal fallback address ONLY for run_p2pool.py's required -a flag if user hasn't saved their own wallet yet
    node_fallback_wallet = ctrl.wallet or "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2"

    def _post_p2pool_ready():
        for _ in range(45):
            if shutting_down[0]:
                return
            if is_port_open("127.0.0.1", 8345):
                if (not args.no_browser) and (not browser_opened[0]):
                    webbrowser.open(ui_url)
                    browser_opened[0] = True
                if ctrl.wallet and ctrl.wallet.lower().startswith(("scash1", "tcash1")) and len(ctrl.wallet) >= 26:
                    try:
                        start_url = "http://127.0.0.1:8345/miner_start?wallet=%s&threads=%d" % (
                            ctrl.wallet, int(ctrl.threads)
                        )
                        _NO_PROXY_OPENER.open(start_url, timeout=5.0).read()
                        print("[3/3] Auto-started local XMRig worker on 127.0.0.1:8345 for:", ascii_safe(ctrl.wallet))
                    except Exception as e:
                        print("[3/3] Note: Start worker from Web UI (%s)" % ascii_safe(e))
                break
            time.sleep(1.0)

    t_ready = threading.Thread(target=_post_p2pool_ready)
    t_ready.daemon = True
    t_ready.start()

    print("[3/3] Launching Scash P2Pool Sharechain Node on :8344 (P2P) & :8345 (Stratum + QtKawaii UI)...")
    p2pool_env = dict(os.environ)
    p2pool_env["SCASH_ACTIVE_DATADIR"] = str(active_datadir)
    p2pool_env["SCASH_RPC_PORT"] = str(active_creds[2])
    p2pool_env["SCASH_RPC_USER"] = str(active_creds[0])
    p2pool_env["SCASH_RPC_PASS"] = str(active_creds[1])

    p2pool_cmd = [
        sys.executable,
        os.path.join(ROOT_DIR, "run_p2pool.py"),
        "--net", "scash",
        "--disable-upnp",
        "--bitcoind-address", "127.0.0.1",
        "--bitcoind-rpc-port", str(active_creds[2]),
        "--bitcoind-p2p-port", "8343",
        "-a", node_fallback_wallet,
    ]
    for peer in args.peer:
        p2pool_cmd.extend(["-n", peer])
    p2pool_cmd.extend(unknown)
    p2pool_cmd.extend([str(active_creds[0]), str(active_creds[1])])

    p2p_kwargs = {"env": p2pool_env}
    if platform.system() != "Windows":
        preexec = _make_linux_pdeathsig_preexec()
        if preexec is not None:
            p2p_kwargs["preexec_fn"] = preexec

    p2pool_proc[0] = subprocess.Popen(p2pool_cmd, **p2p_kwargs)
    assign_popen_to_win32_job(p2pool_proc[0])

    try:
        while p2pool_proc[0].poll() is None:
            time.sleep(0.4)
        rc = p2pool_proc[0].returncode
    except KeyboardInterrupt:
        _graceful_shutdown_all()
        rc = 0
    finally:
        _graceful_shutdown_all()

    sys.exit(rc if rc is not None else 0)


if __name__ == "__main__":
    main()
