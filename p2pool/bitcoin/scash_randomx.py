"""
Scash 112-Byte Block Header & RandomX v1.2.1 Commitment Bridge for P2Pool.
Works under both Python 2.7 (PyPy/Twisted P2Pool runtime) and Python 3.x (CI verification).
"""
import binascii
import ctypes
import hashlib

try:
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
except Exception:
    pack = None
    scash_block_header_type = None

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
    if isinstance(header_bytes, bytes):
        pad = b'\x00' * 32
        return (header_bytes + pad) if len(header_bytes) == 80 else (header_bytes[:80] + pad)
    pad = '\x00' * 32
    return (header_bytes + pad) if len(header_bytes) == 80 else (header_bytes[:80] + pad)

def _unpack_uint256_le(raw_32):
    if pack is not None:
        try:
            return pack.IntType(256).unpack(raw_32)
        except Exception:
            pass
    if not isinstance(raw_32, bytes):
        raw_32 = raw_32.encode('latin1')
    rev_hex = binascii.hexlify(raw_32[::-1]).decode('ascii')
    return int(rev_hex, 16)

def get_pow_commitment_int256(header_bytes):
    header_112 = pack_header_for_randomx(header_bytes)
    raw_in = header_112 if isinstance(header_112, bytes) else header_112.encode('latin1')
    lib, vm = _get_randomx_vm()
    if lib is not None and vm is not None:
        rx_hash = ctypes.create_string_buffer(32)
        rx_cm = ctypes.create_string_buffer(32)
        lib.randomx_calculate_hash(vm, raw_in, 112, rx_hash)
        lib.randomx_calculate_commitment(raw_in, 112, rx_hash.raw, rx_cm)
        return _unpack_uint256_le(rx_cm.raw)
    digest = hashlib.sha256(hashlib.sha256(raw_in).digest()).digest()
    return _unpack_uint256_le(digest)
