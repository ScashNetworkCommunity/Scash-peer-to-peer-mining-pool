# Scash Peer-to-Peer Mining Pool (`Scash-P2Pool` — QtKawaii Edition)

**Publisher:** `magicalgirlsunite` | **Community:** [`ScashNetworkCommunity`](https://github.com/ScashNetworkCommunity)

A decentralized, **0%-pool-fee** peer-to-peer CPU mining pool for the **Scash Network** (`SCASH`). Modeled on Monero's sovereign local P2Pool architecture, every miner runs their own local Scash Core node (`scashd` / `scash-qt`) connected to their own local Scash P2Pool node (`112-byte` RandomX v1.2.1 block headers with `RANDOMX_ARGON_SALT = "RandomX-Scash\x01"`), with automatic **`scash1...` Bech32** PPLNS payouts, a **QtKawaii Web Dashboard**, and built-in [`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) (`rx/scash`) CPU mining.

## Choose Your Release Package (`v0.2.0-beta.3` Pre-Release)

Download from [**GitHub Releases**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases):

| Package | Includes Built-in `xmrigCC`? | Launchers Included | Best For |
| :--- | :--- | :--- | :--- |
| **`Scash-P2Pool-v0.2.0-beta.3-Windows-x64.zip`** | Yes (`xmrigMiner.exe` + `xmrigDaemon.exe`, `-DWITH_MSR=OFF`) | `Start-Scash-P2Pool.exe` **and** `Start-Scash-P2Pool-Windows.bat` | Full out-of-the-box Windows mining (requires a folder exclusion in Windows Security; see Step 1 below) |
| **`Scash-P2Pool-v0.2.0-beta.3-NodeOnly-Windows-x64.zip`** | No (`miner/` contains no `.exe` files) | `Start-Scash-P2Pool.exe` **and** `Start-Scash-P2Pool-Windows.bat` | Running the P2Pool node + QtKawaii UI cleanly while pointing your own external miner at `127.0.0.1:8345` |
| **`Scash-P2Pool-v0.2.0-beta.3-Linux-x64.tar.gz`** | Yes (`xmrigMiner` + `xmrigDaemon`, `-DWITH_MSR=OFF`) | `./start-scash-p2pool-linux.sh` | Full out-of-the-box Linux x64 mining |

All packages now bundle the **official [Scash 2.3.0 (Mid-World Core 30.4.0)](https://github.com/ScashNetworkCommunity/scash/releases/tag/scash_v2.3.0-mid-world-core-30.4.0) node daemon (`node/scashd.exe` / `node/scashd`)** so Scash P2Pool spins up your own local Scash Core 30.4.0 node automatically out of the box—plus **portable PyPy 2.7 + Twisted** (`runtime/pypy2/`), CMake-compiled **`randomx.dll`** (`CompanyName: magicalgirlsunite`), **17 active Scash community `addnode=` peers**, and **both** a native **`Start-Scash-P2Pool.exe`** launcher (`CompanyName: magicalgirlsunite`) and a plain **`Start-Scash-P2Pool-Windows.bat`** script in case you prefer running the batch file instead of the `.exe`.

## Step 1 (Windows Full Bundle): Windows Security Folder Exclusion & Hash Check

Like official [Monero downloads](https://www.getmonero.org/get-started/faq/) and [Gupax](https://github.com/hinto-janai/gupax/blob/main/README.md), the full Windows bundle includes open-source XMRig binaries compiled from [`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) (built from source in GitHub Actions with `-DWITH_MSR=OFF`, so **no `WinRing0x64.sys` kernel driver** is shipped). Because malware authors frequently abuse open-source XMRig code, Microsoft Defender flags `xmrigMiner.exe` / `xmrigDaemon.exe` as `Trojan:Win64/HashvaultMiner.A` or `Program:Win32/Contebrew.A!ml` if downloaded into an unexcluded folder.

> **Security Tip:** Never add your general `Downloads` folder to antivirus exclusions. Always create a dedicated folder solely for Scash P2Pool and verify the `SHA256SUMS.txt` checksum.

1. Create a dedicated folder on your PC, such as **`C:\Scash-P2Pool`**.
2. Open **Windows Security** -> **Virus & threat protection** -> under *Virus & threat protection settings*, click **Manage settings**.
3. Scroll down to **Exclusions** -> click **Add or remove exclusions** -> **Add an exclusion** -> **Folder**, and select **`C:\Scash-P2Pool`** ([Microsoft Q&A guide](https://learn.microsoft.com/en-us/answers/questions/3187645/how-to-add-an-exception-to-windows-defender)).
4. On the [Releases page](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases), right-click **`Scash-P2Pool-v0.2.0-beta.3-Windows-x64.zip`**, choose **Save link as...**, and save it directly inside **`C:\Scash-P2Pool`**.
5. Verify your download integrity in PowerShell against `SHA256SUMS.txt`:
   ```powershell
   Get-FileHash C:\Scash-P2Pool\Scash-P2Pool-v0.2.0-beta.3-Windows-x64.zip -Algorithm SHA256
   ```
6. Right-click the `.zip` -> **Properties** -> check **Unblock** (if shown) -> **OK**, then extract it inside `C:\Scash-P2Pool`.

*(Note on Windows SmartScreen / Publisher Warning: `Start-Scash-P2Pool.exe` and `randomx.dll` carry `CompanyName: magicalgirlsunite` in File Properties -> Details. Until an Authenticode certificate is attached, Windows may show an "Unknown Publisher" prompt on first launch—click **More info -> Run anyway**, or simply run **`Start-Scash-P2Pool-Windows.bat`** instead.)*

## Step 2: Firewall & Router Port-Forwarding Setup

Scash P2Pool uses four ports—two for peer-to-peer networking and two that should stay strictly local on your machine or home LAN:

| TCP Port | Service | Firewall / Router Recommendation |
| :--- | :--- | :--- |
| **`8342`** | Local `scashd` / `scash-qt` JSON-RPC | **Localhost (`127.0.0.1`) ONLY — NEVER open or port-forward `8342` in your firewall or router!** |
| **`8343`** | Scash Core Node P2P (`fabfb5da`) | **Allow Inbound & Outbound TCP** (optional router port-forward for full node peers) |
| **`8344`** | **Scash P2Pool Sharechain P2P** | **Allow Inbound & Outbound TCP** + forward TCP `8344` on your router so pool peers can connect to you |
| **`8345`** | Local Stratum Miner + QtKawaii Web UI | **Keep local (`127.0.0.1`)** if mining on one PC, or allow on **Private (Home LAN) only** for extra home rigs |

### Option A: Windows Defender Firewall via PowerShell (Fastest)
Open **PowerShell as Administrator** and run ([`New-NetFirewallRule` docs](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule?view=windowsserver2025-ps)):

```powershell
New-NetFirewallRule -DisplayName "Scash Core P2P (TCP 8343)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8343 -Profile Private,Public
New-NetFirewallRule -DisplayName "Scash P2Pool Sharechain (TCP 8344)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8344 -Profile Private,Public
```

*(Optional — run this **only** if you want other mining PCs on your home Wi-Fi/LAN to connect to this PC's P2Pool Stratum port `8345`; keep `Public` blocked:)*

```powershell
New-NetFirewallRule -DisplayName "Scash P2Pool Home LAN Miners (TCP 8345)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8345 -Profile Private
```

### Option B: Windows Defender Firewall via Graphical Interface (`wf.msc`)
1. On first launch, if Windows pops up **"Windows Defender Firewall has blocked some features of this app"** for `scashd.exe`, `Start-Scash-P2Pool.exe`, or `pypy.exe`, check **Private networks** (and **Public networks** if you want incoming P2Pool peers) and click **Allow access** ([Microsoft Support](https://support.microsoft.com/en-us/surface/accessories/surface-display-adapter/troubleshooting-microsoft-wireless-display-adapter)).
2. To open the peer ports manually: press **`Win + R`**, type **`wf.msc`**, and press **Enter** to open **Windows Defender Firewall with Advanced Security**.
3. Click **Inbound Rules** (left pane) -> **New Rule...** (right pane).
4. Select **Port** -> **Next** -> select **TCP**, enter **`8343, 8344`** in **Specific local ports** -> **Next**.
5. Select **Allow the connection** -> **Next** -> keep **Domain, Private, Public** checked -> **Next**.
6. Name the rule **`Scash P2Pool Peer Ports (8343-8344)`** and click **Finish**.

### Option C: Linux Firewall (`ufw`)
```bash
sudo ufw allow 8343/tcp comment 'Scash Core P2P'
sudo ufw allow 8344/tcp comment 'Scash P2Pool Sharechain'
# Optional: allow extra mining rigs on your local home LAN only
# sudo ufw allow from 192.168.0.0/16 to any port 8345 proto tcp
```

### Optional Router Port Forwarding (Recommended for Lower Share Latency)
Outbound mining works behind NAT without router changes, but forwarding **TCP `8344`** (and optionally **TCP `8343`**) in your router's **Port Forwarding / NAT** settings to your mining PC's local LAN IP (e.g., `192.168.1.50`) lets other Scash P2Pool nodes connect inbound to your sharechain node directly. **Never port-forward `8342` or `8345` to the internet.**

## Step 3: Launch & Mine!

1. **No separate node install needed!** Bundled `node/scashd` (**Scash 2.3.0 / Mid-World Core 30.4.0**) spins up automatically on `127.0.0.1:8342` (RPC) and `:8343` (P2P with 17 active Scash peers)—or connects to your already-open Scash Core 30.4.0 wallet if running. During initial block sync, the QtKawaii Dashboard opens immediately at `http://127.0.0.1:8345/static/` showing live block sync progress.
2. Start Scash P2Pool using whichever launcher you prefer:
   - **Windows (`.exe` launcher)**: Double-click **`Start-Scash-P2Pool.exe`**
   - **Windows (`.bat` script)**: Double-click **`Start-Scash-P2Pool-Windows.bat`**
   - **Linux**: Run **`./start-scash-p2pool-linux.sh`**
3. Your browser opens the **QtKawaii Dashboard** at `http://127.0.0.1:8345/static/`—paste your **`scash1...`** wallet address, pick your CPU thread count, and click **Start Mining**!
