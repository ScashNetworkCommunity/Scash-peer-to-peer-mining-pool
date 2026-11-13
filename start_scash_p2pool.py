#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.2.0).
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
    "ffBHz5/9Wff8YX8/8AVehofw=="
)
KAWAII_ANSI_BANNER_ZB64 = (
    "eNrlXMuOHUdy3fsXtKmNAQkDNivfmaqVTIxtwZZEkzPwQvCiQTfIhtlsodmSZgAvhFnPYhbEQAa8MA"
    "zDH+HP0Zc4TuQzsu69JDWU2ICk5uMWs/IZceLEI+8HX5q46S2ETeMvxm4Wn7XZFP1VXf3w6o8/vPru"
    "F/Pzpw++XK/+6oPXbsofPviSH9l1M+vm3dVS3lEpbUq7TTt39cOf/6s+1tbkvpy+evzk/OWz5aF+eH"
    "39fLm3fHVxcaPx272v8ODDf7r9h/Nvzy8vl2/WM322frRM/+0md/Xg+uZiMeuZPVuXMi851bdaksHk"
    "Nxevel/rpta4Gd1WSaurv2iV/7d88c3FzTeXF98uuz7qE/qNxgz+6uCO3N6c3359tXwcjXVv0kfZPL"
    "S3bzFmxLB0Rm69+vz6Xy+WRw8fcB/6eB9KRfSjoju4+C+XfJr/shzYvTfY8X4yin4PiTue2/3nL0kD"
    "/+dNxXUUdYNn7XzKg/mVP3+Xf2ozUtSwWQjwd9Obve30Uw95RVNXXuVHwWwe0pKGZzQFQ/+yDo+iQU"
    "ulw/BsP8PTPwfWLftZ3uq/PZ68BWYsbziZYYNtOxpSRRM2nw7txdI0kF40avNxOCdjoGS+dEN9aNId"
    "PTYgLfT0Tm6gIilwoDOzdmijLAkArUnrtTRzlh54PBibOWpmqRkNmptRt8opmoFoRjihVpp9LLuUH3"
    "h6EIZmPm0e51+HJETimZk4ieGwSwYrjPHILvVjfO1BHDtPmqS/C7b+T7spv2tJrOKRICF0FlV+YCbM"
    "cALOb27dUhkGh+boQEcJcywNqUiYC4QGW1KTjKYtlC5IXkjcomgQGB10aUB/WhpxaEAvEL2Ibo9jtc"
    "EKzahDQJRIrpQSfdA0/RaLuIGbkLQpI9Ya8GodBtJOtl4ILT2jf1ZrEcgEoaZfZpoLrTGULbW0u6Eh"
    "XyFGNLCHgSvdkPrS4tM4kIqptKmzIb2myfhxIF5OLMpIf1V0WEqNQ2GytCo6sKJlK7XCrIWWYSPIAE"
    "BH61jUqzhDqF5schKy4tILcjokTVXpsd0ajGNooLhBVWYFWYtmD2ZVGC2si+iBxGgAM2/zGZmjgIEO"
    "vTQ7h3SAEAxid/VmFuX12PGH5Yf/+N/l8YNPHv/98vDXv3507zdf3MOfy2effv7p53+3PPzii3+sYN"
    "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"
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.2.0)          Core 30.4.0 |
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
