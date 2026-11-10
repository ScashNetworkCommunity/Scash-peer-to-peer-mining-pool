#!/usr/bin/env python
"""
Automated Verification Suite for Scash P2Pool (QtKawaii + Built-in XMRig + Community Nodes Edition).
"""
from __future__ import print_function
import os
import shutil
import sys
import tempfile

def load_module_from_path(name, path):
    if sys.version_info[0] >= 3:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    else:
        import imp
        return imp.load_source(name, path)

def test_bech32_scash():
    bech32_scash = load_module_from_path("bech32_scash", "p2pool/bitcoin/bech32_scash.py")
    sample = "scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2"
    witver, witprog = bech32_scash.decode_scash_address(sample, "scash")
    assert witver == 0 and witprog is not None and len(witprog) == 20
    assert bech32_scash.encode_scash_address(witprog, "scash", 0) == sample
    print("[PASS] 1/5 Bech32 scash1... address decode & roundtrip verified:", sample)

def test_112_byte_randomx_header():
    scash_randomx = load_module_from_path("scash_randomx", "p2pool/bitcoin/scash_randomx.py")
    raw_80 = b"\x01" * 80
    padded_112 = scash_randomx.pack_header_for_randomx(raw_80)
    assert len(padded_112) == 112 and padded_112[80:] == (b"\x00" * 32)
    assert scash_randomx.get_pow_commitment_int256(padded_112) > 0
    print("[PASS] 2/5 112-byte Scash block header & RandomX commitment verified.")

def test_community_nodes_scash_conf():
    scash_nodes = load_module_from_path("scash_nodes", "p2pool/scash_nodes.py")
    tmp_dir = tempfile.mkdtemp(prefix="scash_conf_test_")
    try:
        conf_path = scash_nodes.ensure_scash_conf_with_nodes(custom_datadir=tmp_dir)
        content = open(conf_path).read()
        assert "addnode=scash.tv:8343" in content
        assert "addnode=scash.pool-pay.com:8343" in content
        assert "addnode=satoshicash.cedric-crispin.com:8343" in content
        assert "rpcport=8342" in content and "port=8343" in content
        print("[PASS] 3/5 Community Scash nodes (addnode=...) injected into scash.conf (%d nodes)." % len(scash_nodes.DEFAULT_SCASH_ADDNODES))
    finally:
        shutil.rmtree(tmp_dir)

def test_builtin_xmrig_controller():
    xmrig_manager = load_module_from_path("xmrig_manager", "p2pool/xmrig_manager.py")
    ctrl = xmrig_manager.XMRigController(stratum_host="127.0.0.1", stratum_port=8345)
    status = ctrl.start_mining(wallet="scash1qj7zj3c25e3mmjewcmhngsr63sfxra2vd9ehqq2", threads=4, worker="kawaii_test")
    assert status["ok"] is True and status["running"] is True
    assert status["algo"] == "rx/scash"
    assert os.path.exists(status["config_path"])
    cfg_text = open(status["config_path"]).read()
    assert '"algo": "rx/scash"' in cfg_text and '"127.0.0.1:8345"' in cfg_text
    ctrl.stop_mining()
    print("[PASS] 4/5 Built-in XMRig (rx/scash) auto-config & controller verified.")

def test_kawaii_ui():
    html = open("web-static/index.html").read()
    assert "#170e29" in html and "/miner_start" in html and "rx/scash" in html
    print("[PASS] 5/5 QtKawaii Web UI with built-in XMRig auto-trigger verified.")

if __name__ == "__main__":
    test_bech32_scash()
    test_112_byte_randomx_header()
    test_community_nodes_scash_conf()
    test_builtin_xmrig_controller()
    test_kawaii_ui()
    print("=== ALL 5 SCASH P2POOL + BUILT-IN XMRIG + COMMUNITY NODES TESTS PASSED ===")
