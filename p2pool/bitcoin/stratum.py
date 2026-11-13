import json
import os
import random
import struct
import sys
import traceback

from twisted.internet import protocol, reactor
from twisted.python import log

from p2pool.bitcoin import data as bitcoin_data, getwork, scash_randomx
from p2pool.util import expiring_dict, jsonrpc, pack


class StratumRPCMiningProvider(object):
    def __init__(self, wb, other, transport, proto_ref=None):
        self.wb = wb
        self.other = other
        self.transport = transport
        self.proto_ref = proto_ref

        self.username = None
        self.handler_map = expiring_dict.ExpiringDict(300)
        self.extranonce1_bin = struct.pack('<I', random.randrange(1, 2**32))
        self.extranonce2_size = max(4, self.wb.COINBASE_NONCE_LENGTH - len(self.extranonce1_bin))
        self._pending_send = None
        self._last_notify_sig = None
        self._last_sent_diff = None
        self._last_xmrig_sig = None
        self._diag_logged = False
        self.watch_id = self.wb.new_work_event.watch(self._on_new_work)

    def _schedule_send_work(self, delay=0.0):
        if self._pending_send is not None and self._pending_send.active():
            self._pending_send.cancel()
        self._pending_send = reactor.callLater(delay, self._send_work)

    def _on_new_work(self):
        self._schedule_send_work(0.0)

    def rpc_subscribe(self, *args):
        self._schedule_send_work(0.08)
        return [
            [
                ["mining.set_difficulty", "ae6812eb4cd7735a302a8a9dd95cf71f"],
                ["mining.notify", "ae6812eb4cd7735a302a8a9dd95cf71f"],
            ],
            self.extranonce1_bin.encode('hex'),
            int(self.extranonce2_size),
        ]

    def rpc_authorize(self, username='', password='', *args):
        self.username = username
        self._schedule_send_work(0.02)
        return True

    def rpc_extranonce_subscribe(self, *args):
        return True

    def build_xmrig_job(self, force=False):
        x, got_response = self.wb.get_work(*self.wb.preprocess_request('' if self.username is None else self.username))
        bits_int = x['bits'].bits if hasattr(x['bits'], 'bits') else int(x['bits'])
        eff_target = x.get('target', x['share_target'])
        min_hashes = 1024 if os.environ.get('SCASH_CI_FAST_DIFF') == '1' else 4096
        max_eff_target = (2**256) // min_hashes - 1
        if eff_target > max_eff_target:
            eff_target = max_eff_target
        target64 = min(0xffffffffffffffff, max(1, int(eff_target >> 192)))

        xmrig_sig = (
            x['previous_block'],
            x['coinb1'],
            x['coinb2'],
            tuple(x['merkle_link']['branch']),
            x['version'],
            bits_int,
            x['timestamp'],
            target64,
        )
        if not force and self._last_xmrig_sig == xmrig_sig:
            return None
        self._last_xmrig_sig = xmrig_sig

        jobid = "%016x" % random.randrange(2**64)
        coinb_nonce = struct.pack('<Q', random.randrange(2**64))[:self.wb.COINBASE_NONCE_LENGTH]
        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']
        merkle_root = bitcoin_data.check_merkle_link(bitcoin_data.hash256(new_packed_gentx), x['merkle_link'])

        header_80 = (
            pack.IntType(32).pack(x['version']) +
            pack.IntType(256).pack(x['previous_block']) +
            pack.IntType(256).pack(merkle_root) +
            pack.IntType(32).pack(x['timestamp']) +
            pack.IntType(32).pack(bits_int) +
            pack.IntType(32).pack(0)
        )
        # Full 112-byte Scash CBlockHeader (80-byte Bitcoin header + 32 zero bytes for hashRandomX = 224 hex chars)!
        header_112 = header_80 + ('\x00' * 32)
        seed_hash_hex = scash_randomx.get_scash_epoch_seed_hex(x['timestamp'])
        target_hex = struct.pack('<Q', target64).encode('hex')

        self.handler_map[jobid] = (x, got_response, coinb_nonce, merkle_root, header_80, eff_target)
        return {
            "blob": header_112.encode('hex'),
            "job_id": jobid,
            "target": target_hex,
            "algo": "rx/scash",
            "height": x.get('height', 0),
            "seed_hash": seed_hash_hex,
        }

    def _send_work(self):
        self._pending_send = None
        if self.proto_ref is not None and getattr(self.proto_ref, 'xmrig_mode', False):
            try:
                job_dict = self.build_xmrig_job(force=False)
                if job_dict is not None:
                    self.proto_ref.send_json_line({
                        "jsonrpc": "2.0",
                        "method": "job",
                        "params": job_dict,
                    })
            except Exception:
                log.err()
            return

        try:
            x, got_response = self.wb.get_work(*self.wb.preprocess_request('' if self.username is None else self.username))
        except Exception:
            log.err()
            self.transport.loseConnection()
            return

        bits_int = x['bits'].bits if hasattr(x['bits'], 'bits') else int(x['bits'])
        eff_target = x.get('target', x['share_target'])
        expected_hashes = max((1024.0 if os.environ.get('SCASH_CI_FAST_DIFF') == '1' else 4096.0), float(2**256) / max(1.0, float(eff_target)))
        scash_diff = expected_hashes / 65536.0

        notify_sig = (
            x['previous_block'],
            x['coinb1'],
            x['coinb2'],
            tuple(x['merkle_link']['branch']),
            x['version'],
            bits_int,
            x['timestamp'],
        )
        if (
            self._last_notify_sig == notify_sig
            and self._last_sent_diff is not None
            and abs(scash_diff - self._last_sent_diff) <= 0.05 * self._last_sent_diff
        ):
            return

        clean_jobs = (self._last_notify_sig is None) or (notify_sig[0] != self._last_notify_sig[0])
        self._last_notify_sig = notify_sig
        self._last_sent_diff = scash_diff

        jobid = "%016x" % random.randrange(2**64)
        diff_msg = json.dumps({
            "id": None,
            "jsonrpc": "2.0",
            "method": "mining.set_difficulty",
            "params": [scash_diff],
        }) + "\n"
        notify_msg = json.dumps({
            "id": None,
            "jsonrpc": "2.0",
            "method": "mining.notify",
            "params": [
                jobid,
                getwork._swap4(pack.IntType(256).pack(x['previous_block'])).encode('hex'),
                x['coinb1'].encode('hex'),
                x['coinb2'].encode('hex'),
                [pack.IntType(256).pack(s).encode('hex') for s in x['merkle_link']['branch']],
                getwork._swap4(pack.IntType(32).pack(x['version'])).encode('hex'),
                getwork._swap4(pack.IntType(32).pack(bits_int)).encode('hex'),
                getwork._swap4(pack.IntType(32).pack(x['timestamp'])).encode('hex'),
                clean_jobs,
            ],
        }) + "\n"
        self.transport.write(diff_msg + notify_msg)
        self.handler_map[jobid] = (x, got_response)

    def rpc_submit(self, worker_name, job_id, extranonce2, ntime, nonce):
        if job_id not in self.handler_map:
            print >>sys.stderr, "Couldn't link returned work's job id with its handler."
            return False
        entry = self.handler_map[job_id]
        x, got_response = entry[0], entry[1]
        raw_en2 = extranonce2.decode('hex')
        if len(raw_en2) == self.extranonce2_size and (len(self.extranonce1_bin) + len(raw_en2)) == self.wb.COINBASE_NONCE_LENGTH:
            coinb_nonce = self.extranonce1_bin + raw_en2
        elif len(raw_en2) == self.wb.COINBASE_NONCE_LENGTH:
            coinb_nonce = raw_en2
        else:
            coinb_nonce = (self.extranonce1_bin + raw_en2)[:self.wb.COINBASE_NONCE_LENGTH].ljust(self.wb.COINBASE_NONCE_LENGTH, '\x00')

        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']
        merkle_root = bitcoin_data.check_merkle_link(bitcoin_data.hash256(new_packed_gentx), x['merkle_link'])
        bits_int = x['bits'].bits if hasattr(x['bits'], 'bits') else int(x['bits'])
        _mh = 1024 if os.environ.get('SCASH_CI_FAST_DIFF') == '1' else 4096
        eff_target = min((2**256) // _mh - 1, x.get('target', x['share_target']))

        ntime_padded = ntime.strip()
        if len(ntime_padded) % 2 != 0:
            ntime_padded = '0' + ntime_padded
        ntime_padded = ntime_padded.zfill(8)

        nonce_padded = nonce.strip()
        if nonce_padded.startswith(('0x', '0X')):
            nonce_padded = nonce_padded[2:]
        if len(nonce_padded) % 2 != 0:
            nonce_padded = '0' + nonce_padded
        nonce_padded = nonce_padded.zfill(8)

        ts_candidates = []
        for tc in (
            int(ntime_padded, 16),
            x['timestamp'],
            pack.IntType(32).unpack(ntime_padded.decode('hex')),
        ):
            if tc not in ts_candidates:
                ts_candidates.append(tc)

        nonce_candidates = []
        for nc in (
            pack.IntType(32).unpack(nonce_padded.decode('hex')),
            int(nonce_padded, 16),
        ):
            if nc not in nonce_candidates:
                nonce_candidates.append(nc)

        best_pair = (ts_candidates[0], nonce_candidates[0], 0, 2**256)
        matched = False
        for tv in ts_candidates:
            for nv in nonce_candidates:
                hdr_try = (
                    pack.IntType(32).pack(x['version']) +
                    pack.IntType(256).pack(x['previous_block']) +
                    pack.IntType(256).pack(merkle_root) +
                    pack.IntType(32).pack(tv) +
                    pack.IntType(32).pack(bits_int) +
                    pack.IntType(32).pack(nv)
                )
                rxh_try, rxcm_try = scash_randomx.calculate_rx_hash_and_cm_uint256(hdr_try)
                if rxcm_try < best_pair[3]:
                    best_pair = (tv, nv, rxh_try, rxcm_try)
                if rxcm_try <= eff_target:
                    best_pair = (tv, nv, rxh_try, rxcm_try)
                    matched = True
                    break
            if matched:
                break

        ts_val, nonce_val, rx_hash_int, _ = best_pair
        header = dict(
            version=x['version'],
            previous_block=x['previous_block'],
            merkle_root=merkle_root,
            timestamp=ts_val,
            bits=x['bits'],
            nonce=nonce_val,
            rx_hash=rx_hash_int,
        )
        return got_response(header, worker_name, coinb_nonce)

    def submit_xmrig_share(self, job_id, nonce_hex, result_hex=''):
        if job_id not in self.handler_map:
            return False, "Stale or unknown job_id"
        entry = self.handler_map[job_id]
        x, got_response, coinb_nonce, merkle_root, header_80_base = entry[0], entry[1], entry[2], entry[3], entry[4]
        eff_target = entry[5] if len(entry) > 5 else x.get('target', x['share_target'])
        raw_nonce = nonce_hex.decode('hex')
        if len(raw_nonce) != 4:
            return False, "Invalid nonce length"

        cand_a = header_80_base[:76] + raw_nonce
        rx_hash_a, rx_cm_a = scash_randomx.calculate_rx_hash_and_cm_uint256(cand_a)
        if rx_cm_a <= eff_target:
            nonce_int = pack.IntType(32).unpack(raw_nonce)
            rx_hash_int = rx_hash_a
            rx_cm_best = rx_cm_a
        else:
            cand_b = header_80_base[:76] + raw_nonce[::-1]
            rx_hash_b, rx_cm_b = scash_randomx.calculate_rx_hash_and_cm_uint256(cand_b)
            if rx_cm_b <= eff_target:
                nonce_int = pack.IntType(32).unpack(raw_nonce[::-1])
                rx_hash_int = rx_hash_b
                rx_cm_best = rx_cm_b
            else:
                print >>sys.stderr, (
                    "[XMRIG-SUBMIT-DIAG] rx_cm > eff_target: job=%s nonce=%s xmrig_res=%s cm_a=%x cm_b=%x target=%x"
                    % (job_id, nonce_hex, result_hex, rx_cm_a, rx_cm_b, eff_target)
                )
                sys.stderr.flush()
                return False, "Low difficulty share"

        header = dict(
            version=x['version'],
            previous_block=x['previous_block'],
            merkle_root=merkle_root,
            timestamp=x['timestamp'],
            bits=x['bits'],
            nonce=nonce_int,
            rx_hash=rx_hash_int,
        )
        try:
            ok = got_response(header, '' if self.username is None else self.username, coinb_nonce)
            sys.stdout.flush()
            return bool(ok), None
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            return False, str(e)

    def close(self):
        if self._pending_send is not None and self._pending_send.active():
            self._pending_send.cancel()
            self._pending_send = None
        try:
            self.wb.new_work_event.unwatch(self.watch_id)
        except Exception:
            pass
        try:
            if hasattr(self.handler_map, '_expire_loop') and self.handler_map._expire_loop.running:
                self.handler_map._expire_loop.stop()
        except Exception:
            pass


class StratumProtocol(jsonrpc.LineBasedPeer):
    def connectionMade(self):
        if hasattr(jsonrpc.LineBasedPeer, 'connectionMade'):
            jsonrpc.LineBasedPeer.connectionMade(self)
        self.xmrig_mode = False
        self.svc_mining = StratumRPCMiningProvider(self.factory.wb, getattr(self, 'other', None), self.transport, proto_ref=self)

    def send_json_line(self, payload):
        self.transport.write(json.dumps(payload) + "\n")

    def lineReceived(self, line):
        line_str = line.strip()
        if not line_str:
            return
        try:
            msg = json.loads(line_str)
        except Exception:
            return jsonrpc.LineBasedPeer.lineReceived(self, line)

        method = msg.get('method', '')
        req_id = msg.get('id', 1)
        params = msg.get('params', {})

        if method == 'mining.subscribe':
            plist = params if isinstance(params, list) else []
            res = self.svc_mining.rpc_subscribe(*plist)
            self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": None, "result": res})
            return

        if method == 'mining.authorize':
            plist = params if isinstance(params, list) else []
            res = self.svc_mining.rpc_authorize(*plist)
            self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": None, "result": bool(res)})
            return

        if method == 'mining.extranonce.subscribe':
            self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": None, "result": True})
            return

        if method in ('mining.submit', 'eth_submitWork') and isinstance(params, list) and len(params) >= 5:
            try:
                ok = bool(self.svc_mining.rpc_submit(params[0], params[1], params[2], params[3], params[4]))
                if ok:
                    self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": None, "result": True})
                else:
                    self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": [23, "Low difficulty share", None], "result": False})
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": [20, str(e), None], "result": False})
            return

        if method == 'login' and isinstance(params, dict):
            self.xmrig_mode = True
            if self.svc_mining._pending_send is not None and self.svc_mining._pending_send.active():
                self.svc_mining._pending_send.cancel()
                self.svc_mining._pending_send = None
            self.svc_mining.username = params.get('login', '')
            try:
                job_dict = self.svc_mining.build_xmrig_job(force=True)
                self.send_json_line({
                    "id": req_id,
                    "jsonrpc": "2.0",
                    "error": None,
                    "result": {
                        "id": "scash-p2pool-session",
                        "job": job_dict,
                        "status": "OK",
                    }
                })
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": {"code": -1, "message": str(e)}, "result": None})
            return

        if method == 'submit' and isinstance(params, dict):
            ok, err_msg = self.svc_mining.submit_xmrig_share(
                params.get('job_id', ''),
                params.get('nonce', ''),
                params.get('result', '')
            )
            if ok:
                self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": None, "result": {"status": "OK"}})
            else:
                self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": {"code": -1, "message": err_msg or "Low difficulty share"}, "result": None})
            return

        if method == 'keepalived':
            self.send_json_line({"id": req_id, "jsonrpc": "2.0", "error": None, "result": {"status": "KEEPALIVED"}})
            return

        return jsonrpc.LineBasedPeer.lineReceived(self, line)

    def connectionLost(self, reason):
        if hasattr(self, 'svc_mining') and self.svc_mining is not None:
            self.svc_mining.close()


class StratumServerFactory(protocol.ServerFactory):
    protocol = StratumProtocol

    def __init__(self, wb):
        self.wb = wb
