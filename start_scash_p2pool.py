#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.3.0).
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
    "+8y+5035K8lPrs8="
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.3.0)          Core 30.4.0 |
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
                time.sleep(0.08)
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


def open_dashboard_browser(url):
    if platform.system().startswith("Linux"):
        disp = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        if not disp:
            return False
        devnull = open(os.devnull, "wb")
        sudo_user = os.environ.get("SUDO_USER", "").strip()
        try:
            if hasattr(os, "geteuid") and os.geteuid() == 0 and sudo_user and sudo_user != "root":
                subprocess.Popen(["sudo", "-u", sudo_user, "xdg-open", url], stdout=devnull, stderr=devnull)
                return True
            subprocess.Popen(["xdg-open", url], stdout=devnull, stderr=devnull)
            return True
        except Exception:
            pass
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def probe_working_credentials(host, port, datadirs, conf_user, conf_pass, rpc_timeout=12.0):
    candidates = [(conf_user, conf_pass)]
    for dd in datadirs:
        cu, cp = scash_nodes.read_cookie_credentials(dd)
        if cu and cp and (cu, cp) not in candidates:
            candidates.insert(0, (cu, cp))
        fu, fp = scash_nodes.read_conf_credentials(dd)
        if fu and fp and (fu, fp) not in candidates:
            candidates.append((fu, fp))
    last_err = {"code": -999, "message": "RPC unreachable"}
    for u, pw in candidates:
        ok, res, err = jsonrpc_call(host, port, u, pw, "getblockchaininfo", timeout=rpc_timeout)
        if ok or (err and err.get("code") not in (401, 403, -999)):
            return u, pw, ok, res, err
        if err:
            last_err = err
    return conf_user, conf_pass, False, None, last_err


def _cleanup_stale_linux_processes(rpc_port, all_datadirs, conf_user, conf_pass):
    my_pid = os.getpid()
    my_ppid = os.getppid() if hasattr(os, "getppid") else -1
    stale_launcher_pids = []
    stale_miner_pids = []
    stale_scashd_pids = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid in (my_pid, my_ppid, 1):
                continue
            try:
                raw_cmd = open("/proc/%d/cmdline" % pid, "rb").read()
                parts = [p.decode("utf-8", "replace") for p in raw_cmd.split(b"\x00") if p]
                if not parts:
                    continue
                joined = " ".join(parts)
                low = joined.lower()
                bn0 = os.path.basename(parts[0]).lower()
                if ("start_scash_p2pool.py" in low or "run_p2pool.py" in low) and "grep" not in bn0:
                    stale_launcher_pids.append(pid)
                elif bn0 in ("xmrigminer", "xmrigdaemon") and ("p2pool" in low or "127.0.0.1:8345" in low or "--daemonized" in low):
                    stale_miner_pids.append(pid)
                elif bn0 == "scashd" and ("scash-p2pool" in low or "/node/scashd" in low or "node_data" in low):
                    stale_scashd_pids.append(pid)
            except Exception:
                continue
    except Exception:
        return

    if not (stale_launcher_pids or stale_miner_pids or stale_scashd_pids):
        return

    print("[1/3] Stopping leftover background P2Pool process from previous Linux session...")
    for pid in stale_launcher_pids + stale_miner_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    if stale_scashd_pids:
        u, pw, ok, _, err = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass, rpc_timeout=3.0)
        if ok or (err and err.get("code") != -999):
            jsonrpc_call("127.0.0.1", rpc_port, u, pw, "stop", timeout=2.5)
        for pid in stale_scashd_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        for _ in range(15):
            if not any(os.path.exists("/proc/%d" % p) for p in stale_scashd_pids):
                break
            time.sleep(0.4)

    for _ in range(8):
        if not any(os.path.exists("/proc/%d" % p) for p in (stale_launcher_pids + stale_miner_pids)):
            break
        time.sleep(0.25)

    for pid in stale_launcher_pids + stale_miner_pids:
        if os.path.exists("/proc/%d" % pid):
            try:
                os.kill(pid, getattr(signal, "SIGKILL", 9))
            except Exception:
                pass

    for _ in range(16):
        if (not is_port_open("127.0.0.1", 8345, timeout=0.25)) and (not is_port_open("127.0.0.1", 8344, timeout=0.25)):
            break
        time.sleep(0.3)

    if is_port_open("127.0.0.1", 8344, timeout=0.25):
        print("[Notice] Port 8344 is still held by another user/root process! Run: sudo ./stop-scash-p2pool-linux.sh")


def cleanup_stale_p2pool_processes(rpc_port, all_datadirs, conf_user, conf_pass, primary_datadir):
    if platform.system() != "Windows":
        _cleanup_stale_linux_processes(rpc_port, all_datadirs, conf_user, conf_pass)
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


def ensure_windows_p2p_firewall_rule(p2p_port=8344):
    """When elevated on Windows, allow inbound TCP/UDP :8344 so P2Pool LAN & mesh peers connect cleanly."""
    if platform.system() != "Windows":
        return
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            return
        CREATE_NO_WINDOW = 0x08000000
        devnull = open(os.devnull, "wb")
        for proto in ("TCP", "UDP"):
            rule_name = "Scash P2Pool P2P %s %d" % (proto, int(p2p_port))
            chk = subprocess.call(
                ["netsh", "advfirewall", "firewall", "show", "rule", "name=%s" % rule_name],
                stdout=devnull,
                stderr=devnull,
                creationflags=CREATE_NO_WINDOW,
            )
            if chk != 0:
                subprocess.call(
                    [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        "name=%s" % rule_name,
                        "dir=in", "action=allow",
                        "protocol=%s" % proto,
                        "localport=%d" % int(p2p_port),
                        "profile=any",
                    ],
                    stdout=devnull,
                    stderr=devnull,
                    creationflags=CREATE_NO_WINDOW,
                )
    except Exception:
        pass


def start_bundled_scashd(scashd_bin, datadir, rpc_port=8342, p2p_port=None):
    cmd = [
        scashd_bin,
        "-datadir=%s" % datadir,
        "-chain=scash",
        "-server=1",
        "-listen=1",
        "-dnsseed=1",
        "-uacomment=p2pool",
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
        "127.0.0.1", rpc_port, all_datadirs, rpc_user, rpc_pass, rpc_timeout=12.0
    )
    if (not ok) and (not err or err.get("code") == -999) and is_port_open("127.0.0.1", rpc_port, timeout=1.0):
        print("[1/3] Local Scash node on 127.0.0.1:%d is busy verifying headers -- waiting for RPC..." % rpc_port)
        u, pw, ok, info, err = probe_working_credentials(
            "127.0.0.1", rpc_port, all_datadirs, rpc_user, rpc_pass, rpc_timeout=20.0
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
        except Exception as e:
            print("[2/3] Note: Port 8345 already active:", ascii_safe(e))
        if (not args.no_browser) and (not browser_opened[0]) and is_port_open("127.0.0.1", 8345, timeout=1.0):
            if open_dashboard_browser(ui_url):
                browser_opened[0] = True

        print("      Waiting for local Scash node to finish syncing before starting P2Pool sharechain...")
        last_kick = 0.0
        synced_height = 0
        while not shutting_down[0]:
            u, pw, bc_ok, bc_info, bc_err = probe_working_credentials(
                "127.0.0.1", active_creds[2], [active_datadir] + all_datadirs, active_creds[0], active_creds[1], rpc_timeout=15.0
            )
            active_creds[0], active_creds[1] = u, pw
            _, net_info, _ = jsonrpc_call(
                "127.0.0.1", active_creds[2], u, pw, "getnetworkinfo", timeout=8.0
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
                prev_hdrs = int(sync_state.get("headers", 0))
                prev_blks = int(sync_state.get("blocks", 0))
                if prev_hdrs > 0 and is_port_open("127.0.0.1", active_creds[2], timeout=0.8):
                    busy_msg = "Verifying RandomX block headers... (%d / %d blocks, headers: %d)" % (prev_blks, prev_hdrs, prev_hdrs)
                    sync_state["status_text"] = busy_msg
                    print("      [Scash Node]", busy_msg)
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
                    open_dashboard_browser(ui_url)
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

    ensure_windows_p2p_firewall_rule(8344)
    print("[3/3] Launching Scash P2Pool Sharechain Node on :8344 (P2P) & :8345 (Stratum + QtKawaii UI)...")
    # Verify native RandomX PoW engine against Scash Genesis Block #0 before starting P2Pool!
    os.environ["SCASH_REQUIRE_NATIVE_RANDOMX"] = "1"
    from p2pool.bitcoin import scash_randomx as _srx_chk
    import binascii as _b_chk, struct as _st_chk
    _ml0 = _b_chk.unhexlify("2f7b90fafd8247ee73d213d49699fcfe12a37c608f1d9d1c06f10e43cb6426c6")[::-1]
    _gh0 = _st_chk.pack("<I32s32sIII", 1, b"\x00" * 32, _ml0, 1708650456, 0x1e0fffff, 20076863)
    _rxh0, _ = _srx_chk.calculate_scash_hash_and_cm_bytes(_gh0)
    assert _b_chk.hexlify(_rxh0[::-1]).decode("ascii") == "33c450e0152826e3a8948b01464cf9182344a1544b3ddcf6153dd04b62938d01", "RandomX Genesis self-test mismatch!"
    print("[2/3] Verified native RandomX v1.2.1 PoW engine (Genesis hash match OK)!")

    # One-time cleanup on Linux to purge any stale corrupt shares.0 created by older non-static librandomx builds
    if platform.system() != "Windows":
        _scash_share_dir = os.path.join(ROOT_DIR, "data", "scash")
        _rx_ok_flag = os.path.join(_scash_share_dir, "LINUX_RX_VERIFIED_V2.flag")
        if os.path.isdir(_scash_share_dir) and not os.path.isfile(_rx_ok_flag):
            for _sfn in os.listdir(_scash_share_dir):
                if _sfn.startswith("shares.") or _sfn == "addrs":
                    try:
                        os.remove(os.path.join(_scash_share_dir, _sfn))
                    except Exception:
                        pass
        try:
            if not os.path.isdir(_scash_share_dir): os.makedirs(_scash_share_dir)
            open(_rx_ok_flag, "w").write("1\n")
        except Exception:
            pass

    p2pool_env = dict(os.environ)
    p2pool_env["SCASH_REQUIRE_NATIVE_RANDOMX"] = "1"
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
