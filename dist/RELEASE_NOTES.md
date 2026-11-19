## Scash Peer-to-Peer Mining Pool `v0.1.0-beta.1` (Pre-Release for Community Testing)

This is the first community testing **Pre-Release** of **Scash P2Pool (QtKawaii + Built-in XMRig Edition)**!

### What's Included in `v0.1.0-beta.1`
- **Sovereign 3-Layer Decentralized Pool**: Connects your local `scashd` / `scash-qt` node (`:8342` RPC / `:8343` P2P) to a peer-to-peer PPLNS sharechain (`:8344`) with **0% pool fees** and direct coinbase payouts to `scash1...` Bech32 addresses.
- **Built-in XMRig (`rx/scash`) Auto-Mining**: Pre-packaged with `xmrigCC` (`-a rx/scash`) support inside `miner/`. Entering your `scash1...` address into the Web UI automatically configures `miner/config.json` and begins mining into `127.0.0.1:8345`.
- **QtKawaii Web Dashboard (`http://127.0.0.1:8345/static/`)**: Styled to match the Scash Core QtKawaii wallet, featuring live PPLNS payout estimates, sharechain explorer, 112-byte RandomX header commitment inspector, and floating Node Window.
- **Active Community Scash Peers Preloaded**: Automatically updates `scash.conf` with active community Scash `addnode=` peers on port `:8343` (replacing the retired `scash.one` seed) without overwriting existing settings.

### Pre-Release Testing Checklist
1. Extract the bundle for your OS (`Windows-x64.zip` or `Linux-x64.tar.gz`) and verify checksums against `SHA256SUMS.txt`.
2. Ensure `scash-qt` or `scashd` is synced on mainnet (or let `start_scash_p2pool.py` spin up `scashd` with the bundled community peer list).
3. Run `Start-Scash-P2Pool-Windows.bat` (Windows) or `./start-scash-p2pool-linux.sh` (Linux).
4. Paste your `scash1...` address in the QtKawaii dashboard at `http://127.0.0.1:8345/static/`, forward TCP port `8344` if behind a router, and report peer connectivity, share propagation, and hashrate feedback in Issues!
