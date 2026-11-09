from p2pool.bitcoin import networks
from p2pool.util import math

PARENT = networks.nets['scash_testnet']
SHARE_PERIOD = 15
CHAIN_LENGTH = 24 * 60 * 60 // 15
REAL_CHAIN_LENGTH = 24 * 60 * 60 // 15
TARGET_LOOKBEHIND = 200
SPREAD = 3
IDENTIFIER = '7473636173687032'.decode('hex')
PREFIX = '746b617761696970'.decode('hex')
P2P_PORT = 18344
MIN_TARGET = 0
MAX_TARGET = 2**256 // 2**4 - 1
PERSIST = False
WORKER_PORT = 18345
BOOTSTRAP_ADDRS = 'testnet.seed.scash.one'.split(' ')
ANNOUNCE_CHANNEL = '#scash-p2pool-test'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: None
SEGWIT_ACTIVATION_VERSION = 16
