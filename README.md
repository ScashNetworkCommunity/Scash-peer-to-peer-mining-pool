# Scash Peer-to-Peer Mining Pool (`Scash-P2Pool` — QtKawaii Edition)

A decentralized, **0%-fee** peer-to-peer CPU mining pool for the **Scash Network** (`SCASH`), built on P2Pool's trustless PPLNS sharechain and upgraded for Scash's **112-byte RandomX v1.2.1** block headers (`RANDOMX_ARGON_SALT = "RandomX-Scash\x01"`), **`scash1...` Bech32** SegWit payouts, **dual XMRig (`rx/scash`) + `cpuminer-scash` Stratum**, and a **QtKawaii Web Dashboard**.

## Standalone Architecture (3 Local Layers, Zero Central Pool Server)

1. **Local Scash Node (`scashd` / `scash-qt`)** — Syncs the Scash blockchain on P2P port `:8343` (with active community `addnode=` peers automatically added to `scash.conf`) and serves block templates over local RPC `127.0.0.1:8342`.
2. **Standalone Scash P2Pool Node (`Start-Scash-P2Pool-Windows.bat` / `./start-scash-p2pool-linux.sh`)** — Ships with a **bundled portable PyPy 2.7 + Twisted runtime** (`runtime/pypy2/`) and **compiled native C++ `randomx.dll` / `librandomx.so`** (~30 MB standalone package—no Python install required). Connects to other P2Pool peers on port `:8344` and hosts your local Stratum + QtKawaii Web UI on `http://127.0.0.1:8345/static/`.
3. **CPU Miner (`cpuminer-scash` or `xmrigCC` `rx/scash`)** — Drop `minerd` (from `ScashNetworkCommunity/cpuminer-scash`) or `xmrigMiner` (`rx/scash`, without `WinRing0x64.sys`) into the `miner/` folder (or connect externally to `127.0.0.1:8345`), enter your `scash1...` address in the QtKawaii Web UI, and start mining!

## Quick Start (Standalone Pre-Release `v0.2.0-beta.1`)

1. Download **`Scash-P2Pool-v0.2.0-beta.1-Windows-x64.zip`** (~30 MB) or **`Scash-P2Pool-v0.2.0-beta.1-Linux-x64.tar.gz`** (~30 MB) from [Releases](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) and extract it. *(Note: No third-party miner executables or `WinRing0x64.sys` drivers are bundled inside the main release archive so browsers and Windows Security do not block the download.)*
2. Optional local auto-mining: Copy [`cpuminer-scash` (`minerd.exe`)](https://github.com/ScashNetworkCommunity/cpuminer-scash/releases) or `xmrigMiner.exe` (`rx/scash`) into the `miner/` subfolder.
3. Start your synced `scash-qt` / `scashd` wallet, then double-click **`Start-Scash-P2Pool-Windows.bat`** (Windows) or run **`./start-scash-p2pool-linux.sh`** (Linux).
4. Paste your **`scash1...`** address into the QtKawaii dashboard at **`http://127.0.0.1:8345/static/`**!

## Ports Reference
- `8342` (`127.0.0.1`): Scash Core JSON-RPC (`server=1`)
- `8343` (Public TCP): Scash Core P2P network (`fabfb5da` magic bytes)
- `8344` (Public TCP): **Scash P2Pool sharechain peer port** (forward TCP `8344` on your router for incoming pool peers)
- `8345` (`127.0.0.1`): Local Stratum server (accepts both XMRig `rx/scash` and `cpuminer-scash` Stratum V1) + QtKawaii Web UI (`/static/`)
