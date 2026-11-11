from p2pool.bitcoin import networks
from p2pool.util import math

PARENT = networks.nets['scash']
SHARE_PERIOD = 15
CHAIN_LENGTH = 24 * 60 * 60 // 15
REAL_CHAIN_LENGTH = 24 * 60 * 60 // 15
TARGET_LOOKBEHIND = 200
SPREAD = 3
IDENTIFIER = '7363617368703270'.decode('hex')
PREFIX = '6b61776169697032'.decode('hex')
P2P_PORT = 8344
MIN_TARGET = 0
MAX_TARGET = 2**256 // 2**8 - 1
PERSIST = False
WORKER_PORT = 8345
BOOTSTRAP_ADDRS = 'seed.scash.one scash.tv scash.pool-pay.com satoshicash.cedric-crispin.com 5.59.96.54 144.76.17.34'.split(' ')
ANNOUNCE_CHANNEL = '#scash-p2pool'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set()
MINIMUM_PROTOCOL_VERSION = 1600
NEW_MINIMUM_PROTOCOL_VERSION = 1700
SEGWIT_ACTIVATION_VERSION = 16
