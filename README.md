# Scash Peer-to-Peer Mining Pool (`Scash-P2Pool` — QtKawaii Edition)

A decentralized, **0%-fee** peer-to-peer CPU mining pool for the **Scash Network** (`SCASH`), combining the classic Bitcoin P2Pool sharechain architecture with **RandomX v1.2.1** 112-byte block header commitments, native **`scash1...` Bech32** SegWit payouts, **built-in XMRig (`rx/scash`)** automatic mining, and a **QtKawaii Web Dashboard** matching the Scash QtKawaii Core wallet.

---

## How It Works (Decentralized 3-Layer Local Stack)

Just like Monero's P2Pool, there is **no central pool server** and **no pool operator custodying your coins**. Every miner runs their own sovereign stack locally, orchestrated by `start_scash_p2pool.py`:

| Layer | Local Component | Ports | Role |
| :--- | :--- | :--- | :--- |
| **1. Scash Full Node** | `scashd` / `scash-qt` (Core v27 / v30.4+) | **P2P `:8343`** (Public)<br>**RPC `:8342`** (`127.0.0.1`) | Syncs the Scash blockchain using preloaded active community peers (`scash.conf`) and serves fresh `getblocktemplate` jobs to your local P2Pool node. |
| **2. Scash P2Pool Node** | `run_p2pool.py --net scash` | **Sharechain `:8344`** (Public)<br>**Stratum & UI `:8345`** (`127.0.0.1`) | Connects to other miners' P2Pool nodes on port `:8344` to maintain a shared 24-hour PPLNS sharechain (15s target share time) and serves the QtKawaii UI at `http://127.0.0.1:8345/static/`. |
| **3. Built-in XMRig Miner** | `xmrigDaemon` (`xmrigCC` `-a rx/scash`) | Connects to **`127.0.0.1:8345`** | Automatically configures `miner/config.json` and hashes Scash RandomX commitments into your local P2Pool node as soon as you enter your `scash1...` address in the QtKawaii Web UI. |

### Trustless PPLNS Coinbase Payouts
Whenever *any* miner on the `:8344` P2Pool sharechain finds a RandomX commitment meeting full Scash network difficulty, the block's coinbase transaction pays **every active miner directly into their `scash1...` wallet** (`99.5%` distributed proportionally across the 5,760-share PPLNS window + `0.5%` block-finder bonus).

---

## Quick Start (Pre-Release Testing)

### Option 1: One-Click Pre-Release Bundle (Recommended)
1. Download the latest **Pre-Release** archive for your OS (`Windows-x64` or `Linux-x64`) from the [Releases page](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) and extract it.
2. Make sure `scash-qt` or `scashd` is installed (or running on your machine). On first launch, `start_scash_p2pool.py` automatically populates `scash.conf` with active community Scash nodes (`scash.tv:8343`, `scash.pool-pay.com:8343`, `satoshicash.cedric-crispin.com:8343`, `pool.rplant.xyz:8343`, and verified IPv4/IPv6 peers) without overwriting your existing settings, and starts `scashd` if it isn't running yet.
3. Launch the pool:
   - **Windows**: Double-click **`Start-Scash-P2Pool-Windows.bat`**
   - **Linux / macOS**: Run **`./start-scash-p2pool-linux.sh`** (or `python start_scash_p2pool.py`)
4. Your browser will open **`http://127.0.0.1:8345/static/`** (QtKawaii Web UI). Paste your **`scash1...`** wallet address into the UI, choose your CPU thread count, and built-in **XMRig (`rx/scash`)** will start mining automatically!

### Option 2: Running from Source
Scash P2Pool's core sharechain engine runs on **PyPy 2.7 / Python 2.7** with `Twisted` (while the launcher, node configurator, XMRig controller, and test suite work on both Python 2.7 and Python 3.x):

```bash
git clone https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool.git
cd Scash-peer-to-peer-mining-pool

# Launch full local stack (updates scash.conf, checks/starts scashd, opens QtKawaii UI, & starts XMRig)
python start_scash_p2pool.py --wallet YOUR_SCASH1_ADDRESS --threads 8
```

---

## Network & Port Reference

| Port | Protocol | Exposure | Purpose |
| :--- | :--- | :--- | :--- |
| `8342` | TCP (JSON-RPC) | `127.0.0.1` ONLY | Local `scashd` / `scash-qt` RPC connection for `getblocktemplate` (never expose publicly) |
| `8343` | TCP (P2P) | Public / NAT | Scash blockchain peer-to-peer port (`scashd`) |
| `8344` | TCP (P2P) | Public / NAT | **Scash P2Pool sharechain peer port** (forward TCP `8344` on your router for lower orphan rates and incoming pool peers) |
| `8345` | TCP (HTTP/Stratum) | `127.0.0.1` | Local Stratum mining endpoint (`stratum+tcp://127.0.0.1:8345`) + QtKawaii Web UI (`/static/`) |
| `8346` | TCP (HTTP) | `127.0.0.1` | Optional local XMRig telemetry API |

### Custom Difficulty Tuning (External Miners)
Built-in XMRig automatically calculates your optimal pseudoshare (`+`) and PPLNS sharechain (`/`) difficulty from your thread count. If connecting an external miner (`xmrigDaemon`, `poolpayminer`, or `cpuminer-scash`) to `127.0.0.1:8345`, you can append difficulty modifiers to your wallet address:
```text
scash1qYourWalletAddressHere.rig01+0.004/0.11
```
- `+0.004` sets local UI hashrate graph pseudoshare difficulty.
- `/0.11` sets minimum PPLNS sharechain target difficulty.

---

## Running Verification Tests

```bash
python3 tests/test_scash_p2pool_stack.py
```
Verifies BIP-173 `scash1...` Bech32 encoding/decoding, 112-byte Scash block header packing & RandomX commitment calculation, non-destructive `scash.conf` community node injection, built-in XMRig (`rx/scash`) config generation, and QtKawaii Web UI endpoints.

---

## License & Credits
- **P2Pool**: GNU General Public License v3.0 (`COPYING`) — originally created by Forrest Voight (`forrestv/p2pool`), adapted for Scash by **ScashNetworkCommunity**.
- **XMRig / xmrigCC (`rx/scash`)**: GNU General Public License v3.0 (`Bendr0id/xmrigCC` & `xmrig/xmrig`).
- **Scash Core & RandomX**: MIT License (`ScashNetworkCommunity/scash`) & BSD 3-Clause License (`tevador/RandomX`).
