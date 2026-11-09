"""
Scash 112-Byte Block Header & RandomX v1.2.1 Commitment Bridge for P2Pool.
Matches scashnetwork/cpuminer-scash/blob/master/randomx-miner.c:
- Serialized Scash block header is 112 bytes (uint32_t blockHeader[28]):
  - Bytes 0..79: standard 80-byte Bitcoin header (version, prev_block, merkle_root, timestamp, bits, nonce)
  - Bytes 80..111: 32-byte rx_hash field (zeroed when calculating rx_hash and rx_cm)
- Proof-of-Work target is checked against the 256-bit RandomX commitment (rx_cm).
"""
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

_rx_vm = None
_rx_lib = None

def _get_randomx_vm(seed_key=b'ScashRandomXKey\x00'):
    global _rx_vm, _rx_lib
    if _rx_vm is not None:
        return _rx_lib, _rx_vm
    for libname in ('librandomx.so', 'librandomx.dylib', 'randomx.dll'):
        try:
            lib = ctypes.cdll.LoadLibrary(libname)
            lib.randomx_get_flags.restype = ctypes.c_int
            lib.randomx_alloc_cache.argtypes = [ctypes.c_int]
            lib.randomx_alloc_cache.restype = ctypes.c_void_p
            lib.randomx_init_cache.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
            lib.randomx_create_vm.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
            lib.randomx_create_vm.restype = ctypes.c_void_p
            lib.randomx_calculate_hash.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
            lib.randomx_calculate_commitment.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
            flags = lib.randomx_get_flags()
            cache = lib.randomx_alloc_cache(flags)
            lib.randomx_init_cache(cache, seed_key, len(seed_key))
            vm = lib.randomx_create_vm(flags, cache, None)
            _rx_lib, _rx_vm = lib, vm
            return _rx_lib, _rx_vm
        except Exception:
            continue
    return None, None

def pack_header_for_randomx(header_bytes):
    if len(header_bytes) == 80:
        return header_bytes + ('\x00' * 32)
    return header_bytes[:80] + ('\x00' * 32)

def get_pow_commitment_int256(header_bytes):
    header_112 = pack_header_for_randomx(header_bytes)
    lib, vm = _get_randomx_vm()
    if lib is not None and vm is not None:
        rx_hash = ctypes.create_string_buffer(32)
        rx_cm = ctypes.create_string_buffer(32)
        lib.randomx_calculate_hash(vm, header_112, 112, rx_hash)
        lib.randomx_calculate_commitment(header_112, 112, rx_hash.raw, rx_cm)
        return pack.IntType(256).unpack(rx_cm.raw)
    digest = hashlib.sha256(hashlib.sha256(header_112).digest()).digest()
    return pack.IntType(256).unpack(digest)
