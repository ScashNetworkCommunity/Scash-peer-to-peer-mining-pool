"""
Out-of-the-Box Miner Controller for Scash P2Pool (QtKawaii Edition).
By default (with zero extra downloads or setup), automatically launches the built-in
first-party C++11 RandomX JIT miner (p2pool/scash_builtin_miner.py -> randomx.dll / librandomx.so,
0% dev fee) connected to 127.0.0.1:8345 as soon as the user enters their scash1... wallet address
in the QtKawaii Web UI. Also supports optional custom xmrigMiner / minerd overrides in miner/.
"""
from __future__ import print_function
import json
import multiprocessing
import os
import platform
import subprocess
import sys
import threading
import time

HERE_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(HERE_DIR, '..'))
MINER_DIR = os.path.join(ROOT_DIR, 'miner')
WALLET_STATE_FILE = os.path.join(MINER_DIR, 'wallet_config.json')
XMRIG_CONFIG_FILE = os.path.join(MINER_DIR, 'config.json')
BUILTIN_MINER_SCRIPT = os.path.join(HERE_DIR, 'scash_builtin_miner.py')


class LocalMinerController(object):
    def __init__(self, stratum_host='127.0.0.1', stratum_port=8345):
        self.stratum_host = stratum_host
        self.stratum_port = int(stratum_port)
        self.process = None
        self.running = False
        self.engine_name = 'Built-in Scash C++ RandomX (0% Fee)'
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
            "cpu": {"enabled": True, "huge-pages": self.large_pages, "rx": list(range(self.threads))},
            "print-time": 5,
            "donate-level": 1,
            "pools": [{
                "algo": "rx/scash",
                "url": "%s:%d" % (self.stratum_host, self.stratum_port),
                "user": stratum_user,
                "pass": "x",
                "rig-id": self.worker,
                "keepalive": True,
                "enabled": True,
                "tls": False
            }]
        }
        with open(XMRIG_CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
        return XMRIG_CONFIG_FILE, stratum_user

    def find_custom_miner_binary(self):
        candidates = ['xmrigMiner.exe', 'xmrigMiner', 'xmrigDaemon.exe', 'xmrigDaemon', 'xmrig.exe', 'xmrig', 'minerd.exe', 'minerd']
        for name in candidates:
            full = os.path.join(MINER_DIR, name)
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
        custom_bin = self.find_custom_miner_binary()

        if custom_bin:
            bname = os.path.basename(custom_bin).lower()
            self.engine_name = os.path.basename(custom_bin)
            if 'minerd' in bname:
                cmd = [
                    custom_bin, '-a', 'randomx',
                    '-o', 'stratum+tcp://%s:%d' % (self.stratum_host, self.stratum_port),
                    '-u', stratum_user, '-p', 'x', '--threads=%d' % self.threads
                ]
            else:
                cmd = [
                    custom_bin, '-a', 'rx/scash',
                    '-o', '%s:%d' % (self.stratum_host, self.stratum_port),
                    '-u', stratum_user, '-p', 'x', '-t', str(self.threads),
                    '--print-time=5', '--config=%s' % cfg_path
                ]
        else:
            # Default Out-of-the-Box Native C++ RandomX JIT Miner (0% Fee, Zero Extra Setup!)
            self.engine_name = 'Built-in Scash C++ RandomX (0% Fee)'
            cmd = [
                sys.executable, BUILTIN_MINER_SCRIPT,
                '-o', '%s:%d' % (self.stratum_host, self.stratum_port),
                '-u', stratum_user,
                '-t', str(self.threads)
            ]
            if not self.large_pages:
                cmd.append('--light')

        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.running = True
            self._append_log("[Scash-Miner] Started %s -> 127.0.0.1:%d (%d threads)" % (
                self.engine_name, self.stratum_port, self.threads
            ))
            t = threading.Thread(target=self._reader_thread, args=(self.process,))
            t.daemon = True
            t.start()
        except Exception as e:
            self._append_log("[Scash-Miner] Error launching miner: %s" % str(e))

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
            'miner': self.engine_name,
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
