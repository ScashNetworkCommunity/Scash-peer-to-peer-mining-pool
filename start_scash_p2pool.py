#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.2.0-beta.8).
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
KAWAII_ANSI_HIRES_ZB64 = (
    "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"
)
KAWAII_ANSI_BANNER_ZB64 = (
    "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"
    "sB0="
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.2.0-beta.8)   Core 30.4.0 |
| [ > Overview ]  [ Stratum :8345 ]  [ P2Pool :8344 ]  [ Scash RPC :8342 ]     |
+------------------------------------------------------------------------------+
|  * SCASH PEER-TO-PEER MINING POOL (Sovereign Node + Sharechain + CPU Miner)  |
|  +------------------------------------------------------------------------+  |
|  | Core  : Scash 2.3.0 (Core 30.4.0)   | UI   : http://127.0.0.1:8345/    |  |
|  | Algo  : rx/scash (1% Author Fee)    | Mine : stratum+tcp://127.0.0.1   |  |
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


class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class _CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", _COORD),
        ("dwCursorPosition", _COORD),
        ("wAttributes", ctypes.c_uint16),
        ("srWindow", _SMALL_RECT),
        ("dwMaximumWindowSize", _COORD),
    ]


def _ensure_wide_console_and_get_cols(target_cols=128, target_rows=42):
    cols = 80
    if platform.system() == "Windows":
        try:
            k32 = ctypes.windll.kernel32
            h_out = k32.GetStdHandle(-11)
            csbi = _CONSOLE_SCREEN_BUFFER_INFO()
            if h_out and h_out != -1 and k32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(csbi)):
                cur_w = int(csbi.srWindow.Right - csbi.srWindow.Left + 1)
                cur_h = int(csbi.srWindow.Bottom - csbi.srWindow.Top + 1)
                max_w = int(csbi.dwMaximumWindowSize.X) or target_cols
                max_h = int(csbi.dwMaximumWindowSize.Y) or target_rows
                want_w = min(target_cols, max_w - 2) if max_w > 84 else target_cols
                want_h = min(target_rows, max_h - 2) if max_h > 28 else target_rows
                if cur_w < 124 and want_w >= 124:
                    new_buf = _COORD(max(int(csbi.dwSize.X), want_w), max(int(csbi.dwSize.Y), want_h, 300))
                    k32.SetConsoleScreenBufferSize(h_out, new_buf)
                    rect = _SMALL_RECT(0, 0, want_w - 1, max(cur_h, want_h) - 1)
                    k32.SetConsoleWindowInfo(h_out, 1, ctypes.byref(rect))
                if k32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(csbi)):
                    cols = int(csbi.srWindow.Right - csbi.srWindow.Left + 1)
        except Exception:
            pass
        if cols < 124 and os.environ.get("WT_SESSION"):
            try:
                os.write(1, b"\x1b[8;42;128t")
                cols = 128
            except Exception:
                pass
        return cols

    try:
        import fcntl, struct, termios
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            rc = struct.unpack("hh", fcntl.ioctl(1, termios.TIOCGWINSZ, b"1234"))
            cols = int(rc[1]) or 80
            if cols < 124 and "xterm" in os.environ.get("TERM", "").lower():
                os.write(1, b"\x1b[8;42;128t")
                rc2 = struct.unpack("hh", fcntl.ioctl(1, termios.TIOCGWINSZ, b"1234"))
                if int(rc2[1]) >= 124:
                    cols = int(rc2[1])
    except Exception:
        try:
            cols = int(os.environ.get("COLUMNS", "80"))
        except Exception:
            cols = 80
    return cols


def print_kawaii_terminal_banner(force_ascii=False):
    if force_ascii or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        print(KAWAII_ASCII_FALLBACK)
        return False

    term_cols = _ensure_wide_console_and_get_cols(128, 42)
    chosen_b64 = KAWAII_ANSI_HIRES_ZB64 if term_cols >= 124 else KAWAII_ANSI_BANNER_ZB64

    try:
        raw_utf8 = zlib.decompress(base64.b64decode(chosen_b64.encode("ascii")))
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
    node_fallback_wallet = ctrl.wallet or "scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc"

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
                        start_url = "http://127.0.0.1:8345/miner_start?wallet=%s" % ctrl.wallet
                        if getattr(ctrl, "custom_threads", False):
                            start_url += "&threads=%d" % int(ctrl.threads)
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
