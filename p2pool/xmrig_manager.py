"""
Local CPU Miner Controller for Scash P2Pool (QtKawaii Edition).
Generates miner/config.json and manages a local XMRig (rx/scash) or cpuminer-scash
process placed in the miner/ directory or system PATH, connecting strictly to the
user's own local P2Pool Stratum endpoint (127.0.0.1:8345).
"""
from __future__ import print_function
import json
import multiprocessing
import os
import platform
import subprocess
import threading
import time

MINER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'miner'))
WALLET_STATE_FILE = os.path.join(MINER_DIR, 'wallet_config.json')
XMRIG_CONFIG_FILE = os.path.join(MINER_DIR, 'config.json')


class LocalMinerController(object):
    def __init__(self, stratum_host='127.0.0.1', stratum_port=8345):
        self.stratum_host = stratum_host
        self.stratum_port = int(stratum_port)
        self.process = None
        self.running = False
        self.wallet = ''
        self.worker = 'kawaii_rig01'
        self.threads = max(1, (multiprocessing.cpu_count() or 4) // 2)
        self.large_pages = True
        self.logs = []
        self.lock = threading.Lock()
        self._load_saved_wallet()

    def _load_saved_wallet(self):
        if os.path.exists(WALLET_STATE_FILE):
            try:
                data = json.load(open(WALLET_STATE_FILE, 'r'))
                self.wallet = data.get('wallet', '')
                self.worker = data.get('worker', 'kawaii_rig01')
                self.threads = int(data.get('threads', self.threads))
                self.large_pages = bool(data.get('large_pages', True))
            except Exception:
                pass

    def save_wallet_settings(self, wallet, threads=None, worker=None, large_pages=None):
        if not os.path.exists(MINER_DIR):
            os.makedirs(MINER_DIR)
        if wallet:
            self.wallet = wallet.strip()
        if threads is not None:
            self.threads = max(1, int(threads))
        if worker:
            self.worker = worker.strip()
        if large_pages is not None:
            self.large_pages = bool(large_pages)
        payload = {
            'wallet': self.wallet,
            'worker': self.worker,
            'threads': self.threads,
            'large_pages': self.large_pages,
            'updated_at': int(time.time())
        }
        with open(WALLET_STATE_FILE, 'w') as f:
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
                "rx": list(range(self.threads))
            },
            "http": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 8346,
                "restricted": True
            },
            "print-time": 5,
            "donate-level": 1,
            "pools": [
                {
                    "algo": "rx/scash",
                    "url": "%s:%d" % (self.stratum_host, self.stratum_port),
                    "user": stratum_user,
                    "pass": "x",
                    "rig-id": self.worker,
                    "keepalive": True,
                    "enabled": True,
                    "tls": False
                }
            ]
        }
        with open(XMRIG_CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
        return XMRIG_CONFIG_FILE, stratum_user

    def find_miner_binary(self):
        candidates = [
            'xmrigMiner.exe', 'xmrigMiner',
            'xmrigDaemon.exe', 'xmrigDaemon',
            'xmrig.exe', 'xmrig',
            'minerd.exe', 'minerd',
            'cpuminer-scash.exe', 'cpuminer-scash',
        ]
        search_dirs = [
            MINER_DIR,
            os.path.join(MINER_DIR, 'bin'),
            os.path.abspath(os.path.join(MINER_DIR, '..')),
        ]
        for p in os.environ.get('PATH', '').split(os.pathsep):
            if p:
                search_dirs.append(p)
        for name in candidates:
            for d in search_dirs:
                full = os.path.join(d, name)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    return full
        return None

    def _append_log(self, line):
        with self.lock:
            self.logs.append(line.rstrip())
            if len(self.logs) > 80:
                self.logs = self.logs[-80:]

    def _reader_thread(self, proc):
        try:
            for line in iter(proc.stdout.readline, b''):
                if not line:
                    break
                text = line.decode('utf-8', 'replace') if isinstance(line, bytes) else line
                self._append_log(text)
        except Exception:
            pass
        finally:
            self.running = False

    def start_mining(self, wallet=None, threads=None, worker=None, large_pages=None):
        self.save_wallet_settings(wallet or self.wallet, threads, worker, large_pages)
        if not self.wallet or not self.wallet.lower().startswith(('scash1', 'tcash1')):
            return {
                'ok': False,
                'running': False,
                'error': 'Please enter a valid scash1... Bech32 wallet address.'
            }

        self.stop_mining()
        cfg_path, stratum_user = self.build_xmrig_config()
        binary = self.find_miner_binary()

        if binary:
            bname = os.path.basename(binary).lower()
            if 'minerd' in bname or 'cpuminer' in bname:
                cmd = [
                    binary, '-a', 'randomx',
                    '-o', 'stratum+tcp://%s:%d' % (self.stratum_host, self.stratum_port),
                    '-u', stratum_user, '-p', 'x',
                    '--threads=%d' % self.threads
                ]
                if self.large_pages:
                    cmd.append('--largepages')
            else:
                cmd = [
                    binary, '-a', 'rx/scash',
                    '-o', '%s:%d' % (self.stratum_host, self.stratum_port),
                    '-u', stratum_user, '-p', 'x',
                    '-t', str(self.threads),
                    '--print-time=5',
                    '--config=%s' % cfg_path
                ]
            try:
                self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.running = True
                self._append_log("[Miner] Started %s -> 127.0.0.1:%d" % (os.path.basename(binary), self.stratum_port))
                t = threading.Thread(target=self._reader_thread, args=(self.process,))
                t.daemon = True
                t.start()
                return self.get_status()
            except Exception as e:
                self._append_log("[Miner] Error starting process: %s" % str(e))

        self.running = True
        self._append_log("[Miner] Saved miner/config.json for 127.0.0.1:%d. Place minerd or xmrigMiner in miner/ to hash locally." % self.stratum_port)
        return self.get_status()

    def stop_mining(self):
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None
        self.running = False
        return self.get_status()

    def get_status(self):
        if self.process is not None and self.process.poll() is not None:
            self.running = False
        with self.lock:
            recent_logs = list(self.logs[-15:])
        return {
            'ok': True,
            'running': self.running,
            'algo': 'rx/scash',
            'wallet': self.wallet,
            'worker': self.worker,
            'threads': self.threads,
            'large_pages': self.large_pages,
            'stratum_url': 'stratum+tcp://%s:%d' % (self.stratum_host, self.stratum_port),
            'config_path': XMRIG_CONFIG_FILE,
            'logs': recent_logs
        }


GLOBAL_XMRIG = LocalMinerController()
