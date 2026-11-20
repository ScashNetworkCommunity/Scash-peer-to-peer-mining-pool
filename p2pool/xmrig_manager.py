"""
Local CPU Miner Controller for Scash P2Pool (QtKawaii Edition v0.3.7).
Manages local xmrigDaemon + xmrigMiner (rx/scash, built with -DWITH_MSR=ON,
-DWITH_ASM=ON, WinRing0x64.sys, HugePages, and hwloc physical-core affinity)
connecting strictly to 127.0.0.1:8345 and reports 100% real live process status,
hashrate (H/s), MSR/HugePages state, accepted shares, and stdout logs.
Compatible with PyPy 2.7 and Python 3.x.
"""
from __future__ import print_function
import json
import multiprocessing
import os
import platform
import re
import subprocess
import threading
import time

try:
    import urllib.request as urllib_req
except ImportError:
    import urllib2 as urllib_req

MINER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "miner"))
WALLET_STATE_FILE = os.path.join(MINER_DIR, "wallet_config.json")
XMRIG_CONFIG_FILE = os.path.join(MINER_DIR, "config.json")
_NO_PROXY_OPENER = urllib_req.build_opener(urllib_req.ProxyHandler({}))

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_SPEED_RE = re.compile(
    r"speed\s+\S+\s+([0-9]+(?:\.[0-9]+)?|n/a)(?:\s+([0-9]+(?:\.[0-9]+)?|n/a))?(?:\s+([0-9]+(?:\.[0-9]+)?|n/a))?",
    re.IGNORECASE,
)
_ACCEPT_RE = re.compile(r"accepted\s*\((\d+)/(\d+)\)", re.IGNORECASE)
_TOTAL_ACC_RE = re.compile(r"Total accepted:\s*(\d+)", re.IGNORECASE)
_HTTP_API_RE = re.compile(r"HTTP API\s+127\.0\.0\.1:(\d+)", re.IGNORECASE)


def _enable_os_hugepages_privilege(enable=True):
    """Enables Windows SeLockMemoryPrivilege on current token (for 2MB HugePages) or Linux vm.nr_hugepages when root."""
    if not enable:
        return
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            class LUID(ctypes.Structure):
                _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

            class LUID_AND_ATTRIBUTES(ctypes.Structure):
                _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

            class TOKEN_PRIVILEGES(ctypes.Structure):
                _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

            advapi32 = ctypes.windll.advapi32
            kernel32 = ctypes.windll.kernel32
            TOKEN_ADJUST_PRIVILEGES = 0x0020
            TOKEN_QUERY = 0x0008
            SE_PRIVILEGE_ENABLED = 0x00000002

            h_token = wintypes.HANDLE()
            if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(h_token)):
                try:
                    luid = LUID()
                    if advapi32.LookupPrivilegeValueW(None, u"SeLockMemoryPrivilege", ctypes.byref(luid)):
                        tp = TOKEN_PRIVILEGES()
                        tp.PrivilegeCount = 1
                        tp.Privileges[0].Luid = luid
                        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
                        advapi32.AdjustTokenPrivileges(h_token, False, ctypes.byref(tp), 0, None, None)
                finally:
                    kernel32.CloseHandle(h_token)
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            if hasattr(os, "geteuid") and os.geteuid() == 0 and os.path.isfile("/proc/sys/vm/nr_hugepages"):
                cur_hp = int(open("/proc/sys/vm/nr_hugepages", "r").read().strip() or "0")
                if cur_hp < 1280:
                    with open("/proc/sys/vm/nr_hugepages", "w") as hf:
                        hf.write("1280\n")
        except Exception:
            pass


def _repair_stale_windows_winring0_service(bin_dir):
    """Cleans up stale Windows WinRing0_1_2_0 service entries pointing at old/deleted release folders."""
    if platform.system() != "Windows":
        return False
    expected_sys = os.path.abspath(os.path.join(bin_dir, "WinRing0x64.sys"))
    if not os.path.isfile(expected_sys):
        return False
    try:
        p = subprocess.Popen(
            ["sc", "qc", "WinRing0_1_2_0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=0x08000000,
        )
        out_b, _ = p.communicate()
        if p.returncode != 0:
            return False
        out_txt = out_b.decode("utf-8", "replace")
        m_path = re.search(r"BINARY_PATH_NAME\s*:\s*(.+)", out_txt, re.IGNORECASE)
        if not m_path:
            return False
        reg_raw = m_path.group(1).strip().strip('"')
        if reg_raw.startswith("\\??\\"):
            reg_raw = reg_raw[4:]
        reg_norm = os.path.normcase(os.path.abspath(reg_raw))
        exp_norm = os.path.normcase(expected_sys)
        if reg_norm != exp_norm or not os.path.isfile(reg_raw):
            devnull = open(os.devnull, "wb")
            subprocess.call(["sc", "stop", "WinRing0_1_2_0"], stdout=devnull, stderr=devnull, creationflags=0x08000000)
            time.sleep(0.15)
            subprocess.call(["sc", "delete", "WinRing0_1_2_0"], stdout=devnull, stderr=devnull, creationflags=0x08000000)
            time.sleep(0.15)
            return True
    except Exception:
        pass
    return False


class LocalMinerController(object):
    def __init__(self, stratum_host="127.0.0.1", stratum_port=8345):
        self.stratum_host = stratum_host
        self.stratum_port = int(stratum_port)
        self.process = None
        self.wallet = ""
        self.worker = "kawaii_rig01"
        self.max_cpu_threads = max(1, int(multiprocessing.cpu_count() or 8))
        self.threads = self.max_cpu_threads
        self.custom_threads = False
        self.active_threads = self.threads
        self.large_pages = True
        self.msr_active = None
        self.msr_blocked_reason = None
        self.hugepages_active = None
        self.http_port = 8346
        self.hashrate_hs = 0.0
        self.hashrate_60s_raw = 0.0
        self.hashrate_15m_raw = 0.0
        self._hr_samples = []
        self.accepted_shares = 0
        self.rejected_shares = 0
        self.logs = []
        self.lock = threading.Lock()
        self._load_saved_wallet()

    def _load_saved_wallet(self):
        if os.path.exists(WALLET_STATE_FILE):
            try:
                data = json.load(open(WALLET_STATE_FILE, "r"))
                w = (data.get("wallet") or "").strip()
                self.wallet = w
                self.worker = (data.get("worker") or "kawaii_rig01").strip()
                # Migrate pre-v0.3.4 configs where cpu_count()//2 accidentally locked -t 8 custom_threads!
                if data.get("xmrig_autoconfig_v2"):
                    self.custom_threads = bool(data.get("custom_threads", False))
                    if self.custom_threads:
                        self.threads = max(1, min(self.max_cpu_threads, int(data.get("threads", self.max_cpu_threads))))
                    else:
                        self.threads = self.max_cpu_threads
                else:
                    self.custom_threads = False
                    self.threads = self.max_cpu_threads
                self.active_threads = self.threads
                self.large_pages = bool(data.get("large_pages", True))
            except Exception:
                pass

    def save_wallet_settings(self, wallet, threads=None, worker=None, large_pages=None):
        if not os.path.exists(MINER_DIR):
            os.makedirs(MINER_DIR)
        if wallet is not None:
            self.wallet = wallet.strip()
        if threads is not None and str(threads).strip() != "":
            t_raw = str(threads).strip().lower()
            if t_raw in ("auto", "max", "default", "0", "-1"):
                self.custom_threads = False
                self.threads = self.max_cpu_threads
                self.active_threads = self.max_cpu_threads
            else:
                try:
                    t_val = int(t_raw)
                    if t_val >= self.max_cpu_threads:
                        self.custom_threads = False
                        self.threads = self.max_cpu_threads
                        self.active_threads = self.max_cpu_threads
                    elif t_val > 0:
                        self.threads = t_val
                        self.active_threads = t_val
                        self.custom_threads = True
                except Exception:
                    pass
        if worker:
            self.worker = worker.strip()
        if large_pages is not None:
            if isinstance(large_pages, str):
                self.large_pages = large_pages.lower() in ("1", "true", "yes", "on")
            else:
                self.large_pages = bool(large_pages)
        payload = {
            "wallet": self.wallet,
            "worker": self.worker,
            "threads": self.threads,
            "custom_threads": self.custom_threads,
            "xmrig_autoconfig_v2": True,
            "large_pages": self.large_pages,
            "updated_at": int(time.time()),
        }
        with open(WALLET_STATE_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        return payload

    def build_xmrig_config(self):
        if not os.path.exists(MINER_DIR):
            os.makedirs(MINER_DIR)
        # Do NOT append SHA-256 ASIC +diff/share_diff suffixes! Let P2Pool's native RandomX MAX_TARGET & vardiff tune share rate automatically.
        stratum_user = "%s.%s" % (self.wallet, self.worker)

        is_win = platform.system() == "Windows"
        # IMPORTANT: Do NOT set "rx": [0, 1, 2, ...] in "cpu"!
        # Letting XMRigCC's libhwloc auto-configure maps 1 thread per physical core
        # matching L2/L3 cache (instead of pinning onto SMT hyperthreads of half the CPU),
        # while enabling Ring0 MSR prefetcher tuning (rdmsr/wrmsr via WinRing0x64.sys or /dev/cpu/*/msr)
        # and 2MB/1GB HugePages + JIT HugePages + x86-64 assembly!
        cpu_cfg = {
            "enabled": True,
            "huge-pages": bool(self.large_pages),
            "huge-pages-jit": bool(self.large_pages),
            "hw-aes": None,
            "priority": None,
            "memory-pool": bool(self.large_pages),
            "yield": True,
            "asm": True,
            "max-threads-hint": 100,
        }
        cfg = {
            "autosave": False,
            "cc-client": {
                "enabled": False,
            },
            "randomx": {
                "init": -1,
                "init-avx2": -1,
                "mode": "auto",
                "1gb-pages": bool(self.large_pages and not is_win),
                "rdmsr": True,
                "wrmsr": True,
                "cache_qos": False,
                "numa": True,
                "scratchpad_prefetch_mode": 1,
            },
            "cpu": cpu_cfg,
            "http": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 8346,
                "restricted": True,
            },
            "print-time": 5,
            "donate-level": 0,
            "pools": [
                {
                    "algo": "rx/scash",
                    "url": "%s:%d" % (self.stratum_host, self.stratum_port),
                    "user": stratum_user,
                    "pass": "x",
                    "rig-id": self.worker,
                    "nicehash": False,
                    "keepalive": True,
                    "enabled": True,
                    "tls": False,
                }
            ],
        }
        with open(XMRIG_CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        return XMRIG_CONFIG_FILE, stratum_user

    def find_miner_binary(self):
        is_win = platform.system() == "Windows"
        # Prioritize xmrigDaemon FIRST: per XMRigCC architecture, xmrigDaemon enables
        # Windows SeLockMemoryPrivilege (HugePages) and spawns/supervises xmrigMiner!
        # Launch xmrigMiner directly with --daemonized --cc-disabled (bypasses XMRigd.cpp Windows cmd.exe /c quote stripping
        # while still activating WinRing0x64.sys MSR tuning, SeLockMemoryPrivilege HugePages, and libhwloc physical-core binding)!
        candidates = (
            ["xmrigMiner.exe", "xmrig.exe", "xmrigDaemon.exe", "minerd.exe", "cpuminer-scash.exe"]
            if is_win
            else ["xmrigMiner", "xmrig", "xmrigDaemon", "minerd", "cpuminer-scash"]
        )
        search_dirs = [
            MINER_DIR,
            os.path.join(MINER_DIR, "bin"),
            os.path.abspath(os.path.join(MINER_DIR, "..")),
        ]
        for p in os.environ.get("PATH", "").split(os.pathsep):
            if p:
                search_dirs.append(p)
        for name in candidates:
            for d in search_dirs:
                full = os.path.join(d, name)
                if os.path.isfile(full) and (is_win or os.access(full, os.X_OK)):
                    return full
        return None

    def _append_log(self, line):
        clean = _ANSI_RE.sub("", line).rstrip()
        if not clean:
            return
        low = clean.lower()
        m_spd = _SPEED_RE.search(clean)
        m_acc = _ACCEPT_RE.search(clean)
        m_tot = _TOTAL_ACC_RE.search(clean)
        m_http = _HTTP_API_RE.search(clean)
        with self.lock:
            if m_http:
                try:
                    self.http_port = int(m_http.group(1))
                except Exception:
                    pass
            if m_spd:
                try:
                    g1 = m_spd.group(1)
                    if g1 and g1.lower() != "n/a":
                        v10 = float(g1)
                        self.hashrate_hs = v10
                        self._record_hr_sample_locked(v10)
                    g2 = m_spd.group(2)
                    if g2 and g2.lower() != "n/a":
                        self.hashrate_60s_raw = float(g2)
                    g3 = m_spd.group(3)
                    if g3 and g3.lower() != "n/a":
                        self.hashrate_15m_raw = float(g3)
                except Exception:
                    pass
            if m_acc:
                try:
                    self.accepted_shares = int(m_acc.group(1))
                    self.rejected_shares = int(m_acc.group(2))
                except Exception:
                    pass
            elif m_tot:
                try:
                    self.accepted_shares = int(m_tot.group(1))
                except Exception:
                    pass
            if "register values set" in low or ("msr" in low and "preset" in low):
                self.msr_active = True
                self.msr_blocked_reason = None
            elif "cannot set msr" in low or "failed to apply msr" in low:
                self.msr_active = False
                if not self.msr_blocked_reason:
                    self.msr_blocked_reason = "vbs_or_hv"
            elif "failed to start winring0" in low or "cannot open winring0" in low:
                self.msr_active = False
                self.msr_blocked_reason = "driver_blocked"
            if "huge pages" in low:
                if "100%" in low or "supported" in low:
                    self.hugepages_active = True
                elif "unavailable" in low or "0%" in low or "permission granted" in low:
                    if "unavailable" in low or "0%" in low:
                        self.hugepages_active = False
            self.logs.append(clean)
            if len(self.logs) > 60:
                self.logs = self.logs[-60:]

    def _reader_thread(self, proc):
        try:
            for line in iter(proc.stdout.readline, b""):
                if not line:
                    break
                text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
                self._append_log(text)
        except Exception:
            pass
        finally:
            with self.lock:
                if self.process is proc:
                    self.hashrate_hs = 0.0
                    self.hashrate_60s_raw = 0.0
                    self.hashrate_15m_raw = 0.0
                    self._hr_samples = []

    def _record_hr_sample_locked(self, hs_val, now_ts=None):
        t_now = float(now_ts if now_ts is not None else time.time())
        v = max(0.0, float(hs_val or 0.0))
        if v <= 0.0:
            return
        if self._hr_samples and (t_now - self._hr_samples[-1][0]) < 0.9:
            self._hr_samples[-1] = (t_now, v)
        else:
            self._hr_samples.append((t_now, v))
        cutoff = t_now - 2100.0
        if len(self._hr_samples) > 32 and self._hr_samples[0][0] < cutoff:
            self._hr_samples = [ item for item in self._hr_samples if item[0] >= cutoff ]

    def _window_avg_locked(self, window_sec, now_ts=None):
        if not self._hr_samples:
            return 0.0
        t_now = float(now_ts if now_ts is not None else time.time())
        cutoff = t_now - float(window_sec)
        vals = [ item[1] for item in self._hr_samples if item[0] >= cutoff ]
        if not vals:
            return float(self._hr_samples[-1][1])
        return sum(vals) / float(len(vals))

    def _summary_poller_thread(self, proc):
        while proc.poll() is None and self.process is proc:
            self._poll_xmrig_http_summary()
            time.sleep(1.5)

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def _poll_xmrig_http_summary(self):
        if not self.is_running():
            return
        try:
            raw = _NO_PROXY_OPENER.open("http://127.0.0.1:%d/2/summary" % int(self.http_port or 8346), timeout=0.6).read()
            data = json.loads(raw.decode("utf-8", "replace"))
            hr_obj = data.get("hashrate") or {}
            totals = hr_obj.get("total") or []
            th_list = hr_obj.get("threads")
            with self.lock:
                if len(totals) >= 1 and totals[0] is not None:
                    self.hashrate_hs = float(totals[0])
                    self._record_hr_sample_locked(self.hashrate_hs)
                if len(totals) >= 2 and totals[1] is not None:
                    self.hashrate_60s_raw = float(totals[1])
                if len(totals) >= 3 and totals[2] is not None:
                    self.hashrate_15m_raw = float(totals[2])
                if isinstance(th_list, list) and len(th_list) > 0:
                    self.active_threads = len(th_list)
                hp = data.get("hugepages")
                if isinstance(hp, bool):
                    self.hugepages_active = hp
                elif isinstance(hp, list) and len(hp) >= 2:
                    self.hugepages_active = (hp[0] > 0)
            res_obj = data.get("results") or {}
            if "shares_good" in res_obj:
                with self.lock:
                    self.accepted_shares = int(res_obj.get("shares_good", 0))
                    total_sh = int(res_obj.get("shares_total", self.accepted_shares))
                    self.rejected_shares = max(0, total_sh - self.accepted_shares)
        except Exception:
            pass

    def start_mining(self, wallet=None, threads=None, worker=None, large_pages=None):
        if wallet is not None or threads is not None or worker is not None or large_pages is not None:
            self.save_wallet_settings(wallet if wallet is not None else self.wallet, threads, worker, large_pages)
        if not self.wallet or not self.wallet.lower().startswith(("scash1", "tcash1")) or len(self.wallet) < 20:
            return {
                "ok": False,
                "running": False,
                "error": "Paste your real scash1... Bech32 receive address from Scash Wallet first.",
            }

        self.stop_mining()
        cfg_path, stratum_user = self.build_xmrig_config()
        binary = self.find_miner_binary()
        if not binary:
            self._append_log("[Miner] Saved miner/config.json (NodeOnly edition). Connect external miner to stratum+tcp://127.0.0.1:%d" % self.stratum_port)
            st = self.get_status()
            st["notice"] = "Saved miner/config.json (NodeOnly edition — point external miner at stratum+tcp://127.0.0.1:8345)"
            return st

        bname = os.path.basename(binary).lower()
        bin_dir = os.path.dirname(os.path.abspath(binary))
        if "minerd" in bname or "cpuminer" in bname:
            cmd = [
                binary, "-a", "randomx",
                "-o", "stratum+tcp://%s:%d" % (self.stratum_host, self.stratum_port),
                "-u", stratum_user, "-p", "x",
                "--threads=%d" % self.threads,
            ]
            if self.large_pages:
                cmd.append("--largepages")
        else:
            cmd = [binary]
            if "xmrigminer" in bname:
                cmd.extend(["--daemonized", "--cc-disabled"])
            elif "daemon" in bname:
                cmd.append("--cc-disabled")
            cmd.extend([
                "--config=%s" % cfg_path,
                "-a", "rx/scash",
                "-o", "%s:%d" % (self.stratum_host, self.stratum_port),
                "-u", stratum_user, "-p", "x",
                "--print-time=5",
                "--no-color",
                "--http-enabled",
                "--http-host=127.0.0.1",
                "--http-port=8346",
            ])
            if self.custom_threads:
                cmd.extend(["-t", str(self.threads)])

        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "cwd": bin_dir}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW (XMRig worker threads default to friendly priority so P2Pool reactor never lags)
        _enable_os_hugepages_privilege(self.large_pages)
        repaired_wr0 = _repair_stale_windows_winring0_service(bin_dir)
        try:
            with self.lock:
                self.hashrate_hs = 0.0
                self.hashrate_60s_raw = 0.0
                self.hashrate_15m_raw = 0.0
                self._hr_samples = []
            self.msr_active = None
            self.msr_blocked_reason = None
            self.hugepages_active = None
            if repaired_wr0:
                self._append_log("[Miner] Repaired stale Windows WinRing0_1_2_0 driver path from an older folder.")
            self.process = subprocess.Popen(cmd, **kwargs)
            mode_desc = ("%d threads" % self.threads) if self.custom_threads else "Auto Optimal L2/L3 Cache + MSR + HugePages"
            self._append_log("[Miner] Launched %s (%s) -> 127.0.0.1:%d" % (os.path.basename(binary), mode_desc, self.stratum_port))
            t = threading.Thread(target=self._reader_thread, args=(self.process,))
            t.daemon = True
            t.start()
            tp = threading.Thread(target=self._summary_poller_thread, args=(self.process,))
            tp.daemon = True
            tp.start()
            return self.get_status()
        except Exception as e:
            self.process = None
            self._append_log("[Miner] Failed to launch miner: %s" % str(e))
            st = self.get_status()
            st["ok"] = False
            st["error"] = str(e)
            return st

    def stop_mining(self):
        proc = self.process
        self.process = None
        with self.lock:
            self.hashrate_hs = 0.0
            self.hashrate_60s_raw = 0.0
            self.hashrate_15m_raw = 0.0
            self._hr_samples = []
        if proc is not None and proc.poll() is None:
            pid = proc.pid
            try:
                if platform.system() == "Windows" and pid:
                    devnull = open(os.devnull, "wb")
                    subprocess.call(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=devnull,
                        stderr=devnull,
                        creationflags=0x08000000,
                    )
                else:
                    if pid:
                        subprocess.call(["pkill", "-TERM", "-P", str(pid)])
                    proc.terminate()
                for _ in range(12):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.15)
                if proc.poll() is None:
                    if platform.system() != "Windows" and pid:
                        subprocess.call(["pkill", "-KILL", "-P", str(pid)])
                    proc.kill()
            except Exception:
                pass
            self._append_log("[Miner] Stopped local miner process tree.")
        return self.get_status()

    def get_status(self):
        alive = self.is_running()
        if not alive:
            self.hashrate_hs = 0.0
        binary = self.find_miner_binary()
        winring0_present = os.path.isfile(os.path.join(MINER_DIR, "WinRing0x64.sys"))
        with self.lock:
            logs_copy = list(self.logs[-25:])
            if alive:
                now_t = time.time()
                hr10 = float(self.hashrate_hs) if self.hashrate_hs > 0 else self._window_avg_locked(10.0, now_t)
                hr60 = float(self.hashrate_60s_raw) if self.hashrate_60s_raw > 0 else self._window_avg_locked(60.0, now_t)
                roll30 = self._window_avg_locked(1800.0, now_t)
                span_s = (now_t - self._hr_samples[0][0]) if len(self._hr_samples) >= 2 else 0.0
                if roll30 > 0 and (span_s >= 900.0 or self.hashrate_15m_raw <= 0):
                    hr30m = roll30
                elif self.hashrate_15m_raw > 0:
                    hr30m = float(self.hashrate_15m_raw)
                else:
                    hr30m = hr60 if hr60 > 0 else hr10
                hr = round(hr10, 2)
                hr_10s = round(hr10, 2)
                hr_60s = round(hr60 if hr60 > 0 else hr10, 2)
                hr_30m = round(hr30m if hr30m > 0 else hr_60s, 2)
            else:
                hr = 0.0
                hr_10s = 0.0
                hr_60s = 0.0
                hr_30m = 0.0
            acc = int(self.accepted_shares)
            rej = int(self.rejected_shares)
            act_th = int(self.active_threads if alive else self.threads)
            msr_st = self.msr_active
            msr_reason = self.msr_blocked_reason
            hp_st = self.hugepages_active
        return {
            "ok": True,
            "running": alive,
            "algo": "rx/scash",
            "config_path": XMRIG_CONFIG_FILE,
            "pid": self.process.pid if alive and self.process else None,
            "binary": os.path.basename(binary) if binary else None,
            "has_binary": bool(binary),
            "winring0_bundled": winring0_present,
            "msr_active": msr_st,
            "msr_blocked_reason": msr_reason,
            "hugepages_active": hp_st,
            "wallet": self.wallet,
            "worker": self.worker,
            "threads": act_th,
            "custom_threads": self.custom_threads,
            "max_threads": multiprocessing.cpu_count() or 16,
            "large_pages": self.large_pages,
            "hashrate_hs": hr,
            "hashrate_10s_hs": hr_10s,
            "hashrate_60s_hs": hr_60s,
            "hashrate_30m_hs": hr_30m,
            "accepted_shares": acc,
            "rejected_shares": rej,
            "stratum_url": "stratum+tcp://%s:%d" % (self.stratum_host, self.stratum_port),
            "logs": logs_copy,
        }


GLOBAL_XMRIG = LocalMinerController()
