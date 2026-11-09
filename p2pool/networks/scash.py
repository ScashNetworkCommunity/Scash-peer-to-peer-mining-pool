from p2pool.bitcoin import networks
from p2pool.util import math

# P2Pool Sharechain configuration for Scash Mainnet
PARENT = networks.nets['scash']
SHARE_PERIOD = 15                       # 15s target share interval
CHAIN_LENGTH = 24 * 60 * 60 // 15       # 5,760 shares (24h window)
REAL_CHAIN_LENGTH = 24 * 60 * 60 // 15  # 5,760 shares PPLNS payout window
TARGET_LOOKBEHIND = 200                 # 200 shares difficulty regulation
SPREAD = 3                              # 3 blocks work spread
IDENTIFIER = '7363617368703270'.decode('hex')  # 'scashp2p'
PREFIX = '6b61776169697032'.decode('hex')      # 'kawaiip2'
P2P_PORT = 8344                         # P2Pool peer-to-peer sharechain port
MIN_TARGET = 0
MAX_TARGET = 2**256 // 2**8 - 1         # Low minimum difficulty for home CPUs
PERSIST = False                         # False allows single-node bootstrap; set True when seed nodes are active
WORKER_PORT = 8345                      # Local Stratum & QtKawaii Web UI port
BOOTSTRAP_ADDRS = 'seed.scash.one'.split(' ')
ANNOUNCE_CHANNEL = '#scash-p2pool'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: None
SEGWIT_ACTIVATION_VERSION = 16          # Enables SegWit & native scash1... Bech32 payouts
