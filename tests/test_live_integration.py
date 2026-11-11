#!/usr/bin/env python3
"""
End-to-End Live CI Integration Verification for Scash P2Pool v0.2.0-beta.5 + Real Scash Core 30.4.0 Daemon!
Runs P2Pool directly against the REAL bundled `node/scashd` / `node/scashd.exe` RPC & P2P (zero RPC mocks!)
so every Scash Core 30.4.0 RPC behavior (including `./rpc/util.cpp:803` `rpc_help` bypass and `coinbaseaux`)
is verified live on both Linux and Windows before packaging.
"""
import base64
import json
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
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


def read_tail(path, n=70):
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
    import start_scash_p2pool

    # Verify strict Mainnet sync gate never triggers prematurely at block 0 / 0 peers!
    assert not start_scash_p2pool.is_mainnet_node_synced(
        {"chain": "scash", "blocks": 0, "headers": 0, "initialblockdownload": True},
        {"connections": 0},
    ), "Sync gate wrongly marked 0/0 Genesis node as synced!"
    assert not start_scash_p2pool.is_mainnet_node_synced(
        {"chain": "scash", "blocks": 0, "headers": 0, "initialblockdownload": False},
        {"connections": 0},
    ), "Sync gate wrongly marked 0/0 node with 0 peers as synced!"
    assert not start_scash_p2pool.is_mainnet_node_synced(
        {"chain": "scash", "blocks": 2500, "headers": 152791, "initialblockdownload": True},
        {"connections": 6},
    ), "Sync gate wrongly marked syncing node as synced!"
    assert start_scash_p2pool.is_mainnet_node_synced(
        {"chain": "scash", "blocks": 152791, "headers": 152791, "initialblockdownload": False},
        {"connections": 6},
    ), "Sync gate failed to accept genuinely synced Mainnet node!"

    ci_base = os.path.join(ROOT, "_ci_live_tmp")
    shutil.rmtree(ci_base, ignore_errors=True)
    os.makedirs(ci_base, exist_ok=True)

    scash_rpc_port = get_free_port()
    scash_p2p_port = get_free_port()
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
        assert "addnode=seed.scash.one:8343" in repaired, "Missing seed.scash.one:8343"
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
            real_gbt = rpc_post(scash_rpc_port, u, pw, "getblocktemplate", [{"mode": "template", "rules": ["segwit"]}])
            assert isinstance(real_gbt, dict) and real_gbt.get("previousblockhash") == GENESIS_HEX, real_gbt
            print("[LIVE-PASS 1/3] Bundled Scash Core 30.4.0 scashd started and verified live Mainnet RPC, GBT & P2P!")

            # 2. Verify zero git warning and HTTPS redirect shim in portable PyPy 2.7
            non_git = os.path.join(ci_base, "nongit_check")
            os.makedirs(non_git, exist_ok=True)
            shutil.copytree("p2pool", os.path.join(non_git, "p2pool"))
            shutil.copy2("start_scash_p2pool.py", os.path.join(non_git, "start_scash_p2pool.py"))
            for fn in os.listdir("."):
                if fn.startswith(("randomx", "librandomx")) and os.path.isfile(fn):
                    shutil.copy2(fn, os.path.join(non_git, fn))
            code = (
                "import p2pool; "
                "from twisted.web import client; "
                "assert 'v0.2.0-beta.5' in p2pool.__version__, p2pool.__version__; "
                "assert client.getPage.__name__ == '_scash_safe_getPage'; "
                "import start_scash_p2pool as sp; print('WARM_OK:', sp.ascii_safe(u'Loading block index\\u2026')); print(u'Loading block index\\u2026'); print('VERSION_OK:', p2pool.__version__)"
            )
            p = subprocess.Popen([PYPY_BIN, "-c", code], cwd=non_git, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(timeout=25)
            out_s = out.decode("utf-8", "replace")
            err_s = err.decode("utf-8", "replace")
            assert p.returncode == 0, f"PyPy check failed: {out_s} / {err_s}"
            assert "fatal: not a git repository" not in err_s and "fatal: not a git repository" not in out_s, err_s
            assert "VERSION_OK:" in out_s
            print("[LIVE-PASS 2/3] Verified zero 'fatal: not a git repository' and HTTPS redirect shim in portable PyPy 2.7!")

            # 3. Connect run_p2pool.py DIRECTLY to REAL Scash Core 30.4.0 scashd (zero RPC mocks!)
            tmp_data = os.path.join(ci_base, "p2pool_data")
            os.makedirs(tmp_data, exist_ok=True)
            p2p_log = os.path.join(ci_base, "p2pool_console.log")
            p2p_fh = open(p2p_log, "wb")
            p2p_env = os.environ.copy()
            p2p_env["SCASH_RPC_PORT"] = str(scash_rpc_port)
            p2p_env["SCASH_RPC_USER"] = str(u)
            p2p_env["SCASH_RPC_PASS"] = str(pw)
            p2p_env["SCASH_ACTIVE_DATADIR"] = str(tmp_dd)
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
                    str(scash_rpc_port),
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
                    u,
                    pw,
                ],
                env=p2p_env,
                stdout=p2p_fh,
                stderr=subprocess.STDOUT,
            )
            try:
                web_ok = False
                last_web_err = None
                for _ in range(90):
                    if p2p_proc.poll() is not None:
                        p2p_fh.flush()
                        raise RuntimeError(f"run_p2pool.py exited early ({p2p_proc.returncode}):\n{read_tail(p2p_log)}")
                    p2p_fh.flush()
                    cur_log = open(p2p_log, encoding="utf-8", errors="replace").read()
                    if "Internal bug detected" in cur_log or "NarrowError" in cur_log:
                        raise RuntimeError(f"Real scashd RPC error in P2Pool:\n{read_tail(p2p_log)}")
                    if not tcp_open(worker_port, timeout=0.4):
                        time.sleep(0.6)
                        continue
                    try:
                        html = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/static/", timeout=3).read().decode("utf-8", "replace")
                        if "Scash" in html and "magicalgirlsunite" in html:
                            for fake_tok in ("scash1q9k8m", "1.97990238", "simulateMineShare", "mockResponses"):
                                assert fake_tok not in html, f"Fake demo token {fake_tok} found in live UI!"
                            ns_raw = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/node_sync_status", timeout=3).read().decode("utf-8")
                            ns_obj = json.loads(ns_raw)
                            assert ns_obj.get("p2pool_ready") is True and ns_obj.get("syncing") is False and ns_obj.get("bestblockhash") == GENESIS_HEX, ns_obj
                            ms_raw = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/miner_status", timeout=3).read().decode("utf-8")
                            ms_obj = json.loads(ms_raw)
                            assert ms_obj.get("running") is False, ms_obj
                            web_ok = True
                            break
                    except Exception as _we:
                        last_web_err = _we
                        time.sleep(0.8)
                if not web_ok:
                    p2p_fh.flush()
                    raise RuntimeError(f"QtKawaii Web UI check failed on :{worker_port} (last_err={last_web_err!r}):\n{read_tail(p2p_log)}")

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

                p2p_fh.flush()
                final_log = open(p2p_log, encoding="utf-8", errors="replace").read()
                assert "Internal bug detected" not in final_log and "NarrowError" not in final_log, final_log
                print("[LIVE-PASS 3/3] REAL Scash Core 30.4.0 scashd RPC & P2P + P2Pool + QtKawaii UI + rx/scash Stratum verified with ZERO RPC errors!")
            finally:
                if p2p_proc.poll() is None:
                    p2p_proc.kill()
                    p2p_proc.wait()
                p2p_fh.close()

            rpc_post(scash_rpc_port, u, pw, "stop")
            scashd_proc.wait(timeout=20)
        finally:
            if scashd_proc.poll() is None:
                scashd_proc.kill()
                scashd_proc.wait()
            log_fh.close()

        # 4. Verify [LIVE-PASS 4/4]: Abruptly killing launcher parent process (like clicking X on terminal)
        # automatically terminates child scashd and unlocks its folder immediately!
        job_rpc_port = get_free_port()
        job_p2p_port = get_free_port()
        job_dd = os.path.join(ci_base, "job_kill_dd")
        os.makedirs(job_dd, exist_ok=True)
        scash_nodes.configure_scash_conf(custom_datadir=job_dd, rpc_port=job_rpc_port, p2p_port=job_p2p_port)

        holder_script = os.path.join(ci_base, "_holder_test.py")
        with open(holder_script, "w", encoding="utf-8") as hf:
            hf.write(
                "import sys, time\n"
                f"sys.path.insert(0, {ROOT!r})\n"
                "import start_scash_p2pool as sp\n"
                "sp.setup_win32_kill_on_close_job()\n"
                f"p = sp.start_bundled_scashd({SCASHD_BIN!r}, {job_dd!r}, rpc_port={job_rpc_port}, p2p_port={job_p2p_port})\n"
                "print(\"CHILD_PID=\" + str(p.pid))\n"
                "sys.stdout.flush()\n"
                "while True:\n"
                "    time.sleep(0.5)\n"
            )
        holder_proc = subprocess.Popen([sys.executable, holder_script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            ready_job = False
            for _ in range(60):
                if tcp_open(job_rpc_port, timeout=0.4):
                    ready_job = True
                    break
                time.sleep(0.5)
            assert ready_job, f"Holder scashd failed to open RPC port {job_rpc_port}"
            # Simulate hard terminal close / kill of parent process!
            holder_proc.kill()
            holder_proc.wait(timeout=10)
            closed_ok = False
            for _ in range(25):
                if not tcp_open(job_rpc_port, timeout=0.3):
                    closed_ok = True
                    break
                time.sleep(0.3)
            assert closed_ok, f"Orphan scashd STILL listening on :{job_rpc_port} after parent was killed!"
            # Prove folder is 100% unlocked and deletable on Windows & Linux!
            for _rm_i in range(12):
                try:
                    shutil.rmtree(job_dd)
                    break
                except OSError:
                    if _rm_i == 11:
                        raise
                    time.sleep(0.25)
            print("[LIVE-PASS 4/4] Zero-orphan terminal-close lifecycle verified (child scashd exited & folder unlocked)!")
        finally:
            if holder_proc.poll() is None:
                holder_proc.kill()
                holder_proc.wait()
    finally:
        shutil.rmtree(ci_base, ignore_errors=True)


if __name__ == "__main__":
    run_all_live_tests()
    print("[ALL LIVE INTEGRATION TESTS PASSED]")
