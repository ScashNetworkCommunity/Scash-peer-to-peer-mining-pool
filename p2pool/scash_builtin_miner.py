#!/usr/bin/env python
"""
First-Party Out-of-the-Box Scash RandomX CPU Miner (0% Dev Fee).
Uses the native C++11 multi-threaded JIT + 2080 MiB Dataset engine (scash_mine_batch)
compiled directly into randomx.dll / librandomx.so from ScashNetworkCommunity/RandomX,
connecting over local Stratum JSON-RPC to 127.0.0.1:8345.
Works under both Python 2.7 (bundled portable PyPy) and Python 3.x.
"""
from __future__ import print_function
import argparse
import binascii
import ctypes
import json
import os
import socket
import struct
import sys
import threading
import time


def load_scash_miner_dll():
    here = os.path.abspath(os.path.dirname(__file__))
    root = os.path.abspath(os.path.join(here, '..'))
    candidates = [
        os.environ.get('SCASH_RANDOMX_LIB', ''),
        os.path.join(root, 'randomx.dll'),
        os.path.join(root, 'librandomx.dll'),
        os.path.join(root, 'librandomx.so'),
        os.path.join(root, 'librandomx.dylib'),
        os.path.join(here, 'bitcoin', 'randomx.dll'),
        os.path.join(here, 'bitcoin', 'librandomx.so'),
        'randomx.dll',
        'librandomx.so',
    ]
    for path in candidates:
        if not path:
            continue
        try:
            lib = ctypes.cdll.LoadLibrary(path)
            lib.scash_mine_batch.argtypes = [
                ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64,
                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint32), ctypes.c_char_p, ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_uint64)
            ]
            lib.scash_mine_batch.restype = ctypes.c_int
            return lib, path
        except Exception:
            continue
    return None, None


class BuiltinScashMinerClient(object):
    def __init__(self, host, port, user, threads=4, fast_mode=True, max_shares=0):
        self.host = host
        self.port = int(port)
        self.user = user
        self.threads = max(1, int(threads))
        self.fast_mode = 1 if fast_mode else 0
        self.max_shares = int(max_shares)
        self.sock = None
        self.current_job = None
        self.session_id = "scash-builtin"
        self.job_lock = threading.Lock()
        self.running = True
        self.accepted_shares = 0

    def send_json(self, obj):
        line = (json.dumps(obj) + "\n").encode('utf-8')
        self.sock.sendall(line)

    def _recv_loop(self):
        buf = b""
        while self.running:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line_s = line.strip().decode('utf-8', 'replace')
                    if not line_s:
                        continue
                    msg = json.loads(line_s)
                    if msg.get("method") == "job" and isinstance(msg.get("params"), dict):
                        with self.job_lock:
                            self.current_job = msg["params"]
                        print("[Scash-Miner] New job %s (height %s)" % (
                            self.current_job.get("job_id"), self.current_job.get("height", "?")
                        ))
                        sys.stdout.flush()
                    elif "result" in msg and isinstance(msg["result"], dict):
                        res = msg["result"]
                        if "job" in res:
                            self.session_id = res.get("id", self.session_id)
                            with self.job_lock:
                                self.current_job = res["job"]
                            print("[Scash-Miner] Connected to local P2Pool Stratum (%s:%d) - initial job %s" % (
                                self.host, self.port, self.current_job.get("job_id")
                            ))
                            sys.stdout.flush()
                        elif res.get("status") == "OK":
                            self.accepted_shares += 1
                            print("[Scash-Miner] Share ACCEPTED by local P2Pool! (Total accepted: %d)" % self.accepted_shares)
                            sys.stdout.flush()
                            if self.max_shares > 0 and self.accepted_shares >= self.max_shares:
                                self.running = False
            except Exception:
                break
        self.running = False

    def run(self):
        lib, lib_path = load_scash_miner_dll()
        if lib is None:
            print("[Scash-Miner] Waiting for compiled randomx.dll / librandomx.so...")
            sys.stdout.flush()
            return 1

        print("[Scash-Miner] Loaded native C++ RandomX JIT engine (%s) | Threads: %d | 0%% Fee" % (
            os.path.basename(lib_path), self.threads
        ))
        sys.stdout.flush()

        while self.running:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(15.0)
                self.sock.connect((self.host, self.port))
                self.sock.settimeout(None)
                self.send_json({
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "login",
                    "params": {
                        "login": self.user,
                        "pass": "x",
                        "agent": "Scash-Builtin-RandomX/0.2.0 (0% fee)",
                        "algo": ["rx/scash"]
                    }
                })

                rx_thread = threading.Thread(target=self._recv_loop)
                rx_thread.daemon = True
                rx_thread.start()

                nonce_cursor = 0
                batch_per_thread = 250
                win_nonce = ctypes.c_uint32(0)
                rx_hash_buf = ctypes.create_string_buffer(32)
                rx_cm_buf = ctypes.create_string_buffer(32)
                hashes_done = ctypes.c_uint64(0)
                last_print = time.time()
                window_hashes = 0

                while self.running and rx_thread.is_alive():
                    with self.job_lock:
                        job = dict(self.current_job) if self.current_job else None
                    if not job:
                        time.sleep(0.05)
                        continue

                    blob_bytes = binascii.unhexlify(job["blob"])[:80]
                    seed_bytes = binascii.unhexlify(job["seed_hash"])[:32]
                    t_raw = binascii.unhexlify(job["target"])
                    if len(t_raw) == 8:
                        target_u64 = struct.unpack("<Q", t_raw)[0]
                    else:
                        t32 = struct.unpack("<I", t_raw[:4])[0]
                        target_u64 = 0xffffffffffffffff // max(1, (0xffffffff // max(1, t32)))

                    t0 = time.time()
                    found = lib.scash_mine_batch(
                        seed_bytes, blob_bytes, target_u64,
                        nonce_cursor, batch_per_thread, self.threads, self.fast_mode,
                        ctypes.byref(win_nonce), rx_hash_buf, rx_cm_buf, ctypes.byref(hashes_done)
                    )
                    dt = max(0.001, time.time() - t0)
                    window_hashes += hashes_done.value
                    nonce_cursor = (nonce_cursor + self.threads * batch_per_thread) & 0xFFFFFFFF

                    if found == 1:
                        nonce_le = struct.pack("<I", win_nonce.value)
                        nonce_hex = binascii.hexlify(nonce_le).decode('ascii')
                        cm_hex = binascii.hexlify(rx_cm_buf.raw).decode('ascii')
                        self.send_json({
                            "id": 2,
                            "jsonrpc": "2.0",
                            "method": "submit",
                            "params": {
                                "id": self.session_id,
                                "job_id": job["job_id"],
                                "nonce": nonce_hex,
                                "result": cm_hex
                            }
                        })

                    now = time.time()
                    if now - last_print >= 5.0:
                        hs = window_hashes / (now - last_print)
                        print("[Scash-Miner] Speed: %.1f H/s (%d threads) | Accepted shares: %d" % (
                            hs, self.threads, self.accepted_shares
                        ))
                        sys.stdout.flush()
                        window_hashes = 0
                        last_print = now

                if self.max_shares > 0 and self.accepted_shares >= self.max_shares:
                    break
            except Exception as e:
                if not self.running:
                    break
                print("[Scash-Miner] Waiting for local P2Pool Stratum (%s:%d)... (%s)" % (self.host, self.port, str(e)))
                sys.stdout.flush()
                time.sleep(2.0)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Scash Built-in Native RandomX Miner")
    parser.add_argument("-o", "--url", default="127.0.0.1:8345", help="Local Stratum host:port")
    parser.add_argument("-u", "--user", required=True, help="Scash Bech32 payout address")
    parser.add_argument("-t", "--threads", type=int, default=4, help="CPU threads")
    parser.add_argument("--light", action="store_true", help="Use 256 MB RandomX light mode instead of 2 GB fast dataset")
    parser.add_argument("--max-shares", type=int, default=0, help="Exit after N accepted shares (used for CI self-test)")
    args = parser.parse_args()

    clean_url = args.url.replace("stratum+tcp://", "")
    host, port_s = clean_url.split(":", 1)
    client = BuiltinScashMinerClient(host, int(port_s), args.user, args.threads, not args.light, args.max_shares)
    sys.exit(client.run())


if __name__ == "__main__":
    main()
