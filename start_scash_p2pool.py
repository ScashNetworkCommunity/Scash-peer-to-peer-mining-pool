#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.4.1).
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


def _native_str(val):
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    try:
        if sys.version_info[0] < 3:
            fs_enc = sys.getfilesystemencoding() or "utf-8"
            return val.encode(fs_enc, "replace")
        return val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
    except Exception:
        return ascii_safe(val)


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
KAWAII_ANSI_HIRES_ZB64 = "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"
KAWAII_ANSI_BANNER_ZB64 = "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"

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.4.1)          Core 30.4.0 |
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
            err_obj = err_body.get("error") or {"code": e.code, "message": ascii_safe(e)}
            return False, None, err_obj
        except Exception:
            return False, None, {"code": e.code, "message": ascii_safe(e)}
    except Exception as e:
        return False, None, {"code": -999, "message": ascii_safe(e)}


def is_mainnet_node_synced(bc_info, net_info=None, peer_info=None, allow_unsynced=False):
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
        if peers <= 0:
            return False
        if isinstance(peer_info, list) and peer_info:
            max_peer_h = 0
            for p_obj in peer_info:
                if isinstance(p_obj, dict):
                    for hk in ("synced_headers", "synced_blocks", "startingheight"):
                        try:
                            hv = int(p_obj.get(hk) or 0)
                            if hv > max_peer_h:
                                max_peer_h = hv
                        except Exception:
                            pass
            if max_peer_h > 0 and blks < (max_peer_h - 1):
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
            if err.get("code") == -999 and "timed out" in ascii_safe(err.get("message", "")).lower():
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
    extra_scash_peers = []
    for rel_j in (
        os.path.join("data", "scash", "lan_scash_peers.json"),
        os.path.join("data", "scash", "p2pool_verified_peers.json"),
    ):
        jp = os.path.join(ROOT_DIR, rel_j)
        if os.path.isfile(jp):
            try:
                arr = json.loads(open(jp, "r").read())
                if isinstance(arr, list):
                    for ent in arr[:16]:
                        ip_s = ""
                        if isinstance(ent, dict):
                            ip_s = ascii_safe(ent.get("ip", "")).strip()
                        elif isinstance(ent, (str, type(u""))):
                            ip_s = ascii_safe(ent).strip().split(":")[0]
                        if ip_s and not ip_s.startswith("127."):
                            cand = "%s:8343" % ip_s
                            if cand not in extra_scash_peers:
                                extra_scash_peers.append(cand)
            except Exception:
                pass
    for peer in extra_scash_peers + list(scash_nodes.DEFAULT_SCASH_ADDNODES):
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
                    "version": "0.4.1",
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
    _, init_peers, _ = jsonrpc_call("127.0.0.1", active_creds[2], active_creds[0], active_creds[1], "getpeerinfo", timeout=4.0)
    already_synced = is_mainnet_node_synced(init_bc, init_net, peer_info=init_peers, allow_unsynced=args.allow_unsynced)
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
                elif peers <= 0 and blks >= max(1, hdrs - 1):
                    msg = "Connecting to Scash peers on :8343 to verify latest block tip (#%d, Peers: 0)..." % blks
                else:
                    msg = "Syncing Scash blockchain: %d / %d blocks (%.1f%%) | Peers: %d" % (blks, hdrs, pct, peers)
                peer_info_now = None
                if peers > 0:
                    _, peer_info_now, _ = jsonrpc_call("127.0.0.1", active_creds[2], u, pw, "getpeerinfo", timeout=4.0)
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
                if is_mainnet_node_synced(bc_info, net_info, peer_info=peer_info_now, allow_unsynced=args.allow_unsynced):
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
                is_rpc_timeout = "timed out" in ascii_safe(raw_warm).lower()
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
    p2pool_env["SCASH_ACTIVE_DATADIR"] = _native_str(active_datadir)
    p2pool_env["SCASH_RPC_PORT"] = str(active_creds[2])
    p2pool_env["SCASH_RPC_USER"] = _native_str(active_creds[0])
    p2pool_env["SCASH_RPC_PASS"] = _native_str(active_creds[1])

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
    p2pool_cmd.extend([_native_str(active_creds[0]), _native_str(active_creds[1])])

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
