"""
Local CPU Miner Controller for Scash P2Pool (QtKawaii Edition v0.2.0-beta.5).
Manages local xmrigMiner (rx/scash) or cpuminer-scash connecting strictly to
127.0.0.1:8345 and reports 100% real live process status, hashrate (H/s),
accepted shares, and stdout logs. Compatible with PyPy 2.7 and Python 3.x.
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
_SPEED_RE = re.compile(r"speed\s+\S+\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_ACCEPT_RE = re.compile(r"accepted\s*\((\d+)/(\d+)\)", re.IGNORECASE)


class LocalMinerController(object):
    def __init__(self, stratum_host="127.0.0.1", stratum_port=8345):
        self.stratum_host = stratum_host
        self.stratum_port = int(stratum_port)
        self.process = None
        self.wallet = ""
        self.worker = "kawaii_rig01"
        self.threads = max(1, (multiprocessing.cpu_count() or 4) // 2)
        self.large_pages = True
        self.hashrate_hs = 0.0
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
                self.threads = max(1, int(data.get("threads", self.threads)))
                self.large_pages = bool(data.get("large_pages", True))
            except Exception:
                pass

    def save_wallet_settings(self, wallet, threads=None, worker=None, large_pages=None):
        if not os.path.exists(MINER_DIR):
            os.makedirs(MINER_DIR)
        if wallet is not None:
            self.wallet = wallet.strip()
        if threads is not None:
            try:
                self.threads = max(1, int(threads))
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
            "large_pages": self.large_pages,
            "updated_at": int(time.time()),
        }
        with open(WALLET_STATE_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        return payload

    def build_xmrig_config(self):
        if not os.path.exists(MINER_DIR):
            os.makedirs(MINER_DIR)
        est_hs = self.threads * (530 if self.large_pages else 290)
        pseudo_diff = max(0.0005, (est_hs * 10.0) / 10000000.0)
        share_diff = max(0.01, (est_hs * 15.0) / 550000.0)
        stratum_user = "%s.%s+%.4f/%.2f" % (self.wallet, self.worker, pseudo_diff, share_diff)

        cfg = {
            "autosave": False,
            "cpu": {
                "enabled": True,
                "huge-pages": self.large_pages,
                "rx": list(range(self.threads)),
            },
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
        candidates = (
            ["xmrigMiner.exe", "xmrigDaemon.exe", "xmrig.exe", "minerd.exe", "cpuminer-scash.exe"]
            if is_win
            else ["xmrigMiner", "xmrigDaemon", "xmrig", "minerd", "cpuminer-scash"]
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
        m_spd = _SPEED_RE.search(clean)
        m_acc = _ACCEPT_RE.search(clean)
        with self.lock:
            if m_spd:
                try:
                    self.hashrate_hs = float(m_spd.group(1))
                except Exception:
                    pass
            if m_acc:
                try:
                    self.accepted_shares = int(m_acc.group(1))
                    self.rejected_shares = int(m_acc.group(2))
                except Exception:
                    pass
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

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def _poll_xmrig_http_summary(self):
        if not self.is_running():
            return
        try:
            raw = _NO_PROXY_OPENER.open("http://127.0.0.1:8346/2/summary", timeout=0.6).read()
            data = json.loads(raw.decode("utf-8", "replace"))
            hr_obj = data.get("hashrate") or {}
            totals = hr_obj.get("total") or []
            if totals and totals[0] is not None:
                with self.lock:
                    self.hashrate_hs = float(totals[0])
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
            cmd = [
                binary, "-a", "rx/scash",
                "-o", "%s:%d" % (self.stratum_host, self.stratum_port),
                "-u", stratum_user, "-p", "x",
                "-t", str(self.threads),
                "--print-time=5",
                "--no-color",
                "--http-enabled",
                "--http-host=127.0.0.1",
                "--http-port=8346",
                "--config=%s" % cfg_path,
            ]

        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            self.hashrate_hs = 0.0
            self.process = subprocess.Popen(cmd, **kwargs)
            self._append_log("[Miner] Launched %s (%d threads) -> 127.0.0.1:%d" % (os.path.basename(binary), self.threads, self.stratum_port))
            t = threading.Thread(target=self._reader_thread, args=(self.process,))
            t.daemon = True
            t.start()
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
        self.hashrate_hs = 0.0
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                for _ in range(10):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.15)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
            self._append_log("[Miner] Stopped local miner process.")
        return self.get_status()

    def get_status(self):
        self._poll_xmrig_http_summary()
        alive = self.is_running()
        if not alive:
            self.hashrate_hs = 0.0
        binary = self.find_miner_binary()
        with self.lock:
            logs_copy = list(self.logs[-25:])
            hr = round(float(self.hashrate_hs), 2) if alive else 0.0
            acc = int(self.accepted_shares)
            rej = int(self.rejected_shares)
        return {
            "ok": True,
            "running": alive,
            "algo": "rx/scash",
            "config_path": XMRIG_CONFIG_FILE,
            "pid": self.process.pid if alive and self.process else None,
            "binary": os.path.basename(binary) if binary else None,
            "has_binary": bool(binary),
            "wallet": self.wallet,
            "worker": self.worker,
            "threads": self.threads,
            "max_threads": multiprocessing.cpu_count() or 16,
            "large_pages": self.large_pages,
            "hashrate_hs": hr,
            "accepted_shares": acc,
            "rejected_shares": rej,
            "stratum_url": "stratum+tcp://%s:%d" % (self.stratum_host, self.stratum_port),
            "logs": logs_copy,
        }


GLOBAL_XMRIG = LocalMinerController()
