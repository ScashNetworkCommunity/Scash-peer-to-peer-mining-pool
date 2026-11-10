import json
import random
import struct
import sys

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
        self.watch_id = self.wb.new_work_event.watch(self._send_work)

    def rpc_subscribe(self, miner_version=None, session_id=None):
        reactor.callLater(0, self._send_work)
        return [
            ["mining.notify", "ae6812eb4cd7735a302a8a9dd95cf71f"],
            "",
            self.wb.COINBASE_NONCE_LENGTH,
        ]

    def rpc_authorize(self, username, password):
        self.username = username
        reactor.callLater(0, self._send_work)
        return True

    def build_xmrig_job(self):
        x, got_response = self.wb.get_work(*self.wb.preprocess_request('' if self.username is None else self.username))
        jobid = "%016x" % random.randrange(2**64)
        coinb_nonce = struct.pack('<Q', random.randrange(2**64))[:self.wb.COINBASE_NONCE_LENGTH]
        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']
        merkle_root = bitcoin_data.check_merkle_link(bitcoin_data.hash256(new_packed_gentx), x['merkle_link'])

        # 80-byte serialized Scash header (nonce at byte offset 76..79, matching xmrigCC Job.cpp RX_SCASH)
        header_80 = (
            pack.IntType(32).pack(x['version']) +
            pack.IntType(256).pack(x['previous_block']) +
            pack.IntType(256).pack(merkle_root) +
            pack.IntType(32).pack(x['timestamp']) +
            bitcoin_data.FloatingIntegerType().pack(x['bits']) +
            pack.IntType(32).pack(0)
        )
        seed_hash_hex = scash_randomx.get_scash_epoch_seed_hex(x['timestamp'])
        target64 = min(0xffffffffffffffff, max(1, int(x['share_target'] >> 192)))
        target_hex = struct.pack('<Q', target64).encode('hex')

        self.handler_map[jobid] = (x, got_response, coinb_nonce, merkle_root, header_80)
        return {
            "blob": header_80.encode('hex'),
            "job_id": jobid,
            "target": target_hex,
            "algo": "rx/scash",
            "height": x.get('height', 0),
            "seed_hash": seed_hash_hex,
        }

    def _send_work(self):
        if self.proto_ref is not None and getattr(self.proto_ref, 'xmrig_mode', False):
            try:
                job_dict = self.build_xmrig_job()
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
        jobid = str(random.randrange(2**128))
        self.other.svc_mining.rpc_set_difficulty(bitcoin_data.target_to_difficulty(x['share_target'])).addErrback(lambda err: None)
        self.other.svc_mining.rpc_notify(
            jobid,
            getwork._swap4(pack.IntType(256).pack(x['previous_block'])).encode('hex'),
            x['coinb1'].encode('hex'),
            x['coinb2'].encode('hex'),
            [pack.IntType(256).pack(s).encode('hex') for s in x['merkle_link']['branch']],
            getwork._swap4(pack.IntType(32).pack(x['version'])).encode('hex'),
            getwork._swap4(pack.IntType(32).pack(x['bits'].bits)).encode('hex'),
            getwork._swap4(pack.IntType(32).pack(x['timestamp'])).encode('hex'),
            True,
        ).addErrback(lambda err: None)
        self.handler_map[jobid] = (x, got_response)

    def rpc_submit(self, worker_name, job_id, extranonce2, ntime, nonce):
        if job_id not in self.handler_map:
            print >>sys.stderr, "Couldn't link returned work's job id with its handler."
            return False
        entry = self.handler_map[job_id]
        x, got_response = entry[0], entry[1]
        coinb_nonce = extranonce2.decode('hex')
        assert len(coinb_nonce) == self.wb.COINBASE_NONCE_LENGTH
        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']
        merkle_root = bitcoin_data.check_merkle_link(bitcoin_data.hash256(new_packed_gentx), x['merkle_link'])
        ts_val = pack.IntType(32).unpack(getwork._swap4(ntime.decode('hex')))
        nonce_val = pack.IntType(32).unpack(getwork._swap4(nonce.decode('hex')))

        header_80 = (
            pack.IntType(32).pack(x['version']) +
            pack.IntType(256).pack(x['previous_block']) +
            pack.IntType(256).pack(merkle_root) +
            pack.IntType(32).pack(ts_val) +
            bitcoin_data.FloatingIntegerType().pack(x['bits']) +
            pack.IntType(32).pack(nonce_val)
        )
        rx_hash_int, _ = scash_randomx.calculate_rx_hash_and_cm_uint256(header_80)
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

    def submit_xmrig_share(self, job_id, nonce_hex):
        if job_id not in self.handler_map:
            return False, "Stale or unknown job_id"
        x, got_response, coinb_nonce, merkle_root, header_80_base = self.handler_map[job_id]
        raw_nonce = nonce_hex.decode('hex')
        if len(raw_nonce) != 4:
            return False, "Invalid nonce length"

        # Try exact XMRig little-endian buffer placement first, then swapped fallback
        cand_a = header_80_base[:76] + raw_nonce
        rx_hash_a, rx_cm_a = scash_randomx.calculate_rx_hash_and_cm_uint256(cand_a)
        if rx_cm_a <= x['share_target']:
            nonce_int = pack.IntType(32).unpack(raw_nonce)
            rx_hash_int = rx_hash_a
        else:
            cand_b = header_80_base[:76] + raw_nonce[::-1]
            rx_hash_b, _ = scash_randomx.calculate_rx_hash_and_cm_uint256(cand_b)
            nonce_int = pack.IntType(32).unpack(raw_nonce[::-1])
            rx_hash_int = rx_hash_b

        header = dict(
            version=x['version'],
            previous_block=x['previous_block'],
            merkle_root=merkle_root,
            timestamp=x['timestamp'],
            bits=x['bits'],
            nonce=nonce_int,
            rx_hash=rx_hash_int,
        )
        ok = got_response(header, '' if self.username is None else self.username, coinb_nonce)
        return bool(ok), None

    def close(self):
        self.wb.new_work_event.unwatch(self.watch_id)


class StratumProtocol(jsonrpc.LineBasedPeer):
    def connectionMade(self):
        self.xmrig_mode = False
        self.svc_mining = StratumRPCMiningProvider(self.factory.wb, self.other, self.transport, proto_ref=self)

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

        if method == 'login' and isinstance(params, dict):
            self.xmrig_mode = True
            self.svc_mining.username = params.get('login', '')
            job_dict = self.svc_mining.build_xmrig_job()
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
            return

        if method == 'submit' and isinstance(params, dict):
            ok, err_msg = self.svc_mining.submit_xmrig_share(
                params.get('job_id', ''),
                params.get('nonce', '')
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
        self.svc_mining.close()


class StratumServerFactory(protocol.ServerFactory):
    protocol = StratumProtocol

    def __init__(self, wb):
        self.wb = wb
