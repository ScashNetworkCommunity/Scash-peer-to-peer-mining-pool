import os
import platform
from twisted.internet import defer
from .. import data, helper
from p2pool.util import pack
from p2pool.bitcoin import scash_randomx

# Scash Mainnet parent network definition for P2Pool
# Compatible with Scash Core v2.0.0 / v3.0.0-mid-world-core-30.4.0
P2P_PREFIX = 'f9beb4d9'.decode('hex')
P2P_PORT = 8343
ADDRESS_VERSION = 63
ADDRESS_P2SH_VERSION = 125
HUMAN_READABLE_PART = 'scash'
RPC_PORT = 8342

RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
    ((yield bitcoind.rpc_getblockchaininfo()).get('chain') in ('scash', 'main'))
))

SUBSIDY_FUNC = lambda height: 50 * 100000000 >> (height + 1) // 210000
POW_FUNC = lambda header_bytes: scash_randomx.get_pow_commitment_int256(header_bytes)
BLOCK_PERIOD = 600  # 10 minutes target spacing (ASERT per-block adjustment)
SYMBOL = 'SCASH'

CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Scash') if platform.system() == 'Windows'
    else os.path.expanduser('~/Library/Application Support/Scash/') if platform.system() == 'Darwin'
    else os.path.expanduser('~/.scash'),
    'scash.conf'
)

BLOCK_EXPLORER_URL_PREFIX = 'https://scash.one/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://scash.one/address/'
TX_EXPLORER_URL_PREFIX = 'https://scash.one/tx/'
SANE_TARGET_RANGE = (2**256 // 2**32 - 1, 2**256 // 2**4 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
