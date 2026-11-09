import ctypes
import hashlib
from p2pool.util import pack

scash_block_header_type = pack.ComposedType([
    ('version', pack.IntType(32)),
    ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
    ('merkle_root', pack.IntType(256)),
    ('timestamp', pack.IntType(32)),
    ('bits', pack.IntType(32)),
    ('nonce', pack.IntType(32)),
    ('rx_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
])

def pack_header_for_randomx(header_bytes):
    if len(header_bytes) == 80:
        return header_bytes + ('\x00' * 32)
    return header_bytes[:80] + ('\x00' * 32)

def get_pow_commitment_int256(header_bytes):
    header_112 = pack_header_for_randomx(header_bytes)
    try:
        librx = ctypes.cdll.LoadLibrary('librandomx.so')
        rx_hash = ctypes.create_string_buffer(32)
        rx_cm = ctypes.create_string_buffer(32)
        librx.randomx_calculate_commitment(header_112, 112, rx_hash, rx_cm)
        return pack.IntType(256).unpack(rx_cm.raw)
    except Exception:
        digest = hashlib.sha256(hashlib.sha256(header_112).digest()).digest()
        return pack.IntType(256).unpack(digest)
