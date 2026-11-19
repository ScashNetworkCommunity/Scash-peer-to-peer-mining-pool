#!/usr/bin/env python3
"""
End-to-End Live CI Integration Verification for Scash P2Pool v0.3.5 + Real Scash Core 30.4.0 Daemon!
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
    if IS_WIN:
        wr0 = os.path.join(ROOT, "miner", "WinRing0x64.sys")
        assert os.path.isfile(wr0) and os.path.getsize(wr0) > 5000, f"Missing WinRing0x64.sys at {wr0}"
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
            print("[LIVE-PASS 1/5] Bundled Scash Core 30.4.0 scashd started and verified live Mainnet RPC, GBT & P2P!")

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
                "assert 'v0.3.5' in p2pool.__version__, p2pool.__version__; "
                "assert client.getPage.__name__ == '_scash_safe_getPage'; "
                "import start_scash_p2pool as sp; print('WARM_OK:', sp.ascii_safe(u'Loading block index\\u2026')); print(u'Loading block index\\u2026'); print('VERSION_OK:', p2pool.__version__)"
            )
            p = subprocess.Popen([PYPY_BIN, "-B", "-c", code], cwd=non_git, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(timeout=25)
            out_s = out.decode("utf-8", "replace")
            err_s = err.decode("utf-8", "replace")
            assert p.returncode == 0, f"PyPy check failed: {out_s} / {err_s}"
            assert "fatal: not a git repository" not in err_s and "fatal: not a git repository" not in out_s, err_s
            assert "VERSION_OK:" in out_s

            assert not os.path.exists(os.path.join(ROOT, "p2pool", "p2pool")), "Nested p2pool/p2pool directory still exists!"
            root_code = (
                "import binascii, struct; "
                "from p2pool import main, data as pdata; "
                "from p2pool.bitcoin import data as bdata, networks, scash_randomx; "
                "assert scash_randomx.is_native_randomx_loaded(), 'PyPy failed to load native librandomx!'; "
                "ml = binascii.unhexlify('2f7b90fafd8247ee73d213d49699fcfe12a37c608f1d9d1c06f10e43cb6426c6')[::-1]; "
                "gh = struct.pack('<I32s32sIII', 1, b'\\x00'*32, ml, 1708650456, 0x1e0fffff, 20076863); "
                "rxh, _ = scash_randomx.calculate_scash_hash_and_cm_bytes(gh); "
                "assert binascii.hexlify(rxh[::-1]).decode('ascii') == '33c450e0152826e3a8948b01464cf9182344a1544b3ddcf6153dd04b62938d01'; "
                "assert 'v0.3.5' in main.p2pool.__version__, main.p2pool.__version__; "
                "addr = bdata.script2_to_address(pdata.DONATION_SCRIPT, networks.nets['scash']); "
                "assert addr == 'scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc', addr; "
                "print('ROOT_DONATION_OK:', addr, main.p2pool.__version__)"
            )
            pr = subprocess.Popen([PYPY_BIN, "-B", "-c", root_code], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            rout, rerr = pr.communicate(timeout=25)
            assert pr.returncode == 0 and b"ROOT_DONATION_OK:" in rout, (rout, rerr)
            # Verify BEP 15 Serverless UDP Swarm Rendezvous wire protocol inside portable PyPy 2.7!
            import threading as _t_bep, struct as _st_bep
            _bep_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _bep_sock.bind(("127.0.0.1", 0))
            _bep_port = _bep_sock.getsockname()[1]
            _bep_sock.settimeout(25.0)
            def _mock_bep15_srv():
                try:
                    d1, a1 = _bep_sock.recvfrom(256)
                    magic, act1, tx1 = _st_bep.unpack("!QII", d1[:16])
                    assert magic == 0x41727101980 and act1 == 0
                    _bep_sock.sendto(_st_bep.unpack("!16s", _st_bep.pack("!IIQ", 0, tx1, 0x123456789ABCDEF0))[0], a1)
                    d2, a2 = _bep_sock.recvfrom(256)
                    cid, act2, tx2 = _st_bep.unpack("!QII", d2[:16])
                    assert cid == 0x123456789ABCDEF0 and act2 == 1 and len(d2) == 98
                    hdr = _st_bep.pack("!IIIII", 1, tx2, 90, 2, 0)
                    peers_bin = socket.inet_aton("198.51.100.42") + _st_bep.pack("!H", 8344) + socket.inet_aton("127.0.0.1") + _st_bep.pack("!H", 8344)
                    _bep_sock.sendto(hdr + peers_bin, a2)
                finally:
                    _bep_sock.close()
            _bt = _t_bep.Thread(target=_mock_bep15_srv)
            _bt.daemon = True
            _bt.start()
            bep_pypy_code = (
                "from p2pool import auto_mesh; "
                f"res = auto_mesh.announce_and_discover_bep15_swarm('7363617368703236', 8344, trackers=[('127.0.0.1', {_bep_port})], timeout=3.0); "
                "assert res == [('198.51.100.42', 8344)], repr(res); "
                "print('BEP15_SWARM_OK:', res)"
            )
            pb = subprocess.Popen([PYPY_BIN, "-B", "-c", bep_pypy_code], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            bout, berr = pb.communicate(timeout=25)
            assert pb.returncode == 0 and b"BEP15_SWARM_OK:" in bout, (bout, berr)
            # Also live-verify SHP1 Decentralized UDP Hole-Punch stream bridge (64 KB random binary payload) in PyPy 2.7!
            hp_pypy_code = (
                "import hashlib, os, socket, threading, time\n"
                "from p2pool import auto_mesh\n"
                "echo_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
                "echo_srv.bind(('127.0.0.1', 0)); echo_srv.listen(2)\n"
                "echo_port = echo_srv.getsockname()[1]\n"
                "def _echo_loop():\n"
                "    c, _ = echo_srv.accept()\n"
                "    while True:\n"
                "        d = c.recv(8192)\n"
                "        if not d: break\n"
                "        c.sendall(d)\n"
                "    c.close(); echo_srv.close()\n"
                "te = threading.Thread(target=_echo_loop); te.daemon = True; te.start()\n"
                "ua = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); ua.bind(('127.0.0.1', 0))\n"
                "ub = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); ub.bind(('127.0.0.1', 0))\n"
                "pa, pb_u = ua.getsockname()[1], ub.getsockname()[1]\n"
                "tp = threading.Thread(target=auto_mesh._udp_tunnel_pump_worker); tp.daemon = True; tp.start()\n"
                "ready_port = []\n"
                "tun_a = auto_mesh._UdpTunnelSession(777, ('127.0.0.1', pb_u), 'bbbb', True, ua, target_local_port=echo_port)\n"
                "tun_b = auto_mesh._UdpTunnelSession(777, ('127.0.0.1', pa), 'aaaa', False, ub, target_local_port=echo_port)\n"
                "with auto_mesh._UDP_TUNNELS_LOCK:\n"
                "    auto_mesh._UDP_TUNNELS[777] = tun_a\n"
                "tun_b_map = {777: tun_b}\n"
                "def _pump_udp(usock, my_tun):\n"
                "    while not my_tun.closed:\n"
                "        try:\n"
                "            pkt, _ = usock.recvfrom(2048)\n"
                "            pr = auto_mesh.unpack_shp_packet(pkt)\n"
                "            if pr: my_tun.on_udp_packet(pr[0], pr[2], pr[3], pr[4])\n"
                "        except Exception: break\n"
                "tun_b.start_responder_socket()\n"
                "with auto_mesh._UDP_TUNNELS_LOCK:\n"
                "    auto_mesh._UDP_TUNNELS[778] = tun_b\n"
                "tun_a.start_initiator_listener(on_ready_cb=lambda lp: ready_port.append(lp))\n"
                "ta = threading.Thread(target=_pump_udp, args=(ua, tun_a)); ta.daemon = True; ta.start()\n"
                "tb = threading.Thread(target=_pump_udp, args=(ub, tun_b)); tb.daemon = True; tb.start()\n"
                "for _ in range(40):\n"
                "    if ready_port: break\n"
                "    tun_b._send_udp(auto_mesh.SHP_OPEN_ACK, 0, 0, b'')\n"
                "    time.sleep(0.05)\n"
                "assert ready_port, 'SHP1 initiator bridge did not become ready!'\n"
                "cli = socket.create_connection(('127.0.0.1', ready_port[0]), timeout=5.0)\n"
                "blob = os.urandom(65536)\n"
                "cli.sendall(blob)\n"
                "got = bytearray()\n"
                "cli.settimeout(8.0)\n"
                "while len(got) < len(blob):\n"
                "    ch = cli.recv(8192)\n"
                "    assert ch, 'EOF before 64KB completed'\n"
                "    got.extend(ch)\n"
                "assert hashlib.sha256(memoryview(got).tobytes()).hexdigest() == hashlib.sha256(blob).hexdigest()\n"
                "cli.close(); tun_a.close(); tun_b.close(); ua.close(); ub.close()\n"
                "print('SHP1_HOLEPUNCH_64KB_OK')\n"
            )
            php = subprocess.Popen([PYPY_BIN, "-B", "-c", hp_pypy_code], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            hp_out, hp_err = php.communicate(timeout=25)
            assert php.returncode == 0 and b"SHP1_HOLEPUNCH_64KB_OK" in hp_out, (hp_out, hp_err)
            print("[LIVE-PASS 2/5] Verified PyPy 2.7 runtime, native RandomX, BEP 15 Swarm & 64KB SHP1 UDP Hole-Punch tunnel!")

            # 3. Connect run_p2pool.py DIRECTLY to REAL Scash Core 30.4.0 scashd (zero RPC mocks!)
            tmp_data = os.path.join(ci_base, "p2pool_data")
            os.makedirs(tmp_data, exist_ok=True)
            p2p_log = os.path.join(ci_base, "p2pool_console.log")
            p2p_fh = open(p2p_log, "wb")
            p2p_env = os.environ.copy()
            p2p_env["SCASH_RPC_PORT"] = str(scash_rpc_port)
            p2p_env["SCASH_RPC_USER"] = str(u)
            p2p_env["SCASH_RPC_PASS"] = str(pw)
            mesh_udp_port = get_free_port()
            p2p_env["SCASH_ACTIVE_DATADIR"] = str(tmp_dd)
            p2p_env["SCASH_CI_FAST_DIFF"] = "1"
            p2p_env["SCASH_CI_ISOLATED_MESH"] = "1"
            p2p_env["SCASH_MESH_UDP_PORT"] = str(mesh_udp_port)
            if not IS_WIN:
                p2p_env["LD_LIBRARY_PATH"] = ROOT + (":" + p2p_env["LD_LIBRARY_PATH"] if p2p_env.get("LD_LIBRARY_PATH") else "")

            p2p_proc = subprocess.Popen(
                [
                    PYPY_BIN,
                    "-B",
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
                    "4",
                    "--max-conns",
                    "8",
                    "-a",
                    "scash1q4sv2xck9x7agzx4n4djtsgl3k59zd6s28ywzax",
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
                            pay_raw = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/current_payouts", timeout=3).read().decode("utf-8")
                            pay_obj = json.loads(pay_raw)
                            assert isinstance(pay_obj, dict) and len(pay_obj) >= 1, pay_obj
                            assert "scash1q6q76dl9rjqtx6qsturnu9zkge3c0tpqrumxx8d" not in pay_obj, pay_obj
                            api_raw = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/api/pools", timeout=3).read().decode("utf-8")
                            api_obj = (json.loads(api_raw) or {}).get("pools") or []
                            assert len(api_obj) == 1 and api_obj[0].get("id") == "scash-p2pool" and float(api_obj[0].get("poolFeePercent", -1)) == 0.0, api_obj
                            assert int((api_obj[0].get("networkStats") or {}).get("blockHeight", -1)) >= 0 and float((api_obj[0].get("networkStats") or {}).get("networkDifficulty", 0.0)) > 0.0, api_obj
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
                if not (job.get("algo") == "rx/scash" and len(job.get("blob", "")) == 224):
                    p2p_fh.flush()
                    raise AssertionError(f"Invalid rx/scash Stratum job: {msg}\n{read_tail(p2p_log)}")

                # Live test bundled xmrigDaemon + xmrigMiner (WITH_MSR=ON) via /miner_start -> /miner_status -> /miner_stop!
                st_start = json.loads(
                    NO_PROXY_OPENER.open(
                        f"http://127.0.0.1:{worker_port}/miner_start?wallet=scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2&threads=2",
                        timeout=6,
                    ).read().decode("utf-8")
                )
                assert st_start.get("ok") is True and st_start.get("has_binary") is True, st_start
                assert str(st_start.get("binary", "")).lower().startswith("xmrigminer"), st_start
                cfg_json_txt = open(os.path.join(ROOT, "miner", "config.json"), encoding="utf-8").read()
                cfg_json = json.loads(cfg_json_txt)
                assert cfg_json.get("randomx", {}).get("wrmsr") is True and cfg_json.get("randomx", {}).get("rdmsr") is True, cfg_json
                assert "+" not in cfg_json["pools"][0]["user"], cfg_json["pools"][0]["user"]
                assert "rx" not in cfg_json.get("cpu", {}), cfg_json

                # REQUIRE xmrigMiner (--daemonized --cc-disabled) to ACTUALLY hash rx/scash and mine >= 1 REAL ACCEPTED SHARE in P2Pool!
                share_mined_ok = False
                last_ms = None
                last_ls = None
                for _ in range(120):
                    time.sleep(0.75)
                    p2p_fh.flush()
                    cur_p2p_log = open(p2p_log, encoding="utf-8", errors="replace").read()
                    try:
                        last_ms = json.loads(
                            NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/miner_status", timeout=10).read().decode("utf-8")
                        )
                    except Exception:
                        pass
                    try:
                        last_ls = json.loads(
                            NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/local_stats", timeout=10).read().decode("utf-8")
                        )
                    except Exception:
                        pass
                    sh_tot = int(((last_ls or {}).get("shares") or {}).get("total", 0))
                    if "GOT SHARE!" in cur_p2p_log or sh_tot >= 1:
                        share_mined_ok = True
                        print(f"[LIVE-SHARE-VERIFIED] xmrigMiner mined real rx/scash share(s)! total_shares={sh_tot}, miner_status={last_ms.get('hashrate_hs')} H/s")
                        break
                st_stop = json.loads(
                    NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/miner_stop", timeout=6).read().decode("utf-8")
                )
                p2p_fh.flush()
                assert share_mined_ok, (
                    f"xmrigMiner failed to mine a real accepted share on :{worker_port}!\n"
                    f"miner_status={last_ms}\nlocal_stats={last_ls}\n{read_tail(p2p_log)}"
                )
                assert st_stop.get("running") is False, st_stop
                # Verify 0% pool fee + .kawaii_rig01 worker suffix: 100% (~50.0 SCASH) goes straight to miner's scash1... wallet (0.0 SCASH fee)!
                pay_after = {}
                for _ in range(15):
                    pay_after = json.loads(
                        NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/current_payouts", timeout=5).read().decode("utf-8")
                    )
                    if "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2" in pay_after:
                        break
                    time.sleep(0.3)
                miner_amt = float(pay_after.get("scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2", 0.0))
                other_amt = sum(float(v) for k, v in pay_after.items() if k != "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2")
                assert miner_amt >= 49.9999 and other_amt < 0.0001, f"Expected 100% (~50.0 SCASH, 0% fee) to miner, got: {pay_after}"
                print(f"[LIVE-ZERO-FEE-VERIFIED] Miner (.kawaii_rig01)={miner_amt:.8f} SCASH (100% PPLNS, 0% pool fee)!")
                tel_live = json.loads(
                    NO_PROXY_OPENER.open(
                        f"http://127.0.0.1:{worker_port}/pool_telemetry?wallet=scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2",
                        timeout=8,
                    ).read().decode("utf-8")
                )
                assert tel_live.get("ok") is True and tel_live.get("version") == "0.3.5", tel_live
                assert "pool_10s_hs" in (tel_live.get("hashrates") or {}) and "pool_30m_hs" in (tel_live.get("hashrates") or {}), tel_live
                assert "miner_scash_all_time" in (tel_live.get("ledger") or {}) and "pool_blocks_all_time" in (tel_live.get("ledger") or {}), tel_live
                ex_urls = [e.get("url") for e in ((tel_live.get("market") or {}).get("exchanges") or [])]
                assert "https://www.ourbit.com/exchange/SCASH_USDT" in ex_urls and "https://nonkyc.io/market/SCASH_USDT" in ex_urls and "https://trade.nestex.one/spot/SCASH" in ex_urls, ex_urls
                print(f"[LIVE-TELEMETRY-VERIFIED] /pool_telemetry v0.3.5 OK: hashrates={tel_live.get('hashrates')}, ledger_blocks={tel_live['ledger']['pool_blocks_all_time']}")
                for _ in range(15):
                    if not tcp_open(8346, timeout=0.25):
                        break
                    time.sleep(0.2)

                p2p_fh.flush()
                final_log = open(p2p_log, encoding="utf-8", errors="replace").read()
                assert "Internal bug detected" not in final_log and "NarrowError" not in final_log and "Unhandled Error" not in final_log, final_log
                assert "v0.3.5-scash-kawaii" in final_log and "Pool fee: 0.0%" in final_log and "Donating " not in final_log and "scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc" not in final_log, final_log
                print("[LIVE-PASS 3/5] REAL Scash Core 30.4.0 scashd RPC & P2P + P2Pool + QtKawaii UI + rx/scash Stratum verified with ZERO RPC errors!")

                # 3b. [LIVE-PASS 4/5]: Launch a SECOND P2Pool node (Node B) with ZERO -n / --peer flags
                # and verify AutoMesh automatically links Node A <-> Node B and syncs Node A's mined share!
                p2pool_p2p_port_b = get_free_port()
                worker_port_b = get_free_port()
                tmp_data_b = os.path.join(ci_base, "p2pool_data_b")
                os.makedirs(tmp_data_b, exist_ok=True)
                p2p_log_b = os.path.join(ci_base, "p2pool_console_b.log")
                p2p_fh_b = open(p2p_log_b, "wb")
                p2p_proc_b = subprocess.Popen(
                    [
                        PYPY_BIN,
                        "-B",
                        "run_p2pool.py",
                        "--net",
                        "scash",
                        "--disable-upnp",
                        "--datadir",
                        tmp_data_b,
                        "--bitcoind-address",
                        "127.0.0.1",
                        "--bitcoind-rpc-port",
                        str(scash_rpc_port),
                        "--bitcoind-p2p-port",
                        str(scash_p2p_port),
                        "--p2pool-port",
                        str(p2pool_p2p_port_b),
                        "-w",
                        f"127.0.0.1:{worker_port_b}",
                        "--outgoing-conns",
                        "4",
                        "--max-conns",
                        "8",
                        "-a",
                        "scash1q4sv2xck9x7agzx4n4djtsgl3k59zd6s28ywzax",
                        u,
                        pw,
                    ],
                    env=p2p_env,
                    stdout=p2p_fh_b,
                    stderr=subprocess.STDOUT,
                )
                try:
                    mesh_linked = False
                    last_mesh_diag = None
                    for _ in range(70):
                        if p2p_proc_b.poll() is not None:
                            p2p_fh_b.flush()
                            raise RuntimeError(f"Node B exited early ({p2p_proc_b.returncode}):\n{read_tail(p2p_log_b)}")
                        time.sleep(0.6)
                        if not tcp_open(worker_port_b, timeout=0.3):
                            continue
                        try:
                            ls_a = json.loads(NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/local_stats", timeout=4).read().decode("utf-8")) or {}
                            ls_b = json.loads(NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port_b}/local_stats", timeout=4).read().decode("utf-8")) or {}
                            pay_b = json.loads(NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port_b}/current_payouts", timeout=4).read().decode("utf-8")) or {}
                            ms_a = json.loads(NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/mesh_status", timeout=4).read().decode("utf-8")) or {}
                            ms_b = json.loads(NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port_b}/mesh_status", timeout=4).read().decode("utf-8")) or {}
                            pa_a_txt = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port}/peer_addresses", timeout=4).read().decode("utf-8").replace('"', "").strip()
                            pa_b_txt = NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port_b}/peer_addresses", timeout=4).read().decode("utf-8").replace('"', "").strip()
                            ls_peers_a = int((ls_a.get("peers") or {}).get("incoming", 0)) + int((ls_a.get("peers") or {}).get("outgoing", 0))
                            ls_peers_b = int((ls_b.get("peers") or {}).get("incoming", 0)) + int((ls_b.get("peers") or {}).get("outgoing", 0))
                            peers_a_cnt = max(ls_peers_a, int(ms_a.get("connected_peers", 0)), len(pa_a_txt.split()) if pa_a_txt else 0)
                            peers_b_cnt = max(ls_peers_b, int(ms_b.get("connected_peers", 0)), len(pa_b_txt.split()) if pa_b_txt else 0)
                            last_mesh_diag = (peers_a_cnt, peers_b_cnt, pay_b, ms_a, ms_b)
                            if (
                                peers_a_cnt >= 1
                                and peers_b_cnt >= 1
                                and "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2" in pay_b
                            ):
                                # Verify connection stays stable with ZERO self-connections / peer bans!
                                time.sleep(1.5)
                                p2p_fh.flush()
                                p2p_fh_b.flush()
                                log_a_chk = open(p2p_log, encoding="utf-8", errors="replace").read()
                                log_b_chk = open(p2p_log_b, encoding="utf-8", errors="replace").read()
                                assert "was connected to self" not in log_a_chk and "was connected to self" not in log_b_chk, (
                                    f"Self-connection detected!\n{read_tail(p2p_log)}\n{read_tail(p2p_log_b)}"
                                )
                                assert "Bad peer banned" not in log_a_chk and "Bad peer banned" not in log_b_chk, (
                                    f"Peer ban detected!\n{read_tail(p2p_log)}\n{read_tail(p2p_log_b)}"
                                )
                                api_b = (json.loads(NO_PROXY_OPENER.open(f"http://127.0.0.1:{worker_port_b}/api/pools", timeout=4).read().decode("utf-8")) or {}).get("pools") or []
                                assert len(api_b) == 1 and int((api_b[0].get("poolStats") or {}).get("connectedMiners", 0)) >= 1 and float((api_b[0].get("poolStats") or {}).get("poolHashrate", 0.0)) > 0.0, api_b
                                mesh_linked = True
                                print(
                                    f"[LIVE-PASS 4/5] Automatic Serverless P2Pool Mesh verified! "
                                    f"Node A peers={peers_a_cnt}, Node B peers={peers_b_cnt}, zero self-bans, synced Node B payouts={pay_b}"
                                )
                                break
                        except Exception as _me:
                            last_mesh_diag = repr(_me)
                    if not mesh_linked:
                        p2p_fh.flush()
                        p2p_fh_b.flush()
                        raise AssertionError(
                            f"Node A & Node B failed to auto-discover & sync shares! diag={last_mesh_diag}\n"
                            f"{read_tail(p2p_log)}\n{read_tail(p2p_log_b)}"
                        )
                finally:
                    if p2p_proc_b.poll() is None:
                        p2p_proc_b.kill()
                        p2p_proc_b.wait()
                    p2p_fh_b.close()
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

        # 4. Verify [LIVE-PASS 5/5]: Abruptly killing launcher parent process (like clicking X on terminal)
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
            print("[LIVE-PASS 5/5] Zero-orphan terminal-close lifecycle verified (child scashd exited & folder unlocked)!")
        finally:
            if holder_proc.poll() is None:
                holder_proc.kill()
                holder_proc.wait()
    finally:
        shutil.rmtree(ci_base, ignore_errors=True)


if __name__ == "__main__":
    run_all_live_tests()
    print("[ALL LIVE INTEGRATION TESTS PASSED]")
