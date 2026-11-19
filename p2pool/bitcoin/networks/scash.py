import os
from twisted.internet import defer
from .. import data, helper
from p2pool.util import pack
from p2pool import scash_nodes
from p2pool.bitcoin import scash_randomx

# Exact Scash Mainnet consensus parameters from ScashNetworkCommunity/scash (src/kernel/chainparams.cpp)
P2P_PREFIX = 'fabfb5da'.decode('hex')   # pchMessageStart = {0xfa, 0xbf, 0xb5, 0xda}
P2P_PORT = 8343                         # nDefaultPort = 8343
ADDRESS_VERSION = 0                     # base58Prefixes[PUBKEY_ADDRESS] = 0
ADDRESS_P2SH_VERSION = 5                # base58Prefixes[SCRIPT_ADDRESS] = 5
HUMAN_READABLE_PART = 'scash'           # bech32_hrp = "scash"
RPC_PORT = 8342                         # ChainType::SCASHMAIN RPC port = 8342

SCASH_GENESIS_HASH = 'e3bf1597a568216022dbda6a0945f09b005d19f041e7158c3cbca9d4029ee82d'

RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
    ((yield bitcoind.rpc_getblockchaininfo()).get('chain') in ('scash', 'main')) and
    ((yield bitcoind.rpc_getblockhash(0)) == SCASH_GENESIS_HASH)
))

SUBSIDY_FUNC = lambda height: 50 * 100000000 >> (height + 1) // 210000
POW_FUNC = lambda header_bytes: scash_randomx.get_pow_commitment_int256(header_bytes)
BLOCK_PERIOD = 600
SYMBOL = 'SCASH'

CONF_FILE_FUNC = lambda: os.path.join(scash_nodes.get_scash_datadir(), 'scash.conf')

BLOCK_EXPLORER_URL_PREFIX = 'https://scash.tv/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://scash.tv/address/'
TX_EXPLORER_URL_PREFIX = 'https://scash.tv/tx/'
SANE_TARGET_RANGE = (2**256 // 2**40 - 1, (2**256 // 2**10 - 1) if os.environ.get('SCASH_CI_FAST_DIFF') == '1' else (2**256 // 2**12 - 1))
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8

def _warm_scash_rx_async():
    try:
        import struct as _st, threading as _th, time as _tm
        _hdr = bytes(bytearray(68) + bytearray(_st.pack('<I', int(_tm.time()))) + bytearray(40))
        _t = _th.Thread(target=scash_randomx.get_pow_commitment_int256, args=(_hdr,))
        _t.daemon = True
        _t.start()
    except Exception:
        pass
_warm_scash_rx_async()
