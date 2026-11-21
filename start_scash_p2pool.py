#!/usr/bin/env python
"""
Sovereign Full-Stack Launcher for Scash P2Pool (QtKawaii Edition v0.3.10).
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
)

KAWAII_ASCII_FALLBACK = """+------------------------------------------------------------------------------+
| [Scash] Scash P2Pool - peer2peer-pool (QtKawaii v0.3.10)          Core 30.4.0 |
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
        "-uacomment=p2pool",
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
                    "version": "0.3.10",
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
