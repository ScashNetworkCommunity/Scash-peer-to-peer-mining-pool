#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.4.0).
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
import re
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
    "Nv1Q5Hr1Xr+r5/u/AQtf/Zy+z+x73pS/An2SrZM="
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.4.0)          Core 30.4.0 |
| [ > Overview ]  [ Stratum :8345 ]  [ P2Pool :8344 ]  [ Scash RPC :8342 ]     |
+------------------------------------------------------------------------------+
|  * SCASH PEER-TO-PEER MINING POOL (Sovereign Node + Sharechain + CPU Miner)  |
|  +------------------------------------------------------------------------+  |
|  | Core  : Scash 2.3.0 (Core 30.4.0)   | UI   : http://127.0.0.1:8345/    |  |
|  | Algo  : rx/scash (0% Pool Fee)      | Mine : stratum+tcp://127.0.0.1   |  |
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
            # Disable Windows Console QuickEdit Mode (0x0040) so clicking inside the terminal never pauses P2Pool in 'Select ...' mode!
            h_in = k32.GetStdHandle(-10)
            m_in = ctypes.c_uint32(0)
            if h_in and h_in != -1 and k32.GetConsoleMode(h_in, ctypes.byref(m_in)):
                k32.SetConsoleMode(h_in, ctypes.c_uint32((int(m_in.value) & ~0x0040) | 0x0080))
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


def _posix_terminal_supports_truecolor(env=None):
    """
    Returns True ONLY when the POSIX terminal emulator is verified to support 24-bit SGR TrueColor
    (`\x1b[38;2;R;G;Bm` / `\x1b[48;2;R;G;Bm`). Prevents non-TrueColor terminals (`rxvt`, plain
    `xterm`, `TERM=linux`, unconfigured `tmux`/`screen`, or basic SSH clients) from misparsing RGB
    channel bytes like `41` as legacy SGR `41` (bright red background)!
    """
    e = os.environ if env is None else env
    if e.get("NO_COLOR") or e.get("SCASH_ASCII_BANNER") == "1":
        return False
    term = (e.get("TERM") or "").strip().lower()
    cterm = (e.get("COLORTERM") or "").strip().lower()
    if not term or term in ("dumb", "linux", "vt100", "vt102", "vt220", "ansi", "cons25", "cygwin"):
        return False
    if "rxvt" in term:
        return cterm in ("truecolor", "24bit")
    if cterm in ("truecolor", "24bit"):
        return True
    # Inside screen/tmux without explicit COLORTERM=truecolor/24bit, 24-bit SGR degrades unpredictably
    if e.get("STY") or e.get("TMUX") or term.startswith(("screen", "tmux")):
        return False
    if term.endswith(("-direct", "-truecolor")) or term in (
        "xterm-kitty", "wezterm", "alacritty", "foot", "foot-extra", "xterm-ghostty", "contour"
    ):
        return True
    if e.get("KITTY_WINDOW_ID") or e.get("WEZTERM_EXECUTABLE") or e.get("KONSOLE_VERSION") or e.get("WT_SESSION"):
        return True
    try:
        if int(e.get("VTE_VERSION") or "0") >= 3600:
            return True
    except Exception:
        pass
    return False


def print_kawaii_terminal_banner(force_ascii=False):
    if force_ascii or os.environ.get("NO_COLOR") or os.environ.get("SCASH_ASCII_BANNER") == "1" or os.environ.get("TERM") == "dumb":
        print(KAWAII_ASCII_FALLBACK)
        return False

    is_win = platform.system() == "Windows"
    if (not is_win) and (not _posix_terminal_supports_truecolor()):
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
        if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") or os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
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
            # If scashd accepted TCP on :8342 and timed out holding cs_main (RandomX header presync),
            # do not pile up duplicate timed-out RPC calls with fallback credentials!
            if err.get("code") == -999 and "timed out" in str(err.get("message", "")).lower():
                return u, pw, False, None, err
    return conf_user, conf_pass, False, None, last_err


_PRESYNC_RE = re.compile(r"(Pre-synchronizing|Synchronizing) blockheaders,\s*height:\s*(\d+)\s*\(\~?([0-9.]+)%\)")
_UPDATETIP_RE = re.compile(r"UpdateTip:\s*new best=\S+\s+height=(\d+)")


def _read_scash_debug_log_sync_hint(datadir, peers=0):
    """
    Reads the tail (last 24 KB) of `<datadir>/scash/debug.log` or `<datadir>/debug.log`
    so first-time 0-block syncs display real-time Bitcoin Core 30.4 `Pre-synchronizing blockheaders`
    height & `%` while `getblockchaininfo` still reports `headers: 0` or waits on `cs_main`!
    Returns `(status_msg, est_headers, est_pct)` or `(None, 0, 0.0)`.
    """
    if not datadir:
        return None, 0, 0.0
    cands = []
    for rel in (os.path.join("scash", "debug.log"), "debug.log"):
        p = os.path.join(datadir, rel)
        if os.path.isfile(p):
            try:
                cands.append((os.path.getmtime(p), p))
            except Exception:
                cands.append((0.0, p))
    if not cands:
        return None, 0, 0.0
    cands.sort(reverse=True)
    log_p = cands[0][1]
    try:
        fh = open(log_p, "rb")
        try:
            fh.seek(0, 2)
            sz = fh.tell()
            fh.seek(max(0, sz - 24576), 0)
            tail_txt = fh.read().decode("utf-8", "replace")
        finally:
            fh.close()
        lines = tail_txt.splitlines()
        for ln in reversed(lines):
            m_pre = _PRESYNC_RE.search(ln)
            if m_pre:
                kind = m_pre.group(1)
                h_int = int(m_pre.group(2))
                pct_f = float(m_pre.group(3))
                h_fmt = "{:,}".format(h_int)
                stage_lbl = "Pre-synchronizing" if kind.startswith("Pre-") else "Synchronizing"
                peer_sfx = (" | Peers: %d" % int(peers)) if int(peers) > 0 else ""
                return (
                    "%s Scash RandomX block headers: height %s (~%.1f%%)%s" % (stage_lbl, h_fmt, pct_f, peer_sfx),
                    h_int,
                    pct_f,
                )
            m_tip = _UPDATETIP_RE.search(ln)
            if m_tip:
                h_int = int(m_tip.group(1))
                peer_sfx = (" | Peers: %d" % int(peers)) if int(peers) > 0 else ""
                return (
                    "Validating Scash blocks at height %s...%s" % ("{:,}".format(h_int), peer_sfx),
                    h_int,
                    0.0,
                )
    except Exception:
        pass
    return None, 0, 0.0


def _find_linux_listening_socket_owners(ports=(8344, 8345), proc_root="/proc"):
    """
    Inspects /proc/net/tcp and /proc/net/tcp6 for TCP_LISTEN ('0A') sockets on `ports`,
    returning (listener_pids, has_privileged_listener) so stale P2Pool listeners are found
    even if started under a custom script name or an earlier `sudo` session!
    """
    my_pid = os.getpid()
    my_ppid = os.getppid() if hasattr(os, "getppid") else -1
    my_uid = os.geteuid() if hasattr(os, "geteuid") else -1
    want_ports = set(int(p) for p in ports)
    inodes_to_uid = {}
    priv_held = False

    for net_fn in ("net/tcp", "net/tcp6"):
        p_net = os.path.join(proc_root, net_fn)
        if not os.path.isfile(p_net):
            continue
        try:
            lines = open(p_net, "r").read().splitlines()[1:]
        except Exception:
            continue
        for ln in lines:
            cols = ln.split()
            if len(cols) < 10 or cols[3] != "0A":
                continue
            try:
                loc_port = int(cols[1].rsplit(":", 1)[1], 16)
            except Exception:
                continue
            if loc_port not in want_ports:
                continue
            try:
                s_uid = int(cols[7])
            except Exception:
                s_uid = -1
            inode = cols[9]
            if inode and inode != "0":
                inodes_to_uid[inode] = s_uid
            if my_uid > 0 and s_uid != -1 and s_uid != my_uid:
                priv_held = True

    owner_pids = []
    if inodes_to_uid:
        want_targets = set("socket:[%s]" % ino for ino in inodes_to_uid.keys())
        try:
            for entry in os.listdir(proc_root):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                if pid in (my_pid, my_ppid, 1):
                    continue
                fd_dir = os.path.join(proc_root, entry, "fd")
                try:
                    fds = os.listdir(fd_dir)
                except Exception:
                    continue
                for fd_n in fds:
                    try:
                        lnk = os.readlink(os.path.join(fd_dir, fd_n))
                        if lnk in want_targets:
                            if pid not in owner_pids:
                                owner_pids.append(pid)
                            break
                    except Exception:
                        continue
        except Exception:
            pass
    return owner_pids, priv_held


def _has_exec_in_path(bin_name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d:
            cand = os.path.join(d, bin_name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return True
    return False


def _is_scash_qt_running():
    if platform.system() == "Windows":
        try:
            CREATE_NO_WINDOW = 0x08000000
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq scash-qt.exe", "/NH"],
                creationflags=CREATE_NO_WINDOW,
            ).decode("utf-8", "replace").lower()
            return "scash-qt.exe" in out
        except Exception:
            return False
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            raw_cmd = open("/proc/%s/cmdline" % entry, "rb").read()
            parts = [x.decode("utf-8", "replace") for x in raw_cmd.split(b"\x00") if x]
            if parts and os.path.basename(parts[0]).lower() == "scash-qt":
                return True
    except Exception:
        pass
    return False


def _cleanup_stale_linux_processes(rpc_port, all_datadirs, conf_user, conf_pass):
    my_pid = os.getpid()
    my_ppid = os.getppid() if hasattr(os, "getppid") else -1
    my_uid = os.geteuid() if hasattr(os, "geteuid") else -1
    stale_launcher_pids = []
    stale_miner_pids = []
    stale_scashd_pids = []
    any_scash_core_pids = {}
    root_p2pool_pids = []
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
                p_uid = -1
                try:
                    for st_ln in open("/proc/%d/status" % pid, "r").read().splitlines():
                        if st_ln.startswith("Uid:"):
                            p_uid = int(st_ln.split()[1])
                            break
                except Exception:
                    pass
                if bn0 in ("scashd", "scash-qt"):
                    any_scash_core_pids[pid] = bn0
                if ("start_scash_p2pool.py" in low or "run_p2pool.py" in low) and "grep" not in bn0 and "sudo" not in bn0:
                    stale_launcher_pids.append(pid)
                    if my_uid > 0 and p_uid != -1 and p_uid != my_uid:
                        root_p2pool_pids.append(pid)
                elif bn0 in ("xmrigminer", "xmrigdaemon") and ("p2pool" in low or "127.0.0.1:8345" in low or "--daemonized" in low):
                    stale_miner_pids.append(pid)
                elif bn0 == "scashd" and ("scash-p2pool" in low or "/node/scashd" in low or "node_data" in low):
                    stale_scashd_pids.append(pid)
            except Exception:
                continue
    except Exception:
        return

    sock_8344_pids, priv_8344 = _find_linux_listening_socket_owners((8344,))
    sock_8345_pids, priv_8345 = _find_linux_listening_socket_owners((8345,))
    priv_sock = priv_8344 or priv_8345
    qt_holding_8344 = False
    for spid in sock_8344_pids + sock_8345_pids:
        core_kind = any_scash_core_pids.get(spid)
        if core_kind == "scash-qt":
            qt_holding_8344 = True
        elif core_kind == "scashd":
            # Headless scashd started with an older scash.conf is holding 127.0.0.1:8344=onion!
            if spid not in stale_scashd_pids:
                stale_scashd_pids.append(spid)
        elif spid not in stale_launcher_pids and spid not in stale_scashd_pids:
            stale_launcher_pids.append(spid)

    port_busy_initial = is_port_open("127.0.0.1", 8344, timeout=0.25) or is_port_open("127.0.0.1", 8345, timeout=0.25)
    if not (stale_launcher_pids or stale_miner_pids or stale_scashd_pids or priv_sock or port_busy_initial):
        return

    if stale_launcher_pids or stale_miner_pids:
        print("[1/3] Stopping leftover background P2Pool process from previous Linux session...")
        for pid in stale_launcher_pids + stale_miner_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    if stale_scashd_pids:
        print("[1/3] Stopping previous local scashd cleanly so updated scash.conf releases port 8344...")
        u, pw, ok, _, err = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass, rpc_timeout=3.0)
        if ok or (err and err.get("code") != -999):
            jsonrpc_call("127.0.0.1", rpc_port, u, pw, "stop", timeout=3.0)
        for pid in stale_scashd_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        for _ in range(25):
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

    if qt_holding_8344 and is_port_open("127.0.0.1", 8344, timeout=0.2):
        print("[1/3] Notice: Open Scash-Qt Wallet is holding port 8344 (Bitcoin Core 30.4 default 8343+1 Tor onion bind).")
        print("      scash.conf has been updated (bind=0.0.0.0:8343, listenonion=0).")
        print("      Please close & reopen Scash-Qt Wallet once so P2Pool can listen on port 8344!")
        return

    if _has_exec_in_path("fuser") and not any_scash_core_pids and (
        is_port_open("127.0.0.1", 8344, timeout=0.2) or is_port_open("127.0.0.1", 8345, timeout=0.2)
    ):
        devnull = open(os.devnull, "wb")
        try:
            subprocess.call(["fuser", "-k", "8344/tcp", "8345/tcp"], stdout=devnull, stderr=devnull)
        except Exception:
            pass
        finally:
            devnull.close()

    for _ in range(12):
        if (not is_port_open("127.0.0.1", 8345, timeout=0.2)) and (not is_port_open("127.0.0.1", 8344, timeout=0.2)):
            break
        time.sleep(0.25)

    # If port 8344 or 8345 is STILL held by an older root/sudo session, clear it via sudo (stopping root scashd cleanly first)!
    if is_port_open("127.0.0.1", 8344, timeout=0.25) or is_port_open("127.0.0.1", 8345, timeout=0.25):
        u_r, pw_r, ok_r, _, err_r = probe_working_credentials("127.0.0.1", rpc_port, all_datadirs, conf_user, conf_pass, rpc_timeout=2.5)
        if ok_r or (err_r and err_r.get("code") != -999):
            jsonrpc_call("127.0.0.1", rpc_port, u_r, pw_r, "stop", timeout=2.5)
            for _ in range(15):
                if not is_port_open("127.0.0.1", 8344, timeout=0.25):
                    break
                time.sleep(0.3)
        if (is_port_open("127.0.0.1", 8344, timeout=0.25) or is_port_open("127.0.0.1", 8345, timeout=0.25)) and my_uid > 0 and _has_exec_in_path("sudo"):
            sudo_clean_sh = "pkill -9 -f 'run_p2pool.py|start_scash_p2pool.py' 2>/dev/null || true; fuser -k 8345/tcp 2>/dev/null || true"
            if not _is_scash_qt_running():
                sudo_clean_sh += "; fuser -k 8344/tcp 2>/dev/null || true"
            devnull2 = open(os.devnull, "wb")
            try:
                subprocess.call(["sudo", "-n", "sh", "-c", sudo_clean_sh], stdout=devnull2, stderr=devnull2)
            except Exception:
                pass
            finally:
                devnull2.close()
            time.sleep(0.4)
            is_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
            is_tty = bool(hasattr(sys.stdin, "isatty") and sys.stdin.isatty() and hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
            if (is_port_open("127.0.0.1", 8344, timeout=0.25) or is_port_open("127.0.0.1", 8345, timeout=0.25)) and is_tty and not is_ci:
                print("[1/3] Port 8344 is held by an older root/sudo session%s." % ((" (PID %s)" % ",".join(str(x) for x in root_p2pool_pids)) if root_p2pool_pids else ""))
                print("      Enter your Linux sudo password once to free port 8344 cleanly:")
                try:
                    subprocess.call(["sudo", "sh", "-c", sudo_clean_sh])
                except Exception:
                    pass
                for _ in range(10):
                    if not is_port_open("127.0.0.1", 8344, timeout=0.25):
                        break
                    time.sleep(0.25)

    if is_port_open("127.0.0.1", 8344, timeout=0.25):
        print("[Notice] Port 8344 is still in use! Check with: sudo ss -tulpn | grep 8344")

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


def _lower_win32_process_priority(proc_obj):
    """Lowers background node/P2Pool processes to BELOW_NORMAL_PRIORITY_CLASS on Windows after sync so XMRig gets 100% physical-core priority."""
    if platform.system() != "Windows" or proc_obj is None:
        return
    try:
        pid = getattr(proc_obj, "pid", None)
        if not pid:
            return
        PROCESS_SET_INFORMATION = 0x0200
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, int(pid))
        if h_proc:
            try:
                ctypes.windll.kernel32.SetPriorityClass(h_proc, BELOW_NORMAL_PRIORITY_CLASS)
            finally:
                ctypes.windll.kernel32.CloseHandle(h_proc)
    except Exception:
        pass


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


def _datadir_conf_has_bind(datadir):
    if not datadir:
        return False
    cp = os.path.join(datadir, "scash.conf")
    if not os.path.isfile(cp):
        return False
    try:
        for raw in open(cp, "r").read().splitlines():
            s = raw.strip().lower()
            if s and not s.startswith("#") and (s.startswith("bind=") or s.startswith("whitebind=")):
                return True
    except Exception:
        pass
    return False


def start_bundled_scashd(scashd_bin, datadir, rpc_port=8342, p2p_port=None):
    eff_p2p = int(p2p_port) if p2p_port is not None else 8343
    eff_rpc = int(rpc_port)
    cmd = [
        scashd_bin,
        "-datadir=%s" % datadir,
        "-chain=scash",
        "-server=1",
        "-listen=1",
        "-listenonion=0",
        "-dnsseed=1",
        "-rpcport=%d" % eff_rpc,
        "-rpcbind=127.0.0.1",
        "-rpcallowip=127.0.0.1",
        "-port=%d" % eff_p2p,
    ]
    # Pass -bind=0.0.0.0:<eff_p2p> ONLY when scash.conf does not already set bind=
    # (prevents Core 30.4.0 from auto-binding 127.0.0.1:(port+1)=8344 for Tor onion
    # while never triggering CheckBindingConflicts duplicate -bind error!).
    if not _datadir_conf_has_bind(datadir):
        cmd.append("-bind=0.0.0.0:%d" % eff_p2p)
    if os.environ.get("SCASH_CI_OFFLINE_SCASHD") == "1":
        cmd.extend(["-connect=0", "-dnsseed=0"])
    else:
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

            if path == "/pool_telemetry":
                self._send_json({
                    "ok": True,
                    "syncing": True,
                    "version": "0.4.0",
                    "hashrates": {
                        "local_live_hs": 0.0, "local_10s_hs": 0.0, "local_60s_hs": 0.0, "local_30m_hs": 0.0,
                        "pool_live_hs": 0.0, "pool_10s_hs": 0.0, "pool_60s_hs": 0.0, "pool_30m_hs": 0.0,
                    },
                    "ledger": {
                        "wallet": ctrl.wallet or "",
                        "miner_scash_7d": 0.0, "miner_scash_30d": 0.0, "miner_scash_all_time": 0.0,
                        "miner_blocks_paid": 0, "pool_blocks_7d": 0, "pool_blocks_30d": 0,
                        "pool_blocks_all_time": 0, "pool_scash_all_time": 0.0,
                        "backfill_scanning": True, "recent_blocks": [],
                    },
                    "market": {
                        "ok": False,
                        "weighted_price_usd": None,
                        "block_value_usd": None,
                        "total_liquidity_usd": 0.0,
                        "total_volume_24h_usd": 0.0,
                        "exchanges": [
                            {"key": "ourbit", "name": "Ourbit", "pair": "SCASH/USDT", "price_usd": None, "weight_pct": 0.0, "url": "https://www.ourbit.com/exchange/SCASH_USDT"},
                            {"key": "nonkyc", "name": "NonKYC", "pair": "SCASH/USDT", "price_usd": None, "weight_pct": 0.0, "url": "https://nonkyc.io/market/SCASH_USDT"},
                            {"key": "nestex", "name": "NestEx", "pair": "SCASH/USDT", "price_usd": None, "weight_pct": 0.0, "url": "https://trade.nestex.one/spot/SCASH"},
                        ],
                        "reference_links": [
                            {"name": "Ourbit", "url": "https://www.ourbit.com/exchange/SCASH_USDT"},
                            {"name": "NonKYC", "url": "https://nonkyc.io/market/SCASH_USDT"},
                            {"name": "NestEx", "url": "https://trade.nestex.one/spot/SCASH"},
                            {"name": "CoinGecko", "url": "https://www.coingecko.com/en/coins/satoshi-cash-network"},
                        ],
                    },
                    "explorers": {
                        "active_key": "scash_network",
                        "active_name": "explorer.scash.network",
                        "active_url": "https://explorer.scash.network/",
                        "checked_at": 0,
                        "items": [
                            {"key": "scash_network", "name": "explorer.scash.network", "short": "scash.network", "home_url": "https://explorer.scash.network/", "block_tpl": "https://explorer.scash.network/block/{id}/20/1", "address_tpl": "https://explorer.scash.network/address/{id}/20/1", "online": True},
                            {"key": "scash_tv", "name": "scash.tv", "short": "scash.tv", "home_url": "https://scash.tv/", "block_tpl": "https://scash.tv/block/{id}", "address_tpl": "https://scash.tv/address/{id}", "online": True},
                            {"key": "local_node", "name": "Local Scash Node", "short": "Local Coinbase", "home_url": "/local_explorer", "block_tpl": "/local_explorer?block={id}", "address_tpl": "/local_explorer?address={id}", "online": True},
                        ],
                    },
                })
                return

            if path in ("/explorer_go", "/local_explorer"):
                qtype = (qs.get("type", [None])[0] or ("address" if qs.get("address") else "block")).strip().lower()
                qid = (qs.get("id", [None])[0] or qs.get("block", [None])[0] or qs.get("address", [None])[0] or "").strip()
                if qtype == "address" and qid:
                    qid = qid.split(".")[0]
                    dest_u = "https://explorer.scash.network/address/%s/20/1" % qid
                elif qid and len(qid) == 64:
                    dest_u = "https://explorer.scash.network/block/%s/20/1" % qid
                else:
                    dest_u = "https://explorer.scash.network/"
                self.send_response(302)
                self.send_header("Location", dest_u)
                self.end_headers()
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
    need_spawn_scashd = not (ok or (err and err.get("code") != -999))
    if not need_spawn_scashd:
        active_creds[0], active_creds[1] = u, pw
        if is_port_open("127.0.0.1", 8344, timeout=0.25):
            if (not _is_scash_qt_running()) and find_scashd_binary(args.scashd_bin):
                print("[1/3] Local scashd is holding port 8344 (Core 30.4 default 8343+1 onion bind) -- restarting scashd cleanly...")
                jsonrpc_call("127.0.0.1", rpc_port, u, pw, "stop", timeout=3.0)
                for _ in range(30):
                    if (not is_port_open("127.0.0.1", rpc_port, timeout=0.3)) and (not is_port_open("127.0.0.1", 8344, timeout=0.3)):
                        break
                    time.sleep(0.4)
                need_spawn_scashd = True
            else:
                print("[1/3] Notice: Open Scash-Qt Wallet is holding port 8344 (Core 30.4 default 8343+1 onion bind).")
                print("      scash.conf has been updated (bind=0.0.0.0:8343, listenonion=0) -- restart Scash-Qt once to free :8344!")
        if not need_spawn_scashd:
            print("[1/3] Connected to running local Scash node on 127.0.0.1:%d." % rpc_port)
    if need_spawn_scashd:
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
                if hdrs == 0:
                    dbg_msg, _, _ = _read_scash_debug_log_sync_hint(active_datadir, peers=peers)
                    if dbg_msg:
                        msg = dbg_msg
                    elif peers == 0:
                        msg = "Connecting to Scash Mainnet peers on :8343... (Peers: 0 - discovering network headers)"
                    else:
                        msg = "Connected to %d Scash peer(s) - pre-synchronizing RandomX block headers..." % peers
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
                eff_peers = peers if peers > 0 else int(sync_state.get("connections", 0))
                dbg_msg, _, _ = _read_scash_debug_log_sync_hint(active_datadir, peers=eff_peers)
                raw_warm = (bc_err or {}).get("message", "Starting Scash node...")
                is_rpc_timeout = "timed out" in str(raw_warm).lower()
                rpc_alive = is_port_open("127.0.0.1", active_creds[2], timeout=0.8)
                if dbg_msg and rpc_alive:
                    sync_state.update({
                        "syncing": True,
                        "p2pool_ready": False,
                        "connections": eff_peers,
                        "subversion": subver,
                        "datadir": active_datadir,
                        "status_text": dbg_msg,
                    })
                    print("      [Scash Node]", ascii_safe(dbg_msg))
                elif prev_hdrs > 0 and rpc_alive:
                    busy_msg = "Verifying RandomX block headers... (%d / %d blocks, headers: %d | Peers: %d)" % (prev_blks, prev_hdrs, prev_hdrs, eff_peers)
                    sync_state["connections"] = eff_peers
                    sync_state["status_text"] = busy_msg
                    print("      [Scash Node]", busy_msg)
                elif is_rpc_timeout and rpc_alive:
                    if eff_peers > 0:
                        busy_msg = "Verifying initial Scash RandomX block headers from %d peer(s) (CPU busy, first-time presync takes ~3-10 min)..." % eff_peers
                    else:
                        busy_msg = "Initializing Scash Core 30.4 RandomX header verifier..."
                    sync_state.update({
                        "syncing": True,
                        "p2pool_ready": False,
                        "connections": eff_peers,
                        "subversion": subver,
                        "datadir": active_datadir,
                        "status_text": busy_msg,
                    })
                    print("      [Scash Node]", busy_msg)
                else:
                    warm_msg = ascii_safe(raw_warm)
                    sync_state.update({
                        "syncing": True,
                        "p2pool_ready": False,
                        "connections": eff_peers,
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
    node_fallback_wallet = ctrl.wallet
    if not node_fallback_wallet:
        from p2pool.bitcoin import bech32_scash as _fb_b32
        _fb_file = os.path.join(ROOT_DIR, "miner", "node_bootstrap_addr.txt")
        if os.path.isfile(_fb_file):
            try:
                node_fallback_wallet = open(_fb_file, "r").read().strip()
            except Exception:
                node_fallback_wallet = ""
        if not (node_fallback_wallet and node_fallback_wallet.startswith("scash1") and len(node_fallback_wallet) >= 40):
            node_fallback_wallet = _fb_b32.encode_scash_address(os.urandom(20), "scash")
            try:
                if not os.path.isdir(os.path.dirname(_fb_file)):
                    os.makedirs(os.path.dirname(_fb_file))
                open(_fb_file, "w").write(node_fallback_wallet + "\n")
            except Exception:
                pass

    def _post_p2pool_ready():
        for _ in range(45):
            if shutting_down[0]:
                return
            if is_port_open("127.0.0.1", 8345):
                if (not args.no_browser) and (not browser_opened[0]):
                    open_dashboard_browser(ui_url)
                    browser_opened[0] = True
                if ctrl.wallet and ctrl.wallet.lower().startswith(("scash1", "tcash1")) and len(ctrl.wallet) >= 26:
                    # Wait for initial P2Pool sharechain download/verification so XMRig doesn't mine genesis-diff stales!
                    last_wait_log = 0.0
                    for _w_idx in range(75):
                        if shutting_down[0]:
                            return
                        try:
                            raw_tel = _NO_PROXY_OPENER.open("http://127.0.0.1:8345/pool_telemetry", timeout=3.0).read()
                            tel_obj = json.loads(raw_tel.decode("utf-8", "replace")) or {}
                            sc_st = tel_obj.get("sharechain_sync") or {}
                            if not sc_st.get("syncing"):
                                break
                            now_lg = time.time()
                            if (now_lg - last_wait_log) >= 5.0:
                                print("[3/3] %s (holding XMRig start so startup shares aren't orphaned)" % ascii_safe(sc_st.get("status_text") or "Syncing P2Pool sharechain..."))
                                last_wait_log = now_lg
                        except Exception:
                            break
                        time.sleep(1.0)
                    try:
                        start_url = "http://127.0.0.1:8345/miner_start?wallet=%s" % ctrl.wallet
                        if getattr(ctrl, "custom_threads", False):
                            start_url += "&threads=%d" % int(ctrl.threads)
                        _NO_PROXY_OPENER.open(start_url, timeout=5.0).read()
                        print("[3/3] Sharechain ready! Auto-started local XMRig worker on 127.0.0.1:8345 for:", ascii_safe(ctrl.wallet))
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
        "--give-author", "0",
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
