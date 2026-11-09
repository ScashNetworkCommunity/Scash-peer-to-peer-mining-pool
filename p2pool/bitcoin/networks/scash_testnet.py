import os
import platform
from twisted.internet import defer
from .. import data, helper
from p2pool.util import pack
from p2pool.bitcoin import scash_randomx

P2P_PREFIX = '0b110907'.decode('hex')
P2P_PORT = 18343
ADDRESS_VERSION = 111
ADDRESS_P2SH_VERSION = 196
HUMAN_READABLE_PART = 'tcash'
RPC_PORT = 18342

RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
    ((yield bitcoind.rpc_getblockchaininfo()).get('chain') in ('scashtestnet', 'test'))
))

SUBSIDY_FUNC = lambda height: 50 * 100000000 >> (height + 1) // 210000
POW_FUNC = lambda header_bytes: scash_randomx.get_pow_commitment_int256(header_bytes)
BLOCK_PERIOD = 600
SYMBOL = 'tSCASH'

CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Scash') if platform.system() == 'Windows'
    else os.path.expanduser('~/Library/Application Support/Scash/') if platform.system() == 'Darwin'
    else os.path.expanduser('~/.scash'),
    'scash.conf'
)

BLOCK_EXPLORER_URL_PREFIX = 'https://scash.one/testnet/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://scash.one/testnet/address/'
TX_EXPLORER_URL_PREFIX = 'https://scash.one/testnet/tx/'
SANE_TARGET_RANGE = (2**256 // 2**32 - 1, 2**256 // 2 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
