# Scash Peer-to-Peer Mining Pool (`Scash-P2Pool` — QtKawaii + Built-in `xmrigCC` Edition)

A decentralized, **0%-pool-fee** peer-to-peer CPU mining pool for the **Scash Network** (`SCASH`), combining P2Pool's trustless PPLNS sharechain with **Scash's 112-byte RandomX v1.2.1** block headers (`RANDOMX_ARGON_SALT = "RandomX-Scash\x01"`), native **`scash1...` Bech32** SegWit payouts, **pre-compiled [`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) (`rx/scash`, built from source with `-DWITH_MSR=OFF`)**, and a **QtKawaii Web Dashboard**.

## Works 100% Out of the Box (Nothing Extra to Install or Copy)

Every standalone release (`~35 MB`) comes ready to mine out of the box:
1. **Pre-Compiled [`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) (`miner/xmrigMiner` & `miner/xmrigDaemon`)**: Compiled directly from our organization's `xmrigCC` source repository with `-DWITH_MSR=OFF` so **no `WinRing0x64.sys` kernel driver** is included. Automatically starts mining `rx/scash` into `127.0.0.1:8345` as soon as you enter your `scash1...` wallet address in the QtKawaii Web UI!
2. **Compiled Native C++ Scash RandomX Engine (`randomx.dll` / `librandomx.so`)**: Built from [`ScashNetworkCommunity/RandomX`](https://github.com/ScashNetworkCommunity/RandomX/tree/scash) and verified in CI against the Scash Mainnet Genesis Block (`e3bf1597a568216022dbda6a0945f09b005d19f041e7158c3cbca9d4029ee82d`).
3. **Bundled Portable Runtime (`runtime/pypy2/` + `Twisted 20.3.0`)**: Users do **not** need Python installed on Windows or Linux.
4. **Active Community Scash Peers (`p2pool/scash_nodes.py`)**: Automatically adds active community Scash `addnode=` peers (`:8343`) to `scash.conf` without overwriting existing user settings, and spins up local `scashd` if needed.

## Quick Start (`v0.2.0-beta.1` Pre-Release)

1. Download **`Scash-P2Pool-v0.2.0-beta.1-Windows-x64.zip`** or **`Scash-P2Pool-v0.2.0-beta.1-Linux-x64.tar.gz`** from [Releases](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) and extract it.
2. Start your synced Scash Core wallet (`scash-qt` or `scashd`), then launch Scash P2Pool:
   - **Windows**: Double-click **`Start-Scash-P2Pool-Windows.bat`**
   - **Linux**: Run **`./start-scash-p2pool-linux.sh`**
3. Paste your **`scash1...`** address into the QtKawaii Web UI (`http://127.0.0.1:8345/static/`), choose your CPU thread count, and built-in **`xmrigCC` (`rx/scash`)** starts mining automatically!

## Ports Reference
- `8342` (`127.0.0.1`): Local `scashd` / `scash-qt` JSON-RPC (`server=1`)
- `8343` (Public TCP): Scash Core P2P (`fabfb5da` magic bytes)
- `8344` (Public TCP): **Scash P2Pool sharechain peer port** (forward TCP `8344` on your router for incoming pool peers)
- `8345` (`127.0.0.1`): Local Stratum server (speaks both XMRig `rx/scash` and `cpuminer-scash` Stratum V1) + QtKawaii Web UI (`/static/`)
