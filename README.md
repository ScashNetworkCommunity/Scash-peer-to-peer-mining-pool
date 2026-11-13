## 🇨🇳 [**中文使用指南（简体中文 · 中国大陆/北京）**](README_ZH_CN.md) &nbsp;|&nbsp; 🇭🇰 [**中文使用指南（繁體中文 · 香港/港澳台）**](README_ZH_HK.md)

# Scash P2Pool — Easy All-in-One CPU Mining Pool (QtKawaii Edition `v0.2.0`)

**Publisher:** `magicalgirlsunite` | **Community:** [`ScashNetworkCommunity`](https://github.com/ScashNetworkCommunity) | **Pool Fee:** **1%** to Pool Author (`scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc`), **99%** straight to Miners

Welcome to **Scash P2Pool**! This is an easy, all-in-one program that lets you mine **Scash (`SCASH`)** using your regular home computer's processor (CPU) together with other miners—with **no accounts to create**, **no website holding your coins**, and **no extra software to install**.

Everything you need is packed inside one folder:
- **Official Scash 2.3.0 (Core 30.4.0) Node** ([`ScashNetworkCommunity/scash`](https://github.com/ScashNetworkCommunity/scash/releases/tag/scash_v2.3.0-mid-world-core-30.4.0)) — connects automatically to the Scash network and reuses your existing Scash Wallet blockchain if you already have it on your PC!
- **Scash P2Pool Sharechain** — teams up your CPU with other miners so everyone earns steady shares toward the next `50 SCASH` block.
- **Fast Built-in CPU Miner** ([`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) + [`WinRing0x64.sys`](https://github.com/xmrig/xmrig/blob/master/bin/WinRing0/WinRing0x64.sys) MSR CPU speed booster) — pre-configured for full RandomX speed (`0%` extra miner fee; only the `1%` P2Pool author fee applies).
- **QtKawaii Web Dashboard** — opens automatically in your web browser so you can paste your wallet address, adjust CPU threads with a simple slider, and watch your live speed and payouts.

## 1. Which File Should I Download?

Go to the [**Releases Page**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) and pick the file that matches your computer:

| Download File | Who Is It For? | Built-in CPU Miner Included? |
| :--- | :--- | :--- |
| **`scash-p2pool-0.2.0-win64.zip`** | **Recommended for Windows users!** Ready to mine out of the box. | **Yes** (`xmrigDaemon.exe` + `xmrigMiner.exe` + `WinRing0x64.sys` speed booster) |
| **`scash-p2pool-0.2.0-win64-nodeonly.zip`** | Advanced Windows users who want to use their own separate mining app. | **No** (`miner/` has no `.exe` or `.sys` files) |
| **`scash-p2pool-0.2.0-x86_64-pc-linux-gnu.tgz`** | **Linux (64-bit) users.** Ready to mine out of the box. | **Yes** (`xmrigDaemon` + `xmrigMiner` with MSR support) |

*(Make sure you also have the [Scash Wallet](https://github.com/ScashNetworkCommunity/scash/releases) installed so you have your own **`scash1...`** receiving address where your mined coins will be sent!)*

## 2. Easy Step-by-Step Guide for Windows (No Tech Experience Needed!)

### Step 1: Create an Allowed Folder in Windows Security (One-Time Setup)
Just like [official Monero mining apps](https://www.getmonero.org/get-started/faq/), Scash P2Pool includes open-source CPU mining software and the standard `WinRing0x64.sys` CPU speed-boost driver. Because bad actors sometimes hide crypto miners inside unrelated downloads, **Windows Security automatically deletes CPU miners unless you put them in their own allowed folder first**.

> **Safety Tip:** Never add your general `Downloads` folder to exclusions. Instead, make one dedicated folder just for Scash P2Pool:

1. Open **File Explorer**, click **This PC** -> **Local Disk (C:)**, and create a new folder named **`Scash-P2Pool`** (so its path is **`C:\Scash-P2Pool`**).
2. Click the Windows **Start** button, type **Windows Security**, and open the **Windows Security** app.
3. Click **Virus & threat protection**, then under *Virus & threat protection settings*, click **Manage settings**.
4. Scroll down to **Exclusions** and click **Add or remove exclusions**.
5. Click **Add an exclusion** -> choose **Folder** -> select **`C:\Scash-P2Pool`** ([Microsoft step-by-step guide](https://learn.microsoft.com/en-us/answers/questions/3187645/how-to-add-an-exception-to-windows-defender)).

### Step 2: Save & Unzip Inside `C:\Scash-P2Pool`
1. On the [**Releases Page**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases), **right-click** **`scash-p2pool-0.2.0-win64.zip`** and click **Save link as...**.
2. Choose **`C:\Scash-P2Pool`** and click **Save** *(saving straight into `C:\Scash-P2Pool` keeps Windows from deleting it in your `Downloads` folder)*.
3. Open **`C:\Scash-P2Pool`**, **right-click** the `.zip` file, click **Extract All...**, and click **Extract**.

### Step 3: Double-Click `Start-Scash-P2Pool.exe`
Open your extracted folder and double-click **`Start-Scash-P2Pool.exe`** (or **`Start-Scash-P2Pool-Windows.bat`**). On your very first launch, Windows may show up to three normal prompts:
1. **"Windows protected your PC" (Blue SmartScreen box):** Click **More info** -> **Run anyway**.
2. **"Do you want to allow this app to make changes to your device?" (Administrator prompt):** Click **Yes**! Running as Administrator lets the miner turn on **MSR CPU cache tuning (`WinRing0x64.sys`)** and **Windows Huge Pages**, making your mining speed **2x to 4x faster**.
3. **"Windows Defender Firewall has blocked some features":** Check **Private networks** and **Public networks**, then click **Allow access** so other miners can connect with you.

### Step 4: Paste Your `scash1...` Address & Start Mining!
1. Your web browser will automatically open the **QtKawaii Dashboard** at `http://127.0.0.1:8345/static/`.
   - *First time syncing?* If your PC hasn't synced the Scash blockchain yet, a purple banner at the top shows sync progress (`0%` -> `100%`). You can paste your wallet address right away and mining will start automatically as soon as sync hits `100%`!
2. Open your **Scash Wallet**, copy a **`scash1...`** receiving address, paste it into **"Your Scash Wallet Address"** on the Dashboard, and click **Start Built-in XMRig**!
3. **One-Time Bonus Speed Tip:** After running as Administrator for the very first time on Windows, **restart your computer once**. Rebooting lets Windows finish unlocking "Huge Pages" memory, giving your CPU an extra **20%–35% speed boost** on every run after that!

### How to Stop Mining
- **To stop everything cleanly:** Simply click the **`X`** button at the top-right of the black terminal window (or press `Ctrl + C`). The Scash node, P2Pool, and CPU miner all shut down automatically—nothing stays stuck in Task Manager! *(You can also double-click `Stop-Scash-P2Pool-Windows.bat` anytime.)*
- **To pause only CPU mining:** Click **Stop Built-in XMRig Miner** on the Dashboard.

## 3. Common Beginner Questions (FAQ)

**Q: I see "Accepted Shares" going up, so why is my Scash Wallet balance still 0?**
Think of **Shares** like raffle/work tickets showing how much work your CPU contributed to the pool over the last 24 hours. Nobody gets paid tiny dust every minute—instead, **the moment anyone on Scash P2Pool solves a full Scash Block (`50 SCASH`)**, the Scash blockchain immediately sends **99%** of that `50 SCASH` block directly into the wallets of every miner on the **PPLNS Payouts** list (split fairly by your share %) and **1%** (`0.50 SCASH`) to the pool author (`scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc`). Because coins go straight to your wallet on the blockchain, the pool never holds your funds!

**Q: Can I keep Scash Wallet (`scash-qt`) installed on the same PC?**
Yes! Scash P2Pool automatically detects your existing blockchain inside `AppData\Local\Scash` so you don't have to download blocks twice. *(Tip: If your Scash Wallet window was already open before your very first P2Pool launch, close Scash Wallet briefly—or restart it once—so both programs share your synced blocks smoothly.)*

**Q: Can I still browse the web, watch videos, or play games while mining?**
Yes! By default, the miner automatically uses only your CPU's physical cache cores so your computer stays responsive. If you want your PC even lighter while gaming or working, just drag the **CPU Threads** slider lower on the Dashboard and restart the miner.

**Q: Next time I start it, do I have to paste my wallet address again?**
Nope! Your `scash1...` wallet address is saved locally on your PC, so next time you double-click `Start-Scash-P2Pool.exe`, it syncs and starts mining automatically.

## 4. Linux Quick Start & Optional Home Router Tips (Advanced)

### Linux (64-bit) Quick Start
```bash
tar -xzf scash-p2pool-0.2.0-x86_64-pc-linux-gnu.tgz
cd scash-p2pool-0.2.0
# Optional: enable Linux 2MB HugePages & run with sudo if you want MSR CPU register tuning
sudo sysctl -w vm.nr_hugepages=1280
./start-scash-p2pool-linux.sh
```

### Optional: Forwarding Port `8344` on Your Home Router
Mining works right away with **zero router changes**! However, if you know how to open **Port Forwarding** in your home Wi-Fi router settings, forwarding **TCP Port `8344`** (and optionally **TCP Port `8343`**) to your mining PC's local IP address lets other P2Pool miners connect inbound to you for even lower latency:

| TCP Port | What Uses It | Should I Forward It on My Router? |
| :--- | :--- | :--- |
| **`8344`** | **Scash P2Pool Sharechain** | **Optional (Recommended)** — forward TCP `8344` so other P2Pool nodes can connect to you |
| **`8343`** | **Scash Blockchain Node** | **Optional** — forward TCP `8343` to help relay Scash blocks |
| **`8345`** | **Your Dashboard & Local Miner** | **NO — Keep Private!** Only open on your home Wi-Fi if connecting a 2nd PC in your house |
| **`8342`** | **Internal Node Connection** | **NEVER open or port-forward `8342`!** Strictly for `127.0.0.1` on your own PC |

### Optional: Verifying Your Download (`SHA256SUMS.txt`)
If you'd like to verify your `.zip` matches `SHA256SUMS.txt` on the Releases page, open PowerShell and run:
```powershell
Get-FileHash C:\Scash-P2Pool\scash-p2pool-0.2.0-win64.zip -Algorithm SHA256
```
