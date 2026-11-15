from p2pool.bitcoin import networks
from p2pool.util import math

PARENT = networks.nets['scash']
SHARE_PERIOD = 15
CHAIN_LENGTH = 24 * 60 * 60 // 15
REAL_CHAIN_LENGTH = 24 * 60 * 60 // 15
TARGET_LOOKBEHIND = 200
SPREAD = 3
IDENTIFIER = '7363617368703236'.decode('hex')  # scashp26
PREFIX = '6b61776169697036'.decode('hex')      # kawaiip6
P2P_PORT = 8344
MIN_TARGET = 0
MAX_TARGET = 2**256 // 2**8 - 1
PERSIST = False
WORKER_PORT = 8345
import os as _os
BOOTSTRAP_ADDRS = [] if _os.environ.get('SCASH_CI_ISOLATED_MESH') == '1' else (
    'p2pool.magicalgirlsunite.moe magicalgirlsunite.moe seed.scash.one scash.tv '
    'scash.pool-pay.com satoshicash.cedric-crispin.com pool.rplant.xyz '
    '5.59.96.54 5.128.87.126 5.186.40.82 144.76.17.34 198.199.73.40 88.190.223.96 209.141.46.154'
).split()
ANNOUNCE_CHANNEL = '#scash-p2pool'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set()
MINIMUM_PROTOCOL_VERSION = 1600
NEW_MINIMUM_PROTOCOL_VERSION = 1700
SEGWIT_ACTIVATION_VERSION = 16
