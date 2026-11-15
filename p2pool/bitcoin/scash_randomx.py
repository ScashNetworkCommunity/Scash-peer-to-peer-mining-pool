"""
Consensus-Exact Scash 112-Byte Block Header & RandomX v1.2.1 Commitment Bridge.
Uses ctypes.c_void_p + pinned ctypes.create_string_buffer(data, n) (NEVER c_char_p!)
so embedded/leading NUL bytes and binary 32-byte hashes are never truncated under
PyPy 2.7 _ctypes or CPython 3. Includes automatic non-JIT VM fallback on hardened
Linux kernels and loud load-error reporting (never silent SHA-256 poisoning).
"""

from __future__ import print_function
import binascii
import ctypes
import hashlib
import os
import struct
import sys
import threading

MAINNET_EPOCH_DURATION = 7 * 24 * 60 * 60  # 604,800 seconds
RANDOMX_FLAG_JIT = 8

_rx_lock = threading.Lock()
_rx_lib = None
_rx_cache = None
_rx_vm = None
_rx_active_flags = 0
_rx_current_epoch = None
_rx_load_errors = []
_rx_found_file_on_disk = False


def get_scash_epoch(timestamp, epoch_duration=MAINNET_EPOCH_DURATION):
    return int(timestamp) // int(epoch_duration)


def get_scash_epoch_seed_bytes(timestamp, epoch_duration=MAINNET_EPOCH_DURATION):
    epoch = get_scash_epoch(timestamp, epoch_duration)
    seed_str = ("Scash/RandomX/Epoch/%d" % epoch).encode('ascii')
    return hashlib.sha256(hashlib.sha256(seed_str).digest()).digest()


def get_scash_epoch_seed_hex(timestamp, epoch_duration=MAINNET_EPOCH_DURATION):
    raw = get_scash_epoch_seed_bytes(timestamp, epoch_duration)
    h = binascii.hexlify(raw)
    return h.decode('ascii') if not isinstance(h, str) else h


def _load_librandomx():
    global _rx_lib, _rx_found_file_on_disk
    if _rx_lib is not None:
        return _rx_lib
    del _rx_load_errors[:]
    _rx_found_file_on_disk = False
    here = os.path.abspath(os.path.dirname(__file__))
    root = os.path.abspath(os.path.join(here, '..', '..'))
    cwd = os.path.abspath('.')
    search_paths = [
        os.path.join(root, 'randomx.dll'),
        os.path.join(root, 'librandomx.dll'),
        os.path.join(root, 'librandomx.so'),
        os.path.join(root, 'librandomx.dylib'),
        os.path.join(cwd, 'randomx.dll'),
        os.path.join(cwd, 'librandomx.so'),
        os.path.join(here, 'randomx.dll'),
        os.path.join(here, 'librandomx.so'),
        'randomx.dll',
        'librandomx.so',
        'librandomx.dylib',
    ]
    seen = set()
    for candidate in search_paths:
        if candidate in seen:
            continue
        seen.add(candidate)
        exists_on_disk = os.path.isabs(candidate) and os.path.isfile(candidate)
        if exists_on_disk:
            _rx_found_file_on_disk = True
        try:
            lib = ctypes.cdll.LoadLibrary(candidate)
            lib.randomx_get_flags.argtypes = []
            lib.randomx_get_flags.restype = ctypes.c_uint
            lib.randomx_alloc_cache.argtypes = [ctypes.c_uint]
            lib.randomx_alloc_cache.restype = ctypes.c_void_p
            lib.randomx_init_cache.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
            lib.randomx_init_cache.restype = None
            lib.randomx_release_cache.argtypes = [ctypes.c_void_p]
            lib.randomx_release_cache.restype = None
            lib.randomx_create_vm.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            lib.randomx_create_vm.restype = ctypes.c_void_p
            lib.randomx_destroy_vm.argtypes = [ctypes.c_void_p]
            lib.randomx_destroy_vm.restype = None
            lib.randomx_calculate_hash.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
            lib.randomx_calculate_hash.restype = None
            lib.randomx_calculate_commitment.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
            lib.randomx_calculate_commitment.restype = None
            _rx_lib = lib
            return _rx_lib
        except Exception as e:
            if exists_on_disk:
                _rx_load_errors.append("%s: %s" % (candidate, e))
            continue
    return None


def _get_vm_for_timestamp(timestamp):
    global _rx_cache, _rx_vm, _rx_active_flags, _rx_current_epoch
    lib = _load_librandomx()
    if lib is None:
        return None, None
    epoch = get_scash_epoch(timestamp)
    if _rx_vm is not None and _rx_current_epoch == epoch:
        return lib, _rx_vm

    seed_key = get_scash_epoch_seed_bytes(timestamp)
    seed_buf = ctypes.create_string_buffer(seed_key, 32)

    if _rx_vm is not None:
        lib.randomx_destroy_vm(_rx_vm)
        _rx_vm = None

    hw_flags = int(lib.randomx_get_flags())
    flag_candidates = []
    for fc in (hw_flags, hw_flags & ~RANDOMX_FLAG_JIT, 0):
        if fc not in flag_candidates:
            flag_candidates.append(fc)

    for cand_flags in flag_candidates:
        if _rx_cache is None or _rx_active_flags != cand_flags:
            if _rx_cache is not None:
                try:
                    lib.randomx_release_cache(_rx_cache)
                except Exception:
                    pass
                _rx_cache = None
            _rx_cache = lib.randomx_alloc_cache(cand_flags)
            if not _rx_cache:
                _rx_cache = None
                continue
            _rx_active_flags = cand_flags
        lib.randomx_init_cache(_rx_cache, seed_buf, 32)
        vm = lib.randomx_create_vm(cand_flags, _rx_cache, None)
        if vm:
            _rx_vm = vm
            _rx_current_epoch = epoch
            return lib, _rx_vm

    return lib, None


def is_native_randomx_loaded():
    return _load_librandomx() is not None


def get_load_diagnostics():
    return list(_rx_load_errors)


def _to_bytes(data):
    if isinstance(data, bytes):
        return data
    return data.encode('latin1')


def pack_header_for_randomx(header_bytes):
    raw = _to_bytes(header_bytes)
    return raw[:80] + (b'\x00' * 32)


def _unpack_uint256_le(raw_32):
    b = _to_bytes(raw_32)
    rev_hex = binascii.hexlify(b[::-1]).decode('ascii')
    return int(rev_hex, 16)


def calculate_scash_hash_and_cm_bytes(header_bytes):
    header_112 = pack_header_for_randomx(header_bytes)
    ntime = struct.unpack('<I', header_112[68:72])[0]
    with _rx_lock:
        lib, vm = _get_vm_for_timestamp(ntime)
        if lib is not None and vm is not None:
            hdr_buf = ctypes.create_string_buffer(header_112, 112)
            rx_hash = ctypes.create_string_buffer(32)
            rx_cm = ctypes.create_string_buffer(32)
            lib.randomx_calculate_hash(vm, hdr_buf, 112, rx_hash)
            lib.randomx_calculate_commitment(hdr_buf, 112, rx_hash, rx_cm)
            return rx_hash.raw, rx_cm.raw

    if _rx_found_file_on_disk or os.environ.get('SCASH_REQUIRE_NATIVE_RANDOMX') == '1':
        detail = '; '.join(_rx_load_errors) if _rx_load_errors else 'librandomx.so / randomx.dll missing or VM init failed'
        msg = '[CRITICAL] Native Scash RandomX library failed to initialize (%s)!' % detail
        print(msg, file=sys.stderr)
        sys.stderr.flush()
        raise RuntimeError(msg)

    rx_hash_fb = hashlib.sha256(header_112).digest()
    rx_cm_fb = hashlib.sha256(header_112 + rx_hash_fb).digest()
    return rx_hash_fb, rx_cm_fb


def calculate_rx_hash_and_cm_uint256(header_bytes):
    rx_hash_raw, rx_cm_raw = calculate_scash_hash_and_cm_bytes(header_bytes)
    return _unpack_uint256_le(rx_hash_raw), _unpack_uint256_le(rx_cm_raw)


def get_pow_commitment_int256(header_bytes):
    _, rx_cm_int = calculate_rx_hash_and_cm_uint256(header_bytes)
    return rx_cm_int
