#!/usr/bin/env python3
"""
End-to-End Live CI Integration Verification for Scash P2Pool v0.2.0-beta.3 + Scash Core 30.4.0.
"""
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

IS_WIN = platform.system() == "Windows"
ROOT = os.path.abspath(".")
sys.path.insert(0, ROOT)

SCASHD_BIN = os.path.join(ROOT, "node", "scashd.exe" if IS_WIN else "scashd")
PYPY_BIN = os.path.join(ROOT, "runtime", "pypy2", "pypy.exe" if IS_WIN else "bin/pypy")
GENESIS_HEX = "e3bf1597a568216022dbda6a0945f09b005d19f041e7158c3cbca9d4029ee82d"

NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_USED_PORTS = set()


def get_free_port():
    # Pick outside Linux ephemeral client range (32768-60999) and Windows WinNAT low range (14000-20000)
    for _ in range(200):
        cand = random.randint(24000, 29999)
        if cand in _USED_PORTS:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", cand))
            s.close()
            _USED_PORTS.add(cand)
            return cand
        except Exception:
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    _USED_PORTS.add(port)
    return port


def tcp_open(port, timeout=0.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", int(port)))
        s.close()
        return True
    except Exception:
        return False


def rpc_post(port, user, pw, method, params=None):
    url = f"http://127.0.0.1:{port}/"
    body = json.dumps({"jsonrpc": "1.0", "id": "ci", "method": method, "params": params or []}).encode("utf-8")
    auth = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "Authorization": f"Basic {auth}"})
    with NO_PROXY_OPENER.open(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))["result"]


def read_tail(path, n=60):
    if os.path.isfile(path):
        try:
            lines = open(path, encoding="utf-8", errors="replace").read().splitlines()[-n:]
            return f"--- {path} ---\n" + "\n".join(lines)
        except Exception:
            pass
    return ""


def run_all_live_tests():
    assert os.path.isfile(SCASHD_BIN), f"Missing bundled scashd at {SCASHD_BIN}"
    from p2pool import scash_nodes

    ci_base = os.path.join(ROOT, "_ci_live_tmp")
    shutil.rmtree(ci_base, ignore_errors=True)
    os.makedirs(ci_base, exist_ok=True)

    scash_rpc_port = get_free_port()
    scash_p2p_port = get_free_port()
    mock_rpc_port = get_free_port()
    p2pool_p2p_port = get_free_port()
    worker_port = get_free_port()

    tmp_dd = os.path.join(ci_base, "scash_dd")
    os.makedirs(tmp_dd, exist_ok=True)
    console_log = os.path.join(ci_base, "scashd_console.log")

    try:
        # 1. Verify scash_nodes.configure_scash_conf() repairs legacy config cleanly
        broken_conf = os.path.join(tmp_dd, "scash.conf")
        with open(broken_conf, "w", encoding="utf-8") as f:
            f.write(
                "chain=scash\nserver=1\ndaemon=1\nupnp=1\ntxindex=1\n"
                "rpcuser=testuser\nrpcpassword=testpass123\n"
                f"rpcport={scash_rpc_port}\nport={scash_p2p_port}\n[scash]\nadddnsseed=scash.tv\n"
            )

        conf_p, u, pw, rport = scash_nodes.configure_scash_conf(custom_datadir=tmp_dd)
        repaired = open(conf_p, encoding="utf-8").read()
        assert "adddnsseed=" not in repaired, "Failed to strip invalid adddnsseed="
        assert "txindex=1" not in repaired, "Failed to strip unindexed txindex=1"
        assert "daemon=" not in repaired, "Failed to strip daemon=1"
        assert "upnp=" not in repaired, "Failed to strip Core-30-removed upnp="
        assert "addnode=scash.tv:8343" in repaired, "Missing injected community Scash nodes"
        assert "[scash]" in repaired and "[main]" in repaired, "Missing [scash] or [main] sections"
        assert u == "testuser" and pw == "testpass123" and rport == scash_rpc_port

        offline_lines = [ln for ln in repaired.splitlines() if not ln.strip().startswith("addnode=")]
        with open(conf_p, "w", encoding="utf-8") as f:
            f.write("\n".join(offline_lines) + "\n")

        cmd = [
            SCASHD_BIN,
            f"-datadir={tmp_dd}",
            "-chain=scash",
            "-server=1",
            "-listen=1",
            f"-rpcport={scash_rpc_port}",
            "-rpcbind=127.0.0.1",
            "-rpcallowip=127.0.0.1",
            f"-port={scash_p2p_port}",
            f"-bind=127.0.0.1:{scash_p2p_port}",
            "-connect=0",
            "-dnsseed=0",
            "-printtoconsole=1",
        ]
        if not IS_WIN:
            cmd.append("-daemon=0")

        log_fh = open(console_log, "wb")
        scashd_proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT)
        try:
            bc_info = None
            last_err = None
            for _ in range(180):
                if scashd_proc.poll() is not None:
                    log_fh.flush()
                    raise RuntimeError(
                        f"scashd exited early ({scashd_proc.returncode}):\n{read_tail(console_log)}"
                    )
                if not tcp_open(scash_rpc_port, timeout=0.4):
                    last_err = f"TCP 127.0.0.1:{scash_rpc_port} not listening yet"
                    time.sleep(0.6)
                    continue
                try:
                    bc_info = rpc_post(scash_rpc_port, u, pw, "getblockchaininfo")
                    if tcp_open(scash_p2p_port, timeout=0.5):
                        break
                except urllib.error.HTTPError as he:
                    try:
                        last_err = f"HTTP {he.code}: {he.read().decode('utf-8', 'replace')}"
                    except Exception:
                        last_err = str(he)
                    time.sleep(0.8)
                except Exception as e:
                    last_err = repr(e)
                    time.sleep(0.8)

            if bc_info is None:
                log_fh.flush()
                raise AssertionError(
                    f"Bundled scashd did not answer getblockchaininfo on :{scash_rpc_port}. Last error: {last_err}\n{read_tail(console_log)}"
                )
            assert bc_info.get("chain") in ("scash", "main"), f"Unexpected chain: {bc_info}"
            g0 = rpc_post(scash_rpc_port, u, pw, "getblockhash", [0])
            assert g0 == GENESIS_HEX, f"Genesis mismatch: {g0}"
            print("[LIVE-PASS 1/3] Bundled Scash Core 30.4.0 scashd started with repaired scash.conf and verified Mainnet RPC & P2P!")

            # 2. Verify zero git warning and HTTPS redirect shim in portable PyPy 2.7
            non_git = os.path.join(ci_base, "nongit_check")
            os.makedirs(non_git, exist_ok=True)
            shutil.copytree("p2pool", os.path.join(non_git, "p2pool"))
            for fn in os.listdir("."):
                if fn.startswith(("randomx", "librandomx")) and os.path.isfile(fn):
                    shutil.copy2(fn, os.path.join(non_git, fn))
            code = (
                "import p2pool; "
                "from twisted.web import client; "
                "assert 'v0.2.0-beta.3' in p2pool.__version__, p2pool.__version__; "
                "assert client.getPage.__name__ == '_scash_safe_getPage'; "
                "print('VERSION_OK:', p2pool.__version__)"
            )
            p = subprocess.Popen([PYPY_BIN, "-c", code], cwd=non_git, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(timeout=25)
            out_s = out.decode("utf-8", "replace")
            err_s = err.decode("utf-8", "replace")
            assert p.returncode == 0, f"PyPy check failed: {out_s} / {err_s}"
            assert "fatal: not a git repository" not in err_s and "fatal: not a git repository" not in out_s, err_s
            assert "VERSION_OK:" in out_s
            print("[LIVE-PASS 2/3] Verified zero 'fatal: not a git repository' and HTTPS redirect shim in portable PyPy 2.7!")

            # 3. Verify live P2Pool + real Scash Core 30.4.0 P2P + QtKawaii Web UI + rx/scash Stratum job
            now_ts = int(time.time())

            class MockSyncedScashCore30RPCHandler(BaseHTTPRequestHandler):
                def log_message(self, fmt, *args):
                    return

                def do_POST(self):
                    ln = int(self.headers.get("Content-Length", "0"))
                    req = json.loads(self.rfile.read(ln).decode("utf-8"))
                    m = req.get("method")
                    res = None
                    err_obj = None
                    if m == "help":
                        res = (
                            "getblock\ngetblockchaininfo\ngetblockhash\ngetblockheader\n"
                            "getblocktemplate\ngetmininginfo\ngetnetworkinfo\ngetpeerinfo\n"
                            "submitblock\nvalidateaddress\n"
                        )
                    elif m == "getblockchaininfo":
                        res = {
                            "chain": "scash",
                            "blocks": 0,
                            "headers": 0,
                            "bestblockhash": GENESIS_HEX,
                            "difficulty": 1.0,
                            "time": now_ts,
                            "mediantime": 1708650456,
                            "initialblockdownload": False,
                            "softforks": {
                                "taproot": {"type": "buried", "active": True, "height": 0},
                            },
                            "warnings": ["Pre-release Core 30.4 test warning"],
                        }
                    elif m == "getnetworkinfo":
                        res = {
                            "version": 300400,
                            "subversion": "/Scash:2.3.0(Mid-World Core 30.4.0)/",
                            "protocolversion": 70016,
                            "connections": 8,
                            "warnings": [],
                        }
                    elif m == "getblockhash":
                        res = GENESIS_HEX
                    elif m in ("getblock", "getblockheader"):
                        res = {
                            "hash": GENESIS_HEX,
                            "confirmations": 1,
                            "height": 0,
                            "version": 1,
                            "merkleroot": "2f7b90fafd8247ee73d213d49699fcfe12a37c608f1d9d1c06f10e43cb6426c6",
                            "time": 1708650456,
                            "nonce": 20076863,
                            "bits": "1e0fffff",
                            "difficulty": 1.0,
                            "tx": ["2f7b90fafd8247ee73d213d49699fcfe12a37c608f1d9d1c06f10e43cb6426c6"],
                        }
                    elif m == "getmininginfo":
                        res = {"blocks": 0, "difficulty": 1.0, "networkhashps": 1000, "warnings": []}
                    elif m == "getpeerinfo":
                        res = []
                    elif m == "validateaddress":
                        p0 = (req.get("params") or [""])[0]
                        res = {
                            "isvalid": True,
                            "address": p0,
                            "scriptPubKey": "0014978528e154cb77b965d8dcef480f51824c3ea9ac",
                            "isscript": False,
                            "iswitness": True,
                        }
                    elif m == "submitblock":
                        res = None
                    elif m == "getblocktemplate":
                        res = {
                            "capabilities": ["proposal"],
                            "version": 0x20000000,
                            "rules": ["csv", "!segwit"],
                            "vbavailable": {},
                            "vbrequired": 0,
                            "previousblockhash": GENESIS_HEX,
                            "transactions": [],
                            "coinbaseaux": {"flags": ""},
                            "coinbasevalue": 5000000000,
                            "longpollid": GENESIS_HEX + "00",
                            "target": "00000fffff000000000000000000000000000000000000000000000000000000",
                            "mintime": 1708650457,
                            "mutable": ["time", "transactions", "prevblock"],
                            "noncerange": "00000000ffffffff",
                            "sigoplimit": 80000,
                            "sizelimit": 4000000,
                            "weightlimit": 4000000,
                            "curtime": now_ts,
                            "bits": "1e0fffff",
                            "height": 1,
                            "default_witness_commitment": "6a24aa21a9ede2f61c3f71d1defd3fa999dfa36953755c690689799962b48bebd836974e8cf9",
                        }
                    else:
                        err_obj = {"code": -32601, "message": f"Method not found: {m}"}
                    out = json.dumps({"result": res, "error": err_obj, "id": req.get("id")}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    self.wfile.write(out)

            rpc_srv = HTTPServer(("127.0.0.1", mock_rpc_port), MockSyncedScashCore30RPCHandler)
            t = threading.Thread(target=rpc_srv.serve_forever)
            t.daemon = True
            t.start()

            tmp_data = os.path.join(ci_base, "p2pool_data")
            os.makedirs(tmp_data, exist_ok=True)
            p2p_log = os.path.join(ci_base, "p2pool_console.log")
            p2p_fh = open(p2p_log, "wb")
            p2p_env = os.environ.copy()
            if not IS_WIN:
                p2p_env["LD_LIBRARY_PATH"] = ROOT + (":" + p2p_env["LD_LIBRARY_PATH"] if p2p_env.get("LD_LIBRARY_PATH") else "")

            p2p_proc = subprocess.Popen(
                [
                    PYPY_BIN,
                    "run_p2pool.py",
                    "--net",
                    "scash",
                    "--disable-upnp",
                    "--datadir",
                    tmp_data,
                    "--bitcoind-address",
                    "127.0.0.1",
                    "--bitcoind-rpc-port",
                    str(mock_rpc_port),
                    "--bitcoind-p2p-port",
                    str(scash_p2p_port),
                    "--p2pool-port",
                    str(p2pool_p2p_port),
                    "-w",
                    f"127.0.0.1:{worker_port}",
                    "--outgoing-conns",
                    "0",
                    "--max-conns",
                    "4",
                    "-a",
                    "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2",
                    "scashminer",
                    "kawaiip2poolpass",
                ],
                env=p2p_env,
                stdout=p2p_fh,
                stderr=subprocess.STDOUT,
            )
            try:
                web_ok = False
                for _ in range(90):
                    if p2p_proc.poll() is not None:
                        p2p_fh.flush()
                        raise RuntimeError(f"run_p2pool.py exited early ({p2p_proc.returncode}):\n{read_tail(p2p_log)}")
                    if not tcp_open(worker_port, timeout=0.4):
                        time.sleep(0.6)
                        continue
                    try:
                        html = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/static/", timeout=3).read().decode("utf-8", "replace")
                        if "Scash" in html and "magicalgirlsunite" in html:
                            web_ok = True
                            break
                    except Exception:
                        time.sleep(0.8)
                if not web_ok:
                    p2p_fh.flush()
                    raise RuntimeError(f"QtKawaii Web UI did not open :{worker_port} within 90s.\n{read_tail(p2p_log)}")

                s = socket.create_connection(("127.0.0.1", worker_port), timeout=5)
                login_req = json.dumps({
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "login",
                    "params": {
                        "login": "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2",
                        "pass": "x",
                        "agent": "ScashTest/1.0",
                        "algo": ["rx/scash"],
                    },
                }) + "\n"
                s.sendall(login_req.encode("utf-8"))
                resp_line = b""
                while b"\n" not in resp_line:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp_line += chunk
                s.close()
                if not resp_line.strip():
                    time.sleep(0.3)
                    p2p_fh.flush()
                    raise RuntimeError(f"Stratum returned empty response on :{worker_port}!\n{read_tail(p2p_log)}")
                msg = json.loads(resp_line.decode("utf-8"))
                job = (msg.get("result") or {}).get("job") or {}
                if not (job.get("algo") == "rx/scash" and len(job.get("blob", "")) == 160):
                    p2p_fh.flush()
                    raise AssertionError(f"Invalid rx/scash Stratum job: {msg}\n{read_tail(p2p_log)}")
                print("[LIVE-PASS 3/3] Live Scash Core 30.4.0 P2P + P2Pool + QtKawaii Web UI + rx/scash Stratum job verified end-to-end!")
            finally:
                if p2p_proc.poll() is None:
                    p2p_proc.kill()
                    p2p_proc.wait()
                p2p_fh.close()
                rpc_srv.shutdown()
                rpc_srv.server_close()

            rpc_post(scash_rpc_port, u, pw, "stop")
            scashd_proc.wait(timeout=20)
        finally:
            if scashd_proc.poll() is None:
                scashd_proc.kill()
                scashd_proc.wait()
            log_fh.close()
    finally:
        shutil.rmtree(ci_base, ignore_errors=True)


if __name__ == "__main__":
    run_all_live_tests()
    print("[ALL LIVE INTEGRATION TESTS PASSED]")
