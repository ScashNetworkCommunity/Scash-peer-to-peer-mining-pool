"""
Automatic Serverless Peer-to-Peer Mesh & Decentralized UDP Hole-Punching for Scash P2Pool (v0.3.8).
Compatible with BOTH PyPy 2.7 (bundled runtime) and Python 3.x!

Every miner running Start-Scash-P2Pool automatically runs a full Scash Core 30.4.0 node
(:8343) + P2Pool sharechain node (:8344) and connects directly to other miners with
ZERO central seed server and ZERO mandatory port forwarding:

1. Live Home LAN Auto-Mesh: UDP Broadcast + Subnet Broadcast + Multicast (239.83.44.1)
   beacons on :8344 (+1 fallback) with strict instance_id deduplication & self-dial
   protection, plus /24 LAN TCP :8344 fallback sweep for broadcast-filtering routers.
2. Automatic Router Port Opening: Non-blocking pure-Python UPnP IGD (v1/v2) + PCP
   (RFC 6887) + NAT-PMP (RFC 6886) mapping for P2Pool (:8344) and Scash Core (:8343).
3. Serverless Global Swarm Rendezvous (BEP 15 Open UDP Swarm + Scash Blockchain Gossip):
   Announces & fetches live Scash P2Pool miner endpoints across independent public UDP
   swarm trackers AND queries local `scashd` (`-uacomment=p2pool`, `getpeerinfo` +
   `getnodeaddresses(256)`), plus caches verified peers in `p2pool_verified_peers.json`.
4. Decentralized STUN + Reliable UDP Hole-Punching (`SHP1`, RFC 5128 / RFC 5389):
   Shares a single UDP socket for STUN external `(ip, udp_port)` discovery and reliable
   windowed stream-over-UDP hole-punching into `127.0.0.1:<p2p_port>`, allowing even two
   miners who are BOTH behind closed UPnP-disabled routers (e.g. AT&T BGW gateways or
   Endpoint-Independent CGNAT) to link up directly and safely without port forwarding.
"""
from __future__ import print_function
import base64
import hashlib
import inspect
import json
import os
import platform
import random
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

try:
    import urllib.request as _ureq
except ImportError:
    import urllib2 as _ureq

_NO_PROXY_OPENER = _ureq.build_opener(_ureq.ProxyHandler({}))

BEACON_MAGIC = "SCASH_P2P_V1"
MULTICAST_GRP = "239.83.44.1"

SHP_MAGIC = b"SHP1"
SHP_HELLO = 1
SHP_HELLO_ACK = 2
SHP_OPEN = 3
SHP_OPEN_ACK = 4
SHP_DATA = 5
SHP_ACK = 6
SHP_CLOSE = 7
SHP_MSS = 1100
SHP_WINDOW = 12
SHP_MAX_TUNNELS = 4

DEFAULT_SWARM_TRACKERS = (
    ("tracker.opentrackr.org", 1337),
    ("open.stealth.si", 80),
    ("exodus.desync.com", 6969),
    ("tracker.torrent.eu.org", 451),
    ("open.demonii.com", 1337),
)

DEFAULT_STUN_SERVERS = (
    ("stun.cloudflare.com", 3478),
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
)

MESH_STATE = {
    "started": False,
    "instance_id": "%016x" % random.randrange(1, 2**64),
    "net_id_hex": "7363617368703236",
    "p2p_port": 8344,
    "udp_port": 0,
    "upnp_mapped": False,
    "natpmp_mapped": False,
    "pcp_mapped": False,
    "external_ip": None,
    "external_udp_port": 0,
    "nat_mapping": "unknown",
    "lan_ips": [],
    "discovered_lan_peers": [],
    "discovered_wan_peers": [],
    "swarm_peers_found": 0,
    "holepunch_tunnels": 0,
    "connected_peers": 0,
    "connected_wan_peers": 0,
    "connected_lan_peers": 0,
    "https_rendezvous_peers": 0,
    "incoming_peers": 0,
    "outgoing_peers": 0,
}

_ACTIVE_P2P_NODE = None
_SHARED_UDP_SOCK = None
_VERIFIED_OPEN_PEERS = set()
_RECENT_UNICAST_REPLY = {}
_DIALED_INSTANCES = {}
_PROBED_WAN_TS = {}
_PENDING_STUN_TX = {}
_STUN_OBSERVATIONS = []
_UDP_TUNNELS = {}
_UDP_TUNNELS_LOCK = threading.Lock()
_HELLO_RATE_LIMIT = {}
_PUNCH_TARGETS = {}
_HTTPS_HP_CANDIDATES = {}
_STOP_EVENT = threading.Event()


def _disable_win_udp_connreset(sock):
    """Prevents Windows WinSock WSAECONNRESET (10054) on UDP sockets during hole-punch bursts."""
    if platform.system() == "Windows":
        try:
            ioctl_code = getattr(socket, "SIO_UDP_CONNRESET", 0x9800000C)
            sock.ioctl(ioctl_code, struct.pack("I", 0))
        except Exception:
            pass


def _refresh_live_peer_counts():
    p2p_node = _ACTIVE_P2P_NODE
    if p2p_node is None:
        return
    try:
        with _UDP_TUNNELS_LOCK:
            active_tuns = [t for t in _UDP_TUNNELS.values() if not t.closed]
            MESH_STATE["holepunch_tunnels"] = len(active_tuns)
            wan_tun_ports = set()
            wan_est_tuns = 0
            for t in active_tuns:
                if t.established and _is_routable_public_ipv4(t.remote_addr[0]):
                    wan_est_tuns += 1
                    if getattr(t, "local_bridge_port", 0):
                        wan_tun_ports.add(int(t.local_bridge_port))
                    if getattr(t, "local_tcp_port", 0):
                        wan_tun_ports.add(int(t.local_tcp_port))

        peers = getattr(p2p_node, "peers", {}) or {}
        vals = list(peers.values())
        inc = 0
        out = 0
        wan_cnt = 0
        loop_unmatched = 0
        for proto in vals:
            if getattr(proto, "incoming", False):
                inc += 1
            else:
                out += 1
            paddr = getattr(proto, "addr", None)
            if paddr and len(paddr) >= 2:
                p_ip, p_port = str(paddr[0]).strip(), int(paddr[1])
                if _is_routable_public_ipv4(p_ip):
                    wan_cnt += 1
                elif p_ip.startswith("127."):
                    if p_port in wan_tun_ports:
                        wan_cnt += 1
                    else:
                        loop_unmatched += 1
        if loop_unmatched > 0 and wan_est_tuns > wan_cnt:
            wan_cnt += min(loop_unmatched, wan_est_tuns - wan_cnt)
        lan_cnt = max(0, len(vals) - wan_cnt)

        MESH_STATE["connected_peers"] = len(vals)
        MESH_STATE["connected_wan_peers"] = wan_cnt
        MESH_STATE["connected_lan_peers"] = lan_cnt
        MESH_STATE["incoming_peers"] = inc
        MESH_STATE["outgoing_peers"] = out
    except Exception:
        pass


def get_mesh_status():
    _refresh_live_peer_counts()
    return {
        "started": bool(MESH_STATE["started"]),
        "instance_id": str(MESH_STATE["instance_id"]),
        "p2p_port": int(MESH_STATE["p2p_port"]),
        "udp_port": int(MESH_STATE["udp_port"]),
        "upnp_mapped": bool(MESH_STATE["upnp_mapped"]),
        "natpmp_mapped": bool(MESH_STATE["natpmp_mapped"]),
        "pcp_mapped": bool(MESH_STATE["pcp_mapped"]),
        "external_ip": MESH_STATE["external_ip"],
        "external_udp_port": int(MESH_STATE["external_udp_port"]),
        "nat_mapping": str(MESH_STATE["nat_mapping"]),
        "lan_ips": list(MESH_STATE["lan_ips"]),
        "discovered_lan_peers": list(MESH_STATE["discovered_lan_peers"])[-20:],
        "discovered_wan_peers": list(MESH_STATE["discovered_wan_peers"])[-20:],
        "swarm_peers_found": int(MESH_STATE["swarm_peers_found"]),
        "https_rendezvous_peers": int(MESH_STATE["https_rendezvous_peers"]),
        "holepunch_tunnels": int(MESH_STATE["holepunch_tunnels"]),
        "connected_peers": int(MESH_STATE["connected_peers"]),
        "connected_wan_peers": int(MESH_STATE["connected_wan_peers"]),
        "connected_lan_peers": int(MESH_STATE["connected_lan_peers"]),
        "incoming_peers": int(MESH_STATE["incoming_peers"]),
        "outgoing_peers": int(MESH_STATE["outgoing_peers"]),
    }


def _is_valid_ipv4(ip):
    if not ip or not isinstance(ip, (str, bytes)):
        return False
    s = ip.decode("ascii", "ignore") if isinstance(ip, bytes) else str(ip)
    parts = s.strip().split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
        return all(0 <= n <= 255 for n in nums)
    except Exception:
        return False


def _is_private_rfc1918(ip):
    if not _is_valid_ipv4(ip):
        return False
    a, b, _, _ = [int(x) for x in str(ip).strip().split(".")]
    if a == 10:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def _is_routable_public_ipv4(ip):
    if not _is_valid_ipv4(ip) or _is_private_rfc1918(ip):
        return False
    a, b, _, _ = [int(x) for x in str(ip).strip().split(".")]
    if a in (0, 127) or a >= 224:
        return False
    if a == 169 and b == 254:
        return False
    if a == 100 and 64 <= b <= 127:
        return False
    return True


def get_local_lan_ipv4s():
    found = []

    def _add(cand):
        if not cand:
            return
        s = cand.decode("ascii", "ignore") if isinstance(cand, bytes) else str(cand)
        s = s.strip()
        if _is_valid_ipv4(s) and not s.startswith("127.") and not s.startswith("169.254.") and s not in found:
            found.append(s)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        _add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in ips:
            _add(ip)
    except Exception:
        pass

    try:
        if platform.system() == "Windows":
            kw = {"creationflags": 0x08000000}
            out = subprocess.check_output(["ipconfig"], **kw).decode("utf-8", "replace")
            for m in re.finditer(r"IPv4[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", out):
                _add(m.group(1))
        else:
            out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"]).decode("utf-8", "replace")
            for m in re.finditer(r"inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/", out):
                _add(m.group(1))
    except Exception:
        pass

    return found


def is_self_endpoint(ip, port):
    """Returns True if (ip, port) points to THIS local P2Pool node's own listening TCP/UDP port."""
    try:
        p = int(port)
    except Exception:
        return True
    my_ports = set([int(MESH_STATE["p2p_port"])])
    if MESH_STATE.get("udp_port"):
        my_ports.add(int(MESH_STATE["udp_port"]))
    if MESH_STATE.get("external_udp_port"):
        my_ports.add(int(MESH_STATE["external_udp_port"]))
    if p not in my_ports:
        return False
    s_ip = str(ip).strip()
    if s_ip in ("0.0.0.0", "") or s_ip.startswith("127."):
        return True
    if MESH_STATE.get("external_ip") and s_ip == str(MESH_STATE["external_ip"]):
        return True
    if p == int(MESH_STATE["p2p_port"]):
        if s_ip in (MESH_STATE.get("lan_ips") or []) or s_ip in get_local_lan_ipv4s():
            return True
    return False


# ==============================================================================
# Reliable Windowed Stream-over-UDP Hole-Punching Engine (`SHP1`)
# ==============================================================================

def pack_shp_packet(ptype, conn_id, seq, ack, payload=b""):
    if not isinstance(payload, bytes):
        payload = payload.encode("latin1")
    crc = zlib.crc32(payload) & 0xFFFF
    return (
        struct.pack(
            "!4sBIIIH",
            SHP_MAGIC,
            int(ptype) & 0xFF,
            int(conn_id) & 0xFFFFFFFF,
            int(seq) & 0xFFFFFFFF,
            int(ack) & 0xFFFFFFFF,
            crc,
        )
        + payload
    )


def unpack_shp_packet(pkt):
    if not pkt or len(pkt) < 19 or pkt[:4] != SHP_MAGIC:
        return None
    _m, ptype, cid, seq, ack, crc = struct.unpack("!4sBIIIH", pkt[:19])
    payload = pkt[19:]
    if (zlib.crc32(payload) & 0xFFFF) != crc:
        return None
    return ptype, cid, seq, ack, payload


class _UdpTunnelSession(object):
    """Bridges a punched UDP peer link <-> local 127.0.0.1 P2Pool TCP socket reliably."""

    def __init__(self, conn_id, remote_addr, remote_inst, initiator, udp_sock, p2p_node=None, target_local_port=None):
        self.conn_id = int(conn_id) & 0xFFFFFFFF
        self.remote_addr = (str(remote_addr[0]), int(remote_addr[1]))
        self.remote_inst = str(remote_inst)
        self.initiator = bool(initiator)
        self.udp_sock = udp_sock
        self.p2p_node = p2p_node
        self.target_local_port = int(target_local_port or MESH_STATE["p2p_port"])
        self.listen_sock = None
        self.local_bridge_port = 0
        self.local_tcp_port = 0
        self.tcp_sock = None
        self.established = False
        self.closed = False
        self.dial_triggered = False

        self.next_seq = 0
        self.send_base = 0
        self.unacked = {}  # seq -> [payload_bytes, last_sent_ts, retries]
        self.recv_next = 0
        self.rx_oob = {}   # seq -> payload_bytes
        self.rx_to_tcp_buf = bytearray()

        now = time.time()
        self.created_ts = now
        self.last_rx_ts = now
        self.last_open_sent_ts = 0.0
        self.last_keepalive_ts = now
        self.open_retries = 0
        self.on_initiator_ready = None  # optional test callback(local_bridge_port)

    def start_initiator_listener(self, on_ready_cb=None):
        self.on_initiator_ready = on_ready_cb
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("127.0.0.1", 0))
        ls.listen(1)
        ls.setblocking(False)
        self.listen_sock = ls
        self.local_bridge_port = ls.getsockname()[1]
        self._send_open()
        return self.local_bridge_port

    def start_responder_socket(self):
        cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cs.settimeout(2.5)
        cs.connect(("127.0.0.1", self.target_local_port))
        try:
            self.local_tcp_port = int(cs.getsockname()[1])
        except Exception:
            pass
        cs.setblocking(False)
        self.tcp_sock = cs
        self.established = True
        self._send_udp(SHP_OPEN_ACK, 0, 0, b"")

    def _send_udp(self, ptype, seq, ack, payload=b""):
        try:
            pkt = pack_shp_packet(ptype, self.conn_id, seq, ack, payload)
            self.udp_sock.sendto(pkt, self.remote_addr)
        except Exception:
            pass

    def _send_open(self):
        meta = ("%s|%s" % (MESH_STATE["net_id_hex"], MESH_STATE["instance_id"])).encode("ascii")
        self._send_udp(SHP_OPEN, 0, 0, meta)
        self.last_open_sent_ts = time.time()
        self.open_retries += 1

    def on_udp_packet(self, ptype, seq, ack, payload):
        if self.closed:
            return
        self.last_rx_ts = time.time()

        if ptype == SHP_OPEN:
            self._send_udp(SHP_OPEN_ACK, 0, self.recv_next, b"")
            return

        if ptype == SHP_OPEN_ACK:
            if not self.established:
                self.established = True
                if self.initiator and not self.dial_triggered:
                    self.dial_triggered = True
                    if self.on_initiator_ready is not None:
                        try:
                            self.on_initiator_ready(self.local_bridge_port)
                        except Exception:
                            pass
                    elif self.p2p_node is not None:
                        print(
                            "[AutoMesh] Punched direct UDP NAT tunnel to peer %s:%d -> local bridge 127.0.0.1:%d"
                            % (self.remote_addr[0], self.remote_addr[1], self.local_bridge_port)
                        )
                        _schedule_connect(
                            self.p2p_node,
                            "127.0.0.1",
                            self.local_bridge_port,
                            immediate=True,
                            source="udp_holepunch",
                            allow_loopback_bridge=True,
                        )
            return

        if ptype == SHP_CLOSE:
            self.close(notify_remote=False)
            return

        # Process cumulative ACK on both SHP_DATA and SHP_ACK
        if ack > self.send_base:
            for k in list(self.unacked.keys()):
                if k < ack:
                    self.unacked.pop(k, None)
            self.send_base = ack

        if ptype == SHP_DATA and payload:
            if seq == self.recv_next:
                self.rx_to_tcp_buf.extend(payload)
                self.recv_next += 1
                while self.recv_next in self.rx_oob:
                    nxt = self.rx_oob.pop(self.recv_next)
                    self.rx_to_tcp_buf.extend(nxt)
                    self.recv_next += 1
                self._send_udp(SHP_ACK, 0, self.recv_next, b"")
            elif self.recv_next < seq < (self.recv_next + 32):
                if len(self.rx_oob) < 32 and seq not in self.rx_oob:
                    self.rx_oob[seq] = payload
                self._send_udp(SHP_ACK, 0, self.recv_next, b"")
            elif seq < self.recv_next:
                self._send_udp(SHP_ACK, 0, self.recv_next, b"")

    def tick(self, now):
        if self.closed:
            return
        if (now - self.last_rx_ts) > 45.0:
            self.close(notify_remote=True)
            return

        if not self.established:
            if self.initiator:
                if self.open_retries > 16:
                    self.close(notify_remote=False)
                    return
                if (now - self.last_open_sent_ts) >= 0.35:
                    self._send_open()
            elif (now - self.created_ts) > 10.0:
                self.close(notify_remote=False)
            return

        if self.listen_sock is not None and self.tcp_sock is None:
            try:
                cs, _ = self.listen_sock.accept()
                cs.setblocking(False)
                self.tcp_sock = cs
                try:
                    self.listen_sock.close()
                except Exception:
                    pass
                self.listen_sock = None
            except Exception:
                if (now - self.created_ts) > 12.0:
                    self.close(notify_remote=True)
                    return

        # Retransmit unacknowledged segments
        if self.unacked:
            sent_n = 0
            for seq in sorted(self.unacked.keys()):
                item = self.unacked.get(seq)
                if not item:
                    continue
                chunk, last_ts, retries = item
                if retries > 28:
                    self.close(notify_remote=True)
                    return
                rto = min(1.2, 0.20 * (1.35 ** min(retries, 6)))
                if (now - last_ts) >= rto:
                    self._send_udp(SHP_DATA, seq, self.recv_next, chunk)
                    item[1] = now
                    item[2] = retries + 1
                    sent_n += 1
                    if sent_n >= 3:
                        break
        elif (now - self.last_keepalive_ts) >= 12.0:
            self.last_keepalive_ts = now
            self._send_udp(SHP_ACK, 0, self.recv_next, b"")

    def close(self, notify_remote=False):
        if self.closed:
            return
        self.closed = True
        if notify_remote:
            self._send_udp(SHP_CLOSE, 0, self.recv_next, b"")
        for s in (self.tcp_sock, self.listen_sock):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        self.tcp_sock = None
        self.listen_sock = None


def _has_tunnel_with_peer(remote_addr, remote_inst):
    with _UDP_TUNNELS_LOCK:
        for t in _UDP_TUNNELS.values():
            if not t.closed and (t.remote_addr == remote_addr or (remote_inst and t.remote_inst == remote_inst)):
                return True
    return False


def _handle_shp_datagram(p2p_node, udp_sock, data, addr, target_local_port=None, on_initiator_ready=None):
    parsed = unpack_shp_packet(data)
    if parsed is None:
        return
    ptype, cid, seq, ack, payload = parsed
    remote_addr = (str(addr[0]), int(addr[1]))
    my_inst = MESH_STATE["instance_id"]
    net_hex = MESH_STATE["net_id_hex"]

    if ptype in (SHP_HELLO, SHP_HELLO_ACK):
        try:
            parts = payload.decode("ascii", "ignore").strip().split("|")
        except Exception:
            return
        if len(parts) < 2 or parts[0] != net_hex or parts[1] == my_inst:
            return
        r_inst = parts[1]

        if ptype == SHP_HELLO:
            now = time.time()
            if (now - _HELLO_RATE_LIMIT.get(remote_addr, 0.0)) >= 0.8:
                _HELLO_RATE_LIMIT[remote_addr] = now
                ack_meta = ("%s|%s" % (net_hex, my_inst)).encode("ascii")
                try:
                    udp_sock.sendto(pack_shp_packet(SHP_HELLO_ACK, 0, 0, 0, ack_meta), remote_addr)
                except Exception:
                    pass

        if _has_tunnel_with_peer(remote_addr, r_inst):
            return
        with _UDP_TUNNELS_LOCK:
            if len(_UDP_TUNNELS) >= SHP_MAX_TUNNELS:
                return

        # Deterministic tie-breaker: lower instance_id initiates SHP_OPEN!
        if my_inst < r_inst:
            new_cid = random.randrange(1, 2**32)
            tun = _UdpTunnelSession(
                new_cid,
                remote_addr,
                r_inst,
                initiator=True,
                udp_sock=udp_sock,
                p2p_node=p2p_node,
                target_local_port=target_local_port,
            )
            with _UDP_TUNNELS_LOCK:
                _UDP_TUNNELS[new_cid] = tun
            tun.start_initiator_listener(on_ready_cb=on_initiator_ready)
        return

    if ptype == SHP_OPEN:
        try:
            parts = payload.decode("ascii", "ignore").strip().split("|")
        except Exception:
            return
        if len(parts) < 2 or parts[0] != net_hex or parts[1] == my_inst:
            return
        r_inst = parts[1]
        with _UDP_TUNNELS_LOCK:
            existing = _UDP_TUNNELS.get(cid)
            if existing is not None and existing.remote_addr == remote_addr and not existing.closed:
                existing.on_udp_packet(ptype, seq, ack, payload)
                return
            if len(_UDP_TUNNELS) >= SHP_MAX_TUNNELS:
                return
        tun = _UdpTunnelSession(
            cid,
            remote_addr,
            r_inst,
            initiator=False,
            udp_sock=udp_sock,
            p2p_node=p2p_node,
            target_local_port=target_local_port,
        )
        try:
            tun.start_responder_socket()
            with _UDP_TUNNELS_LOCK:
                _UDP_TUNNELS[cid] = tun
            print("[AutoMesh] Accepted incoming UDP hole-punched peer tunnel from %s:%d" % (remote_addr[0], remote_addr[1]))
        except Exception:
            tun.close(notify_remote=False)
        return

    with _UDP_TUNNELS_LOCK:
        tun = _UDP_TUNNELS.get(cid)
    if tun is not None and tun.remote_addr == remote_addr and not tun.closed:
        tun.on_udp_packet(ptype, seq, ack, payload)


def _udp_tunnel_pump_worker():
    """Single lightweight event loop pumping TCP <-> Reliable UDP across active hole-punch tunnels."""
    while not _STOP_EVENT.is_set():
        with _UDP_TUNNELS_LOCK:
            tunnels = list(_UDP_TUNNELS.values())

        if not tunnels:
            _STOP_EVENT.wait(0.15)
            continue

        rlist = []
        wlist = []
        sock_to_tun = {}
        now = time.time()

        for tun in tunnels:
            tun.tick(now)
            if tun.closed:
                with _UDP_TUNNELS_LOCK:
                    _UDP_TUNNELS.pop(tun.conn_id, None)
                continue
            if tun.listen_sock is not None and tun.tcp_sock is None:
                rlist.append(tun.listen_sock)
                sock_to_tun[tun.listen_sock] = tun
            elif tun.tcp_sock is not None:
                # Only read from TCP when UDP sliding window has open slots (lossless backpressure!)
                if len(tun.unacked) < SHP_WINDOW:
                    rlist.append(tun.tcp_sock)
                if tun.rx_to_tcp_buf:
                    wlist.append(tun.tcp_sock)
                sock_to_tun[tun.tcp_sock] = tun

        if not rlist and not wlist:
            _STOP_EVENT.wait(0.025)
            continue

        try:
            rd, wr, er = select.select(rlist, wlist, list(sock_to_tun.keys()), 0.025)
        except Exception:
            _STOP_EVENT.wait(0.02)
            continue

        for s in er:
            tun = sock_to_tun.get(s)
            if tun and s is tun.tcp_sock:
                tun.close(notify_remote=True)

        for s in wr:
            tun = sock_to_tun.get(s)
            if tun and not tun.closed and s is tun.tcp_sock and tun.rx_to_tcp_buf:
                try:
                    sent = s.send(memoryview(tun.rx_to_tcp_buf)[:16384].tobytes())
                    if sent > 0:
                        del tun.rx_to_tcp_buf[:sent]
                except Exception:
                    pass

        for s in rd:
            tun = sock_to_tun.get(s)
            if not tun or tun.closed:
                continue
            if s is tun.listen_sock:
                tun.tick(time.time())
                continue
            if s is tun.tcp_sock and len(tun.unacked) < SHP_WINDOW:
                try:
                    chunk = s.recv(SHP_MSS)
                except Exception:
                    continue
                if not chunk:
                    tun.close(notify_remote=True)
                else:
                    seq = tun.next_seq
                    tun.next_seq += 1
                    tun.unacked[seq] = [chunk, time.time(), 0]
                    tun._send_udp(SHP_DATA, seq, tun.recv_next, chunk)


def send_udp_holepunch_burst(candidates):
    """Queues simultaneous UDP SHP_HELLO hole-punch bursts from the shared UDP socket."""
    sock = _SHARED_UDP_SOCK
    if sock is None or not candidates:
        return
    hello_meta = ("%s|%s" % (MESH_STATE["net_id_hex"], MESH_STATE["instance_id"])).encode("ascii")
    pkt = pack_shp_packet(SHP_HELLO, 0, 0, 0, hello_meta)
    now = time.time()
    for ip, uport in candidates[:24]:
        if is_self_endpoint(ip, uport) or _has_tunnel_with_peer((str(ip), int(uport)), None):
            continue
        _PUNCH_TARGETS[(str(ip), int(uport))] = [now, 4]
        try:
            sock.sendto(pkt, (str(ip), int(uport)))
        except Exception:
            pass


def ingest_https_rendezvous_peers(p2p_node, peers_list):
    """
    Ingests WAN peer endpoints discovered via censorship-proof HTTPS :443 (/api/report),
    probing direct TCP :8344 and firing STUN UDP hole-punch bursts even when LAN peers exist!
    """
    if not isinstance(peers_list, list) or not peers_list:
        return 0
    if p2p_node is None:
        p2p_node = _ACTIVE_P2P_NODE
    my_inst = str(MESH_STATE.get("instance_id") or "")
    now = time.time()
    tcp_cands = []
    hp_cands = []

    for item in peers_list[:32]:
        if not isinstance(item, dict):
            continue
        r_inst = str(item.get("instance_id") or "").strip()
        if r_inst and my_inst and r_inst == my_inst:
            continue
        ip = str(item.get("ip") or "").strip()
        if not _is_routable_public_ipv4(ip):
            continue
        try:
            t_port = int(item.get("p2p_port") or MESH_STATE["p2p_port"] or 8344)
        except Exception:
            t_port = 8344
        try:
            u_port = int(item.get("udp_port") or t_port)
        except Exception:
            u_port = t_port

        if 0 < t_port <= 65535 and not is_self_endpoint(ip, t_port):
            if (ip, t_port) not in tcp_cands:
                tcp_cands.append((ip, t_port))
        if 0 < u_port <= 65535 and not is_self_endpoint(ip, u_port):
            _HTTPS_HP_CANDIDATES[(ip, u_port)] = now + 180.0
            if (ip, u_port) not in hp_cands:
                hp_cands.append((ip, u_port))

    MESH_STATE["https_rendezvous_peers"] = max(len(tcp_cands), len(hp_cands))

    if tcp_cands and p2p_node is not None:
        open_https = _probe_tcp_batch(tcp_cands[:24], timeout=1.3)
        if open_https:
            _save_cached_peers(open_https)
        for ip, port in open_https:
            tag = "%s:%d" % (ip, port)
            if tag not in MESH_STATE["discovered_wan_peers"]:
                MESH_STATE["discovered_wan_peers"].append(tag)
            _schedule_connect(p2p_node, ip, port, immediate=True, source="https_rendezvous")

    _refresh_live_peer_counts()
    if int(MESH_STATE["connected_wan_peers"]) < 2 and hp_cands:
        send_udp_holepunch_burst(hp_cands)

    return len(hp_cands)


# ==============================================================================
# STUN (RFC 5389) on Shared Socket + BEP 15 Serverless Swarm + Peer Cache
# ==============================================================================

def _parse_stun_response(resp, expected_txid=None):
    if not resp or len(resp) < 20:
        return None, None
    mtype, mlen, cookie = struct.unpack("!HHI", resp[:8])
    if mtype != 0x0101 or cookie != 0x2112A442:
        return None, None
    txid = resp[8:20]
    if expected_txid is not None and txid != expected_txid:
        return None, None
    pos = 20
    end = min(len(resp), 20 + mlen)
    while pos + 4 <= end:
        atype, alen = struct.unpack("!HH", resp[pos:pos + 4])
        aval = resp[pos + 4:pos + 4 + alen]
        if atype == 0x0020 and len(aval) >= 8:
            fam = struct.unpack("!B", aval[1:2])[0]
            if fam == 0x01:
                xport, xip = struct.unpack("!HI", aval[2:8])
                ip = socket.inet_ntoa(struct.pack("!I", xip ^ 0x2112A442))
                port = int(xport ^ 0x2112)
                if _is_routable_public_ipv4(ip) and 0 < port <= 65535:
                    return ip, port
        elif atype == 0x0001 and len(aval) >= 8:
            fam = struct.unpack("!B", aval[1:2])[0]
            if fam == 0x01:
                port = struct.unpack("!H", aval[2:4])[0]
                ip = socket.inet_ntoa(aval[4:8])
                if _is_routable_public_ipv4(ip) and 0 < port <= 65535:
                    return ip, int(port)
        pos += 4 + ((alen + 3) & ~3)
    return None, None


def refresh_stun_on_shared_socket(wait_s=1.2):
    """Sends STUN Binding Requests directly from _SHARED_UDP_SOCK to learn exact NAT UDP port!"""
    sock = _SHARED_UDP_SOCK
    if sock is None:
        ip = query_stun_external_ipv4(timeout=wait_s)
        return ip, 0

    _STUN_OBSERVATIONS[:] = []
    for host, port in DEFAULT_STUN_SERVERS[:2]:
        if _STOP_EVENT.is_set():
            break
        try:
            infos = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)
            if not infos:
                continue
            txid = struct.pack("!III", random.randrange(1, 2**32), random.randrange(1, 2**32), random.randrange(1, 2**32))
            _PENDING_STUN_TX[txid] = time.time()
            pkt = struct.pack("!HHI12s", 0x0001, 0, 0x2112A442, txid)
            sock.sendto(pkt, infos[0][4])
        except Exception:
            pass

    deadline = time.time() + float(wait_s)
    while time.time() < deadline and len(_STUN_OBSERVATIONS) < 2 and not _STOP_EVENT.is_set():
        time.sleep(0.06)

    if len(_STUN_OBSERVATIONS) >= 2:
        p0, p1 = _STUN_OBSERVATIONS[0][1], _STUN_OBSERVATIONS[1][1]
        MESH_STATE["nat_mapping"] = "endpoint_independent" if (p0 == p1) else "symmetric"
    elif len(_STUN_OBSERVATIONS) == 1 and MESH_STATE["nat_mapping"] == "unknown":
        MESH_STATE["nat_mapping"] = "cone_or_unknown"

    return MESH_STATE.get("external_ip"), int(MESH_STATE.get("external_udp_port") or 0)


def query_stun_external_ipv4(timeout=1.5):
    txid = struct.pack("!III", random.randrange(1, 2**32), random.randrange(1, 2**32), random.randrange(1, 2**32))
    pkt = struct.pack("!HHI12s", 0x0001, 0, 0x2112A442, txid)
    for host, port in DEFAULT_STUN_SERVERS:
        if _STOP_EVENT.is_set():
            break
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _disable_win_udp_connreset(s)
        s.settimeout(float(timeout))
        try:
            s.sendto(pkt, (host, int(port)))
            resp, _ = s.recvfrom(512)
            ip, _ = _parse_stun_response(resp, expected_txid=txid)
            if ip:
                return ip
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    return None


def _get_cache_file_path():
    try:
        from p2pool import scash_nodes as _sn
        dd = os.environ.get("SCASH_ACTIVE_DATADIR") or _sn.get_scash_datadir()
        if dd and os.path.isdir(dd):
            return os.path.join(dd, "p2pool_verified_peers.json")
    except Exception:
        pass
    return None


def _load_cached_peers():
    p = _get_cache_file_path()
    if not p or not os.path.isfile(p):
        return []
    try:
        raw = json.loads(open(p, "r").read())
        out = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    ip = str(item.get("ip", "")).strip()
                    port = int(item.get("port", 8344))
                    if _is_routable_public_ipv4(ip) and 0 < port <= 65535 and not is_self_endpoint(ip, port):
                        out.append((ip, port))
        return out[:64]
    except Exception:
        return []


def _save_cached_peers(peers_list):
    p = _get_cache_file_path()
    if not p:
        return
    try:
        existing = _load_cached_peers()
        merged = []
        seen = set()
        for ip, port in list(peers_list) + existing:
            key = (str(ip), int(port))
            if key not in seen and _is_routable_public_ipv4(key[0]) and not is_self_endpoint(key[0], key[1]):
                seen.add(key)
                merged.append({"ip": key[0], "port": key[1], "ts": int(time.time())})
                if len(merged) >= 64:
                    break
        tmp_p = p + ".tmp"
        with open(tmp_p, "w") as f:
            f.write(json.dumps(merged))
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
        os.rename(tmp_p, p)
    except Exception:
        pass


def announce_and_discover_bep15_swarm(net_id_hex, announce_port, trackers=None, timeout=1.8, swarm_prefix="scash-p2pool-swarm-"):
    """
    Serverless Global Swarm Rendezvous via BEP 15 Open UDP Trackers.
    Used for BOTH direct TCP (:8344) peer discovery (`scash-p2pool-swarm-`) and STUN-mapped
    UDP hole-punch (`scash-p2pool-udphp-`) rendezvous!
    """
    if trackers is None:
        env_tr = os.environ.get("SCASH_SWARM_TRACKERS", "").strip()
        if env_tr:
            parsed = []
            for item in env_tr.split(","):
                item = item.strip()
                if ":" in item:
                    h, ps = item.rsplit(":", 1)
                    try:
                        parsed.append((h.strip(), int(ps.strip())))
                    except Exception:
                        pass
            trackers = parsed
        else:
            trackers = list(DEFAULT_SWARM_TRACKERS)

    info_hash = hashlib.sha1((str(swarm_prefix) + str(net_id_hex)).encode("ascii")).digest()
    inst_str = str(MESH_STATE.get("instance_id", "000000000000"))[:12].ljust(12, "0")
    peer_id = ("-SC0200-" + inst_str).encode("ascii")[:20]
    peer_key = random.randrange(1, 2**31)

    discovered = []
    seen = set()

    for host, tport in trackers:
        if _STOP_EVENT.is_set():
            break
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _disable_win_udp_connreset(s)
        s.settimeout(float(timeout))
        try:
            infos = socket.getaddrinfo(host, int(tport), socket.AF_INET, socket.SOCK_DGRAM)
            if not infos:
                continue
            dest = infos[0][4]
            tx1 = random.randrange(1, 2**31)
            conn_req = struct.pack("!QII", 0x41727101980, 0, tx1)
            s.sendto(conn_req, dest)
            c_resp, _ = s.recvfrom(256)
            if len(c_resp) < 16:
                continue
            c_act, c_tx, conn_id = struct.unpack("!IIQ", c_resp[:16])
            if c_act != 0 or c_tx != tx1:
                continue

            tx2 = random.randrange(1, 2**31)
            ann_req = struct.pack(
                "!QII20s20sQQQIIIiH",
                conn_id,
                1,
                tx2,
                info_hash,
                peer_id,
                0,
                50000,
                0,
                0,
                0,
                peer_key,
                80,
                int(announce_port),
            )
            s.sendto(ann_req, dest)
            a_resp, _ = s.recvfrom(2048)
            if len(a_resp) < 20:
                continue
            a_act, a_tx, _intv, _leech, _seed = struct.unpack("!IIIII", a_resp[:20])
            if a_act != 1 or a_tx != tx2:
                continue

            body = a_resp[20:]
            for off in range(0, len(body) - 5, 6):
                ip_str = socket.inet_ntoa(body[off:off + 4])
                p_num = struct.unpack("!H", body[off + 4:off + 6])[0]
                if p_num <= 0 or p_num > 65535 or is_self_endpoint(ip_str, p_num):
                    continue
                if (ip_str, p_num) not in seen:
                    seen.add((ip_str, p_num))
                    discovered.append((ip_str, p_num))
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass

    return discovered


def _probe_tcp_batch(candidates, timeout=1.2):
    open_list = []
    seen = set()
    dedup = []
    for ip, port in candidates:
        key = (str(ip).strip(), int(port))
        if key not in seen and not is_self_endpoint(key[0], key[1]):
            seen.add(key)
            dedup.append(key)

    chunk_sz = 20
    for idx in range(0, len(dedup), chunk_sz):
        if _STOP_EVENT.is_set():
            break
        batch = dedup[idx:idx + chunk_sz]
        sock_map = {}
        for ip, port in batch:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            try:
                rc = s.connect_ex((ip, port))
                if rc == 0:
                    open_list.append((ip, port))
                    s.close()
                else:
                    sock_map[s] = (ip, port)
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass

        deadline = time.time() + float(timeout)
        while sock_map and time.time() < deadline and not _STOP_EVENT.is_set():
            wait_s = max(0.02, min(0.08, deadline - time.time()))
            try:
                _, writable, errored = select.select([], list(sock_map.keys()), list(sock_map.keys()), wait_s)
            except Exception:
                break
            done = set(writable) | set(errored)
            for s in done:
                target = sock_map.pop(s, None)
                if target is not None and s in writable:
                    try:
                        err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if err == 0:
                            open_list.append(target)
                    except Exception:
                        pass
                try:
                    s.close()
                except Exception:
                    pass

        for s in list(sock_map.keys()):
            try:
                s.close()
            except Exception:
                pass

    return open_list


def _is_peer_connected(p2p_node, ip, port=None):
    try:
        peers = getattr(p2p_node, "peers", {}) or {}
        local_equiv = set(["127.0.0.1"] + get_local_lan_ipv4s())
        ip_is_local = str(ip) in local_equiv
        for proto in list(peers.values()):
            paddr = getattr(proto, "addr", None)
            if paddr:
                p_ip, p_port = str(paddr[0]), int(paddr[1])
                # Remote LAN/WAN hosts run a single P2Pool node per IP (incoming sockets carry ephemeral source ports like :45308)
                if p_ip == str(ip) and ((not ip_is_local) or port is None or p_port == int(port)):
                    return True
                if port is not None and p_port == int(port) and ip_is_local and p_ip in local_equiv:
                    return True
    except Exception:
        pass
    return False


def _twisted_register_and_dial(p2p_node, ip, port, immediate=True, source="mesh", allow_loopback_bridge=False):
    ip = str(ip).strip()
    port = int(port)
    if not _is_valid_ipv4(ip) or port <= 0 or port > 65535:
        return
    if not allow_loopback_bridge and is_self_endpoint(ip, port):
        return

    is_public_wan = _is_routable_public_ipv4(ip)
    if is_public_wan:
        _VERIFIED_OPEN_PEERS.add((ip, port))

    _refresh_live_peer_counts()
    if _is_peer_connected(p2p_node, ip, port):
        return

    try:
        addr_store = getattr(p2p_node, "addr_store", None)
        if isinstance(addr_store, dict) and int(MESH_STATE.get("connected_wan_peers") or 0) == 0:
            for k in list(addr_store.keys()):
                if k not in _VERIFIED_OPEN_PEERS:
                    addr_store.pop(k, None)
    except Exception:
        pass

    # Only add routable public WAN IPs to addr_store (never 127.0.0.1 or RFC1918 LAN IPs!)
    if is_public_wan:
        now = time.time()
        try:
            addr_store = getattr(p2p_node, "addr_store", None)
            if isinstance(addr_store, dict):
                sample_vals = list(addr_store.values())
                if sample_vals and isinstance(sample_vals[0], tuple) and len(sample_vals[0]) == 3:
                    svc = sample_vals[0][0]
                    old = addr_store.get((ip, port))
                    first_seen = old[1] if (isinstance(old, tuple) and len(old) == 3) else (now - 30.0)
                    addr_store[(ip, port)] = (svc, first_seen, now)
                else:
                    addr_store[(ip, port)] = (0, now - 30.0, now)
            if hasattr(p2p_node, "got_addr"):
                try:
                    p2p_node.got_addr((ip, port), 0, int(now))
                except Exception:
                    pass
        except Exception:
            pass

    if not immediate:
        return

    try:
        from p2pool import p2p as _p2p_mod
        from twisted.internet import reactor as _tw_reactor
        dialed = getattr(p2p_node, "_scash_dialed_mesh", None)
        if dialed is None:
            dialed = {}
            p2p_node._scash_dialed_mesh = dialed
        now_t = time.time()
        prev_dial = dialed.get((ip, port), 0.0)
        if (allow_loopback_bridge or (now_t - prev_dial) >= 25.0) and len(getattr(p2p_node, "peers", {}) or {}) < 12:
            scf = getattr(_p2p_mod, "SingleClientFactory", None)
            if scf is not None:
                try:
                    scf_src = inspect.getsource(scf)
                except Exception:
                    scf_src = ""
                try:
                    scf_args = inspect.getargspec(scf.__init__).args
                except Exception:
                    scf_args = ["self", "node"]
                if "attempts" not in scf_src:
                    if len(scf_args) == 2:
                        _tw_reactor.connectTCP(ip, port, scf(p2p_node), timeout=5)
                        dialed[(ip, port)] = now_t
                        print("[AutoMesh] Connecting to discovered P2Pool peer %s:%d (%s)" % (ip, port, source))
                    elif len(scf_args) == 3:
                        _tw_reactor.connectTCP(ip, port, scf(p2p_node, (ip, port)), timeout=5)
                        dialed[(ip, port)] = now_t
                        print("[AutoMesh] Connecting to discovered P2Pool peer %s:%d (%s)" % (ip, port, source))
    except Exception:
        pass


def _schedule_connect(p2p_node, ip, port, immediate=True, delay=0.0, source="mesh", allow_loopback_bridge=False):
    if not allow_loopback_bridge and is_self_endpoint(ip, port):
        return
    try:
        from twisted.internet import reactor as _tw_reactor

        def _do():
            if delay > 0.0:
                _tw_reactor.callLater(
                    float(delay),
                    lambda: _twisted_register_and_dial(
                        p2p_node, ip, port, immediate=True, source=source, allow_loopback_bridge=allow_loopback_bridge
                    ),
                )
            else:
                _twisted_register_and_dial(
                    p2p_node, ip, port, immediate=immediate, source=source, allow_loopback_bridge=allow_loopback_bridge
                )

        _tw_reactor.callFromThread(_do)
    except Exception:
        pass


def _udp_beacon_worker(p2p_node, base_udp_port):
    global _SHARED_UDP_SOCK
    sock = None
    bound_port = 0
    for offset in range(4):
        cand_port = int(base_udp_port) + offset
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        _disable_win_udp_connreset(s)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass
        try:
            s.bind(("0.0.0.0", cand_port))
            sock = s
            bound_port = cand_port
            break
        except Exception:
            try:
                s.close()
            except Exception:
                pass

    if sock is None:
        return

    _SHARED_UDP_SOCK = sock
    MESH_STATE["udp_port"] = bound_port
    try:
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GRP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except Exception:
        pass

    my_inst = MESH_STATE["instance_id"]
    net_hex = MESH_STATE["net_id_hex"]
    my_tcp_port = int(MESH_STATE["p2p_port"])
    payload = ("%s|%s|%d|%s" % (BEACON_MAGIC, net_hex, my_tcp_port, my_inst)).encode("ascii")
    hello_pkt = pack_shp_packet(SHP_HELLO, 0, 0, 0, ("%s|%s" % (net_hex, my_inst)).encode("ascii"))

    target_ports = [int(base_udp_port), int(base_udp_port) + 1]
    next_bcast = 0.0
    bcast_count = 0

    try:
        while not _STOP_EVENT.is_set():
            now = time.time()
            if now >= next_bcast:
                lan_ips = get_local_lan_ipv4s()
                MESH_STATE["lan_ips"] = lan_ips
                dest_ips = ["255.255.255.255", MULTICAST_GRP]
                if os.environ.get("SCASH_DISABLE_LOCALHOST_MESH") != "1":
                    dest_ips.append("127.0.0.1")
                for lip in lan_ips:
                    if _is_private_rfc1918(lip):
                        bcast_ip = ".".join(lip.split(".")[:3] + ["255"])
                        if bcast_ip not in dest_ips:
                            dest_ips.append(bcast_ip)
                for dip in dest_ips:
                    for dport in target_ports:
                        try:
                            sock.sendto(payload, (dip, dport))
                        except Exception:
                            pass
                bcast_count += 1
                next_bcast = now + (2.0 if bcast_count <= 6 else 8.0)

            # Re-send scheduled UDP hole-punch HELLO bursts (~1.6s spacing)
            for t_addr in list(_PUNCH_TARGETS.keys()):
                last_t, rem = _PUNCH_TARGETS.get(t_addr, [0.0, 0])
                if rem <= 0 or _has_tunnel_with_peer(t_addr, None) or int(MESH_STATE["connected_wan_peers"]) >= 3:
                    _PUNCH_TARGETS.pop(t_addr, None)
                    continue
                if (now - last_t) >= 1.6:
                    _PUNCH_TARGETS[t_addr] = [now, rem - 1]
                    try:
                        sock.sendto(hello_pkt, t_addr)
                    except Exception:
                        pass

            try:
                readable, _, _ = select.select([sock], [], [], 0.25)
            except Exception:
                readable = []

            for r in readable:
                for _drain in range(24):
                    try:
                        sock.setblocking(False)
                        data, addr = r.recvfrom(2048)
                    except Exception:
                        break
                    finally:
                        try:
                            sock.setblocking(True)
                        except Exception:
                            pass

                    # 1. Demultiplex STUN Binding Response (0x0101 + magic cookie 0x2112A442)
                    if len(data) >= 20 and data[:2] == b"\x01\x01" and data[4:8] == b"\x21\x12\xa4\x42":
                        txid = data[8:20]
                        if txid in _PENDING_STUN_TX:
                            _PENDING_STUN_TX.pop(txid, None)
                            sip, suport = _parse_stun_response(data, expected_txid=txid)
                            if sip and suport:
                                MESH_STATE["external_ip"] = sip
                                MESH_STATE["external_udp_port"] = int(suport)
                                _STUN_OBSERVATIONS.append((sip, int(suport)))
                        continue

                    # 2. Demultiplex Reliable UDP Hole-Punch Frame (`SHP1`)
                    if len(data) >= 19 and data[:4] == SHP_MAGIC:
                        _handle_shp_datagram(p2p_node, sock, data, addr)
                        continue

                    # 3. Demultiplex Home LAN UDP Beacon (`SCASH_P2P_V1|...`)
                    sender_ip, sender_uport = str(addr[0]), int(addr[1])
                    try:
                        txt = data.decode("ascii", "ignore").strip()
                    except Exception:
                        continue
                    parts = txt.split("|")
                    if len(parts) != 4 or parts[0] != BEACON_MAGIC:
                        continue
                    r_net, r_port_s, r_inst = parts[1], parts[2], parts[3]
                    if r_net != net_hex or r_inst == my_inst:
                        continue
                    try:
                        r_tcp_port = int(r_port_s)
                    except Exception:
                        continue
                    if r_tcp_port <= 0 or r_tcp_port > 65535 or is_self_endpoint(sender_ip, r_tcp_port):
                        continue

                    tag = "%s:%d" % (sender_ip, r_tcp_port)
                    if tag not in MESH_STATE["discovered_lan_peers"]:
                        MESH_STATE["discovered_lan_peers"].append(tag)

                    last_rep = _RECENT_UNICAST_REPLY.get(r_inst, 0.0)
                    if (time.time() - last_rep) >= 4.0:
                        _RECENT_UNICAST_REPLY[r_inst] = time.time()
                        try:
                            sock.sendto(payload, (sender_ip, sender_uport))
                        except Exception:
                            pass

                    prev_inst_dial = _DIALED_INSTANCES.get(r_inst, 0.0)
                    if (time.time() - prev_inst_dial) < 12.0:
                        continue
                    _DIALED_INSTANCES[r_inst] = time.time()

                    if my_inst < r_inst:
                        _schedule_connect(p2p_node, sender_ip, r_tcp_port, immediate=True, delay=0.0, source="lan_udp")
                    else:
                        _schedule_connect(p2p_node, sender_ip, r_tcp_port, immediate=True, delay=1.8, source="lan_udp_fallback")
    finally:
        if _SHARED_UDP_SOCK is sock:
            _SHARED_UDP_SOCK = None
        try:
            sock.close()
        except Exception:
            pass


def _rpc_call_scashd(method, params=None):
    try:
        port = int(os.environ.get("SCASH_RPC_PORT") or 8342)
        u = os.environ.get("SCASH_RPC_USER") or ""
        pw = os.environ.get("SCASH_RPC_PASS") or ""
        if not u or not pw:
            from p2pool import scash_nodes as _sn
            dd = os.environ.get("SCASH_ACTIVE_DATADIR") or _sn.get_scash_datadir()
            cu, cp = _sn.read_cookie_credentials(dd)
            if cu and cp:
                u, pw = cu, cp
            else:
                fu, fp = _sn.read_conf_credentials(dd)
                u, pw = fu or "scashminer", fp or "kawaiip2poolpass"
        url = "http://127.0.0.1:%d/" % port
        body = json.dumps({"jsonrpc": "1.0", "id": "mesh", "method": method, "params": params or []}).encode("utf-8")
        auth = base64.b64encode(("%s:%s" % (u, pw)).encode("utf-8")).decode("ascii")
        req = _ureq.Request(url, body, {"Content-Type": "application/json", "Authorization": "Basic " + auth})
        raw = _NO_PROXY_OPENER.open(req, timeout=2.5).read().decode("utf-8", "replace")
        return (json.loads(raw) or {}).get("result")
    except Exception:
        return None


def _extract_ipv4_from_addr(addr_str):
    if not addr_str:
        return None
    s = str(addr_str).strip()
    if s.startswith("["):
        return None
    host = s.rsplit(":", 1)[0] if ":" in s else s
    return host if _is_routable_public_ipv4(host) else None


def _mesh_scanner_worker(p2p_node):
    if os.environ.get("SCASH_CI_ISOLATED_MESH") == "1":
        return

    my_port = int(MESH_STATE["p2p_port"])
    net_hex = MESH_STATE["net_id_hex"]
    last_lan_sweep = 0.0
    last_wan_scan = 0.0
    last_swarm_announce = 0.0
    last_https_repunch = 0.0

    cached = _load_cached_peers()
    if cached:
        open_cached = _probe_tcp_batch(cached[:20], timeout=1.2)
        for ip, port in open_cached:
            tag = "%s:%d" % (ip, port)
            if tag not in MESH_STATE["discovered_wan_peers"]:
                MESH_STATE["discovered_wan_peers"].append(tag)
            _schedule_connect(p2p_node, ip, port, immediate=True, source="cached_peer")

    time.sleep(0.8)
    while not _STOP_EVENT.is_set():
        now = time.time()
        _refresh_live_peer_counts()
        n_peers = int(MESH_STATE["connected_peers"])
        n_wan = int(MESH_STATE["connected_wan_peers"])
        local_ips = set(get_local_lan_ipv4s())
        if MESH_STATE["external_ip"]:
            local_ips.add(str(MESH_STATE["external_ip"]))

        # 0. Keep NAT UDP pinholes warm every 18s toward HTTPS :443 rendezvous peers until >= 2 WAN peers connect!
        if n_wan < 2 and _HTTPS_HP_CANDIDATES and (now - last_https_repunch) >= 18.0:
            last_https_repunch = now
            fresh_hp = []
            for hp_k, exp_t in list(_HTTPS_HP_CANDIDATES.items()):
                if now > exp_t:
                    _HTTPS_HP_CANDIDATES.pop(hp_k, None)
                elif not _is_peer_connected(p2p_node, hp_k[0], None):
                    fresh_hp.append(hp_k)
            if fresh_hp:
                send_udp_holepunch_burst(fresh_hp)

        # 1. Serverless Global BEP 15 Swarm Rendezvous + STUN + Decentralized UDP Hole Punching!
        swarm_interval = 22.0 if n_wan == 0 else (60.0 if n_wan < 2 else 120.0)
        if (now - last_swarm_announce) >= swarm_interval:
            last_swarm_announce = now
            ext_ip, ext_uport = refresh_stun_on_shared_socket(wait_s=1.1)
            if ext_ip:
                local_ips.add(ext_ip)

            # 1a. Direct TCP (:8344) global swarm discovery
            swarm_cands = announce_and_discover_bep15_swarm(
                net_hex, my_port, timeout=1.6, swarm_prefix="scash-p2pool-swarm-"
            )
            # 1b. STUN-mapped UDP hole-punch (`udphp`) swarm discovery
            hp_port = int(ext_uport or MESH_STATE.get("udp_port") or my_port)
            hp_cands = []
            if hp_port > 0:
                hp_cands = announce_and_discover_bep15_swarm(
                    net_hex, hp_port, timeout=1.6, swarm_prefix="scash-p2pool-udphp-"
                )

            MESH_STATE["swarm_peers_found"] = max(len(swarm_cands), len(hp_cands))
            if swarm_cands:
                open_swarm = _probe_tcp_batch(swarm_cands[:40], timeout=1.4)
                if open_swarm:
                    _save_cached_peers(open_swarm)
                for ip, port in open_swarm:
                    tag = "%s:%d" % (ip, port)
                    if tag not in MESH_STATE["discovered_wan_peers"]:
                        MESH_STATE["discovered_wan_peers"].append(tag)
                    _schedule_connect(p2p_node, ip, port, immediate=True, source="global_swarm")

            # If STILL 0 direct TCP peers, fire simultaneous UDP hole-punch bursts to punch closed NATs!
            _refresh_live_peer_counts()
            if int(MESH_STATE["connected_wan_peers"]) < 2 and hp_cands:
                send_udp_holepunch_burst(hp_cands)

        # 2. Re-resolve BOOTSTRAP_ADDRS & probe Scash Core (`scashd` -uacomment=p2pool) blockchain peers on :8344
        wan_interval = 20.0 if n_wan == 0 else (75.0 if n_wan < 3 else 240.0)
        if (now - last_wan_scan) >= wan_interval:
            last_wan_scan = now
            seed_hosts = ["p2pool.magicalgirlsunite.moe", "magicalgirlsunite.moe", "seed.scash.one", "scash.tv"]
            for h in getattr(getattr(p2p_node, "net", None), "BOOTSTRAP_ADDRS", []) or []:
                hs = str(h).strip()
                if hs and hs not in seed_hosts:
                    seed_hosts.append(hs)

            seed_cands = []
            for host in seed_hosts:
                if _STOP_EVENT.is_set():
                    break
                h_only, h_port = (host.rsplit(":", 1)[0], int(host.rsplit(":", 1)[1])) if (":" in host and not host.startswith("[")) else (host, my_port)
                try:
                    infos = socket.getaddrinfo(h_only, h_port, socket.AF_INET, socket.SOCK_STREAM)
                    for info in infos:
                        ip = info[4][0]
                        if not is_self_endpoint(ip, h_port) and (ip, h_port) not in seed_cands:
                            seed_cands.append((ip, h_port))
                except Exception:
                    pass

            open_seeds = _probe_tcp_batch(seed_cands, timeout=1.5)
            if open_seeds:
                _save_cached_peers(open_seeds)
            for ip, port in open_seeds:
                tag = "%s:%d" % (ip, port)
                if tag not in MESH_STATE["discovered_wan_peers"]:
                    MESH_STATE["discovered_wan_peers"].append(tag)
                _schedule_connect(p2p_node, ip, port, immediate=True, source="bootstrap_seed")

            prio_cands = []
            other_cands = []
            peer_info = _rpc_call_scashd("getpeerinfo")
            if isinstance(peer_info, list):
                for p in peer_info:
                    if not isinstance(p, dict):
                        continue
                    ip = _extract_ipv4_from_addr(p.get("addr", ""))
                    if not ip:
                        continue
                    subv = str(p.get("subver", "")).lower()
                    cand_port = my_port
                    m_port = re.search(r"p2pool:([0-9]{2,5})", subv)
                    if m_port:
                        try:
                            cp = int(m_port.group(1))
                            if 0 < cp <= 65535:
                                cand_port = cp
                        except Exception:
                            pass
                    if is_self_endpoint(ip, cand_port):
                        continue
                    if "p2pool" in subv:
                        if (ip, cand_port) not in prio_cands:
                            prio_cands.append((ip, cand_port))
                    elif (ip, cand_port) not in other_cands:
                        other_cands.append((ip, cand_port))

            node_addrs = _rpc_call_scashd("getnodeaddresses", [256])
            if isinstance(node_addrs, list):
                for na in node_addrs:
                    if isinstance(na, dict):
                        ip = str(na.get("address", "")).strip()
                        if _is_routable_public_ipv4(ip) and not is_self_endpoint(ip, my_port):
                            if (ip, my_port) not in prio_cands and (ip, my_port) not in other_cands:
                                other_cands.append((ip, my_port))

            probe_queue = []
            prio_set = set(prio_cands)
            for ip, cport in (prio_cands + other_cands):
                prev_t = _PROBED_WAN_TS.get((ip, cport), 0.0)
                cooldown = 25.0 if (ip, cport) in prio_set else 180.0
                if (now - prev_t) >= cooldown:
                    _PROBED_WAN_TS[(ip, cport)] = now
                    probe_queue.append((ip, cport))
                    if len(probe_queue) >= 48:
                        break

            if probe_queue:
                open_wan = _probe_tcp_batch(probe_queue, timeout=1.3)
                if open_wan:
                    _save_cached_peers(open_wan)
                for ip, port in open_wan:
                    tag = "%s:%d" % (ip, port)
                    if tag not in MESH_STATE["discovered_wan_peers"]:
                        MESH_STATE["discovered_wan_peers"].append(tag)
                    _schedule_connect(p2p_node, ip, port, immediate=True, source="scashd_mesh")

            # Also attempt UDP :8344 hole-punching toward prioritized `/Scash:...(p2pool)/` blockchain peers if still 0 peers!
            _refresh_live_peer_counts()
            if int(MESH_STATE["connected_wan_peers"]) < 2 and prio_cands:
                send_udp_holepunch_burst(prio_cands[:12])

        # 3. Local /24 LAN TCP :8344 sweep fallback ONLY while connected_peers == 0
        _refresh_live_peer_counts()
        if int(MESH_STATE["connected_peers"]) == 0 and (now - last_lan_sweep) >= 40.0:
            last_lan_sweep = now
            rfc_ips = [ip for ip in local_ips if _is_private_rfc1918(ip)]
            rfc_ips.sort(key=lambda x: (0 if x.startswith(("192.168.", "10.")) else 1))
            for base_ip in rfc_ips[:2]:
                prefix = ".".join(base_ip.split(".")[:3])
                lan_cands = [
                    ("%s.%d" % (prefix, host_i), my_port)
                    for host_i in range(1, 255)
                    if ("%s.%d" % (prefix, host_i)) not in local_ips
                ]
                open_lan = _probe_tcp_batch(lan_cands, timeout=0.28)
                for ip, port in open_lan:
                    tag = "%s:%d" % (ip, port)
                    if tag not in MESH_STATE["discovered_lan_peers"]:
                        MESH_STATE["discovered_lan_peers"].append(tag)
                    _schedule_connect(p2p_node, ip, port, immediate=True, source="lan_tcp_sweep")

        _STOP_EVENT.wait(3.0)


# ==============================================================================
# UPnP IGD + PCP (RFC 6887) + NAT-PMP (RFC 6886) Automatic Router Port Mapping
# ==============================================================================

def _try_upnp_igd_map(local_ip, p2p_port, scash_port=8343):
    services = (
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "urn:schemas-upnp-org:service:WANPPPConnection:1",
    )
    crlf = "\r\n"
    ssdp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    _disable_win_udp_connreset(ssdp)
    ssdp.settimeout(1.8)
    locations = []
    try:
        for st in services:
            lines = [
                "M-SEARCH * HTTP/1.1",
                "HOST: 239.255.255.250:1900",
                'MAN: "ssdp:discover"',
                "MX: 1",
                "ST: %s" % st,
                "",
                "",
            ]
            req = crlf.join(lines).encode("ascii")
            try:
                ssdp.sendto(req, ("239.255.255.250", 1900))
            except Exception:
                pass
        deadline = time.time() + 1.8
        while time.time() < deadline:
            try:
                raw, addr = ssdp.recvfrom(2048)
                if not _is_private_rfc1918(addr[0]):
                    continue
                txt = raw.decode("utf-8", "replace")
                m = re.search(r"(?im)^LOCATION:\s*(http://[^\r\n]+)", txt)
                if m:
                    loc = m.group(1).strip()
                    if loc not in locations:
                        locations.append(loc)
            except Exception:
                break
    finally:
        try:
            ssdp.close()
        except Exception:
            pass

    for loc in locations[:3]:
        try:
            m_host = re.match(r"^http://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)(?::([0-9]+))?(/.*)?$", loc)
            if not m_host or not _is_private_rfc1918(m_host.group(1)):
                continue
            gw_host = m_host.group(1)
            gw_port = int(m_host.group(2) or 80)
            xml_txt = _NO_PROXY_OPENER.open(loc, timeout=2.0).read().decode("utf-8", "replace")
            for st in services:
                idx = xml_txt.find(st)
                if idx == -1:
                    continue
                sub = xml_txt[idx:idx + 2500]
                mc = re.search(r"<controlURL>\s*([^<\s]+)\s*</controlURL>", sub, re.I)
                if not mc:
                    continue
                ctrl_path = mc.group(1).strip()
                if ctrl_path.startswith("http://"):
                    ctrl_url = ctrl_path
                else:
                    if not ctrl_path.startswith("/"):
                        ctrl_path = "/" + ctrl_path
                    ctrl_url = "http://%s:%d%s" % (gw_host, gw_port, ctrl_path)

                mapped_ok = False
                port_specs = [
                    (int(p2p_port), "TCP", "Scash P2Pool TCP"),
                    (int(p2p_port), "UDP", "Scash P2Pool UDP"),
                    (int(scash_port), "TCP", "Scash Node TCP"),
                ]
                for target_port, proto, desc in port_specs:
                    soap_body = (
                        '<?xml version="1.0"?>'
                        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                        '<s:Body><u:AddPortMapping xmlns:u="%s">'
                        '<NewRemoteHost></NewRemoteHost>'
                        '<NewExternalPort>%d</NewExternalPort>'
                        '<NewProtocol>%s</NewProtocol>'
                        '<NewInternalPort>%d</NewInternalPort>'
                        '<NewInternalClient>%s</NewInternalClient>'
                        '<NewEnabled>1</NewEnabled>'
                        '<NewPortMappingDescription>%s</NewPortMappingDescription>'
                        '<NewLeaseDuration>3600</NewLeaseDuration>'
                        '</u:AddPortMapping></s:Body></s:Envelope>'
                        % (st, target_port, proto, target_port, local_ip, desc)
                    ).encode("utf-8")
                    req = _ureq.Request(
                        ctrl_url,
                        soap_body,
                        {
                            "Content-Type": 'text/xml; charset="utf-8"',
                            "SOAPAction": '"%s#AddPortMapping"' % st,
                        },
                    )
                    try:
                        _NO_PROXY_OPENER.open(req, timeout=2.5).read()
                        if target_port == int(p2p_port) and proto == "TCP":
                            mapped_ok = True
                    except Exception:
                        pass

                ext_ip = None
                try:
                    ip_body = (
                        '<?xml version="1.0"?>'
                        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                        '<s:Body><u:GetExternalIPAddress xmlns:u="%s"></u:GetExternalIPAddress>'
                        '</s:Body></s:Envelope>' % st
                    ).encode("utf-8")
                    ip_req = _ureq.Request(
                        ctrl_url,
                        ip_body,
                        {
                            "Content-Type": 'text/xml; charset="utf-8"',
                            "SOAPAction": '"%s#GetExternalIPAddress"' % st,
                        },
                    )
                    ip_xml = _NO_PROXY_OPENER.open(ip_req, timeout=2.0).read().decode("utf-8", "replace")
                    mip = re.search(r"<NewExternalIPAddress>\s*([0-9.]+)\s*</NewExternalIPAddress>", ip_xml, re.I)
                    if mip and _is_routable_public_ipv4(mip.group(1)):
                        ext_ip = mip.group(1)
                except Exception:
                    pass

                if mapped_ok:
                    return True, ext_ip
        except Exception:
            pass
    return False, None


def _try_pcp_map(local_ip, p2p_port):
    if not _is_private_rfc1918(local_ip):
        return False, None
    gw_ip = ".".join(local_ip.split(".")[:3] + ["1"])
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _disable_win_udp_connreset(s)
    s.settimeout(1.2)
    try:
        v4_mapped_prefix = b"\x00" * 10 + b"\xff\xff"
        cli_ip16 = v4_mapped_prefix + socket.inet_aton(local_ip)
        nonce = struct.pack("!III", random.randrange(1, 2**32), random.randrange(1, 2**32), random.randrange(1, 2**32))
        sug_ext16 = v4_mapped_prefix + b"\x00\x00\x00\x00"
        mapped_tcp = False
        ext_ip = None
        for proto_num in (6, 17):
            hdr = struct.pack("!BBHI16s", 2, 1, 0, 3600, cli_ip16)
            body = struct.pack("!12sB3sHH16s", nonce, proto_num, b"\x00\x00\x00", int(p2p_port), int(p2p_port), sug_ext16)
            s.sendto(hdr + body, (gw_ip, 5351))
            resp, raddr = s.recvfrom(128)
            if raddr[0] == gw_ip and len(resp) >= 60:
                ver, op, _r1, res_code = struct.unpack("!BBBB", resp[:4])
                ext_port = struct.unpack("!H", resp[42:44])[0]
                if resp[44:56] == v4_mapped_prefix:
                    cand_ip = socket.inet_ntoa(resp[56:60])
                    if _is_routable_public_ipv4(cand_ip):
                        ext_ip = cand_ip
                if ver == 2 and op == 129 and res_code == 0 and ext_port == int(p2p_port) and proto_num == 6:
                    mapped_tcp = True
        if mapped_tcp:
            return True, ext_ip
    except Exception:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass
    return False, None


def _try_natpmp_clean(local_ip, p2p_port):
    if not _is_private_rfc1918(local_ip):
        return False
    gw_ip = ".".join(local_ip.split(".")[:3] + ["1"])
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _disable_win_udp_connreset(s)
    s.settimeout(1.2)
    try:
        mapped_tcp = False
        for op_req, op_exp in ((2, 130), (1, 129)):
            pkt = struct.pack("!BBHHHI", 0, op_req, 0, int(p2p_port), int(p2p_port), 3600)
            s.sendto(pkt, (gw_ip, 5351))
            resp, raddr = s.recvfrom(64)
            if raddr[0] == gw_ip and len(resp) >= 16:
                ver, op, res_code, _ep, _ip, mapped_ext, life = struct.unpack("!BBHIHHI", resp[:16])
                if ver == 0 and op == op_exp and res_code == 0 and mapped_ext == int(p2p_port) and life > 0 and op_req == 2:
                    mapped_tcp = True
        return mapped_tcp
    except Exception:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass
    return False


def _upnp_worker(p2p_node):
    if os.environ.get("SCASH_CI_ISOLATED_MESH") == "1" or os.environ.get("SCASH_DISABLE_AUTO_UPNP") == "1":
        return

    my_port = int(MESH_STATE["p2p_port"])
    logged_once = False
    while not _STOP_EVENT.is_set():
        lan_ips = [ip for ip in get_local_lan_ipv4s() if _is_private_rfc1918(ip)]
        if lan_ips:
            primary_lan = lan_ips[0]
            ok_upnp, ext_ip = _try_upnp_igd_map(primary_lan, my_port, scash_port=8343)
            if ok_upnp:
                MESH_STATE["upnp_mapped"] = True
                if ext_ip:
                    MESH_STATE["external_ip"] = ext_ip
                if not logged_once:
                    print("[AutoMesh] UPnP router port TCP/UDP %d mapped automatically (%s)!" % (my_port, MESH_STATE["external_ip"] or primary_lan))
                    logged_once = True
            else:
                ok_pcp, pcp_ip = _try_pcp_map(primary_lan, my_port)
                if ok_pcp:
                    MESH_STATE["pcp_mapped"] = True
                    if pcp_ip:
                        MESH_STATE["external_ip"] = pcp_ip
                    if not logged_once:
                        print("[AutoMesh] PCP router port TCP/UDP %d mapped automatically!" % my_port)
                        logged_once = True
                else:
                    ok_pmp = _try_natpmp_clean(primary_lan, my_port)
                    if ok_pmp:
                        MESH_STATE["natpmp_mapped"] = True
                        if not logged_once:
                            print("[AutoMesh] NAT-PMP router port TCP/UDP %d mapped automatically!" % my_port)
                            logged_once = True
        _STOP_EVENT.wait(1200.0)


def start_for_p2p_node(p2p_node):
    global _ACTIVE_P2P_NODE
    if p2p_node is None or getattr(p2p_node, "_scash_auto_mesh_started", False):
        return
    p2p_node._scash_auto_mesh_started = True
    _ACTIVE_P2P_NODE = p2p_node
    MESH_STATE["started"] = True
    MESH_STATE["lan_ips"] = get_local_lan_ipv4s()

    try:
        port = int(getattr(p2p_node, "port", 0) or getattr(getattr(p2p_node, "net", None), "P2P_PORT", 8344) or 8344)
    except Exception:
        port = 8344
    MESH_STATE["p2p_port"] = port

    try:
        ident = getattr(getattr(p2p_node, "net", None), "IDENTIFIER", None)
        if ident:
            if isinstance(ident, bytes):
                import binascii
                MESH_STATE["net_id_hex"] = binascii.hexlify(ident).decode("ascii")
    except Exception:
        pass

    base_udp = int(os.environ.get("SCASH_MESH_UDP_PORT") or port)

    try:
        from twisted.internet import reactor as _tw_reactor

        def _poll_peers():
            _refresh_live_peer_counts()
            if not _STOP_EVENT.is_set():
                _tw_reactor.callLater(1.5, _poll_peers)

        _tw_reactor.callLater(0.5, _poll_peers)
    except Exception:
        pass

    for target_fn, args in (
        (_udp_beacon_worker, (p2p_node, base_udp)),
        (_udp_tunnel_pump_worker, ()),
        (_mesh_scanner_worker, (p2p_node,)),
        (_upnp_worker, (p2p_node,)),
    ):
        t = threading.Thread(target=target_fn, args=args)
        t.daemon = True
        t.start()

    print(
        "[AutoMesh] Serverless P2Pool Mesh active on :%d "
        "(Global Swarm + STUN UDP Hole-Punching + UPnP/PCP/NAT-PMP + Scash Node Gossip + LAN)"
        % port
    )
