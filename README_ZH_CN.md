### 🌐 语言 / Language: [🇺🇸 English README](README.md) &nbsp;|&nbsp; **🇨🇳 简体中文（中国大陆/北京）** &nbsp;|&nbsp; [🇭🇰 繁體中文（香港/港澳台）](README_ZH_HK.md)

# Scash P2Pool — 一键式去中心化 CPU 联合矿池（QtKawaii 版 `v0.2.0`）

**发布团队：** `magicalgirlsunite` | **开源社区：** [`ScashNetworkCommunity`](https://github.com/ScashNetworkCommunity) | **矿池费率：** **99%** 区块奖励链上直发矿工钱包，**1%** 矿池作者维护费（`scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc`）

欢迎使用 **Scash P2Pool**！这是一款开箱即用的全合一 **Scash (`SCASH`)** 去中心化点对点（P2P）CPU 挖矿程序。您只需使用家用电脑的处理器（CPU）即可与其他矿工联合挖矿——**无需注册账号**、**无中心化服务器托管资金**、**无最低起付门槛**，也**无需额外安装复杂环境**。

所有组件均已打包在同一个文件夹内：
- **官方 Scash 2.3.0 (Core 30.4.0) 全节点**（[`ScashNetworkCommunity/scash`](https://github.com/ScashNetworkCommunity/scash/releases/tag/scash_v2.3.0-mid-world-core-30.4.0)）—— 自动连接 Scash 主网节点；如果您的电脑上已安装过 Scash 钱包，程序会自动复用现有区块数据，无需重复同步！
- **Scash P2Pool 份额链（Sharechain）** —— 将全球家用 CPU 矿工的算力点对点汇聚在一起，共同冲击下一个 `50 SCASH` 区块并按 PPLNS 稳定累计工作量份额。
- **内置高速 RandomX CPU 挖矿内核**（[`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) + [`WinRing0x64.sys`](https://github.com/xmrig/xmrig/blob/master/bin/WinRing0/WinRing0x64.sys) MSR 硬件寄存器加速驱动）—— 已针对 `rx/scash` 调优满血算力（内核本身 **0% 抽水**，全局仅含 P2Pool 份额链 **1%** 作者维护费）。
- **QtKawaii 本地网页控制台** —— 启动后自动在浏览器打开，填入您的 `scash1...` 钱包地址即可一键开挖，支持拖动滑块调节 CPU 线程数并实时查看算力与预计收益。

## 1. 下载哪个文件？

前往 [**Releases 发布页面**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) 下载对应您操作系统的压缩包：

| 下载文件名 | 适用人群 | 是否包含内置 CPU 挖矿程序？ |
| :--- | :--- | :--- |
| **`scash-p2pool-0.2.0-win64.zip`** | **Windows 用户首选推荐！** 解压即可一键开挖。 | **包含**（内置 `xmrigDaemon.exe` + `xmrigMiner.exe` + `WinRing0x64.sys` 加速驱动） |
| **`scash-p2pool-0.2.0-win64-nodeonly.zip`** | 希望自行使用外部挖矿软件的高级 Windows 用户。 | **不包含**（仅含全节点、P2Pool 与网页控制台） |
| **`scash-p2pool-0.2.0-x86_64-pc-linux-gnu.tgz`** | **Linux (64 位) 用户。** 开箱即用。 | **包含**（内置支持 MSR 加速的 `xmrigDaemon` + `xmrigMiner`） |

*（开挖前请确保您已安装 [Scash 官方钱包](https://github.com/ScashNetworkCommunity/scash/releases)，并准备好您自己的 **`scash1...`** 收款地址！）*

## 2. Windows 零基础四步开挖教程

### 第一步：在 Windows 安全中心添加专用白名单文件夹（仅首次需要）
与 [Monero 官方挖矿工具](https://www.getmonero.org/get-started/faq/)一样，Scash P2Pool 包含开源 CPU 挖矿内核及标准 `WinRing0x64.sys` 硬件加速驱动。由于杀毒软件通常会无差别拦截所有挖矿程序，**请先创建一个独立的白名单文件夹，避免核心文件被误删**：

> **安全提示：** 请勿将系统默认的“下载 (Downloads)”文件夹加入排除项，建议单独新建一个专用目录：

1. 打开**此电脑** -> **本地磁盘 (C:)**，新建一个名为 **`Scash-P2Pool`** 的文件夹（路径为 **`C:\Scash-P2Pool`**）。
2. 点击开始菜单，搜索并打开 **Windows 安全中心 (Windows Security)**。
3. 点击 **病毒和威胁防护** -> 在“病毒和威胁防护设置”下点击 **管理设置**。
4. 向下滚动找到 **排除项 (Exclusions)**，点击 **添加或删除排除项**。
5. 点击 **添加排除项** -> 选择 **文件夹** -> 选中 **`C:\Scash-P2Pool`**（[微软官方图文说明](https://learn.microsoft.com/en-us/answers/questions/3187645/how-to-add-an-exception-to-windows-defender)）。

### 第二步：下载并解压到 `C:\Scash-P2Pool`
1. 在 [**Releases 发布页面**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) 右键点击 **`scash-p2pool-0.2.0-win64.zip`**，选择 **链接另存为...**，直接保存到 **`C:\Scash-P2Pool`**。
2. 打开 **`C:\Scash-P2Pool`**，右键点击压缩包 -> **全部解压缩 (Extract All...)**。

### 第三步：双击运行 `Start-Scash-P2Pool.exe`
进入解压后的文件夹，双击 **`Start-Scash-P2Pool.exe`**（或 **`Start-Scash-P2Pool-Windows.bat`**）。首次启动时系统可能会弹出以下正常提示：
1. **“Windows 已保护你的电脑”（蓝色 SmartScreen 提示框）：** 点击 **更多信息 (More info)** -> **仍要运行 (Run anyway)**。
2. **管理员权限提示（UAC 弹窗）：** 请点击 **是 (Yes)**！管理员权限可自动开启 **MSR 缓存预取加速 (`WinRing0x64.sys`)** 与 **Windows 大页内存 (HugePages)**，使 RandomX CPU 算力提升 **2 至 4 倍**。
3. **Windows 防火墙提示：** 勾选**专用网络**与**公用网络**并点击**允许访问**，以便与全球其他 P2Pool 矿工节点互联。

### 第四步：粘贴 `scash1...` 钱包地址并开始挖矿！
1. 浏览器会自动打开 **QtKawaii 网页控制台**（`http://127.0.0.1:8345/static/`）。
   - *首次同步区块？* 若本地尚未同步完 Scash 区块链，页面顶部会显示区块同步进度（`0%` -> `100%`）。您可以先填入钱包地址保存，同步达到 `100%` 后将自动开始挖矿！
2. 从您的 **Scash 钱包**复制一个 **`scash1...`** 收款地址，粘贴到控制台的 **"Your Scash Wallet Address"** 输入框中，点击 **Start Built-in XMRig** 即可开挖！
3. **算力满血小贴士：** 首次以管理员身份运行后，建议**重启一次电脑**。重启后 Windows 大页内存（HugePages）权限将彻底生效，后续每次挖矿可额外获得 **20%–35%** 的算力提升！

### 如何停止挖矿
- **完全退出所有程序：** 直接点击黑色终端窗口右上角的 **`X`** 关闭按钮（或按 `Ctrl + C`）。内置的 Scash 节点、P2Pool 与 CPU 挖矿进程都会自动干净退出，绝不残留后台进程！（也可随时双击 `Stop-Scash-P2Pool-Windows.bat`。）
- **仅暂停 CPU 挖矿：** 在网页控制台点击 **Stop Built-in XMRig Miner**。

## 3. 常见问题解答（FAQ）

**问：为什么“Accepted Shares（已接受份额）”一直在增加，但钱包余额还是 0？**
答：**份额（Shares）** 就像您在过去 24 小时内向联合矿池提交的工作量凭证。P2Pool 不会每分钟发放零碎粉尘，而是**每当 P2Pool 全网任意矿工爆出一个完整的 Scash 区块（`50 SCASH`）时**，区块链会在该区块的创币交易（Coinbase）中**直接将 99% 的区块奖励按 PPLNS 份额比例打入每位在榜矿工自己的 `scash1...` 钱包**，其余 **1%**（`0.50 SCASH`）打入矿池作者维护地址（`scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc`）。收益链上秒到账，矿池从不触碰或托管您的资金！

**问：可以和桌面版 Scash 钱包（`scash-qt`）装在同一台电脑吗？**
答：完全可以！Scash P2Pool 会自动识别并复用 `AppData\Local\Scash` 中已同步的区块数据。*（提示：如果在首次启动 P2Pool 前您已经打开了 Scash 钱包窗口，建议先关闭一次钱包再启动 P2Pool，以便平滑共享区块目录。）*

**问：挖矿时还能正常看视频、办公或玩游戏吗？**
答：可以！内置挖矿程序默认仅绑定物理核心缓存线程，日常使用依然流畅。如需更低占用，只需在网页控制台调低 **CPU Threads（线程数）** 滑块并重启挖矿即可。

## 4. Linux 快速启动与路由器端口转发（进阶可选）

### Linux (64 位) 快速启动
```bash
tar -xzf scash-p2pool-0.2.0-x86_64-pc-linux-gnu.tgz
cd scash-p2pool-0.2.0
# 可选：开启 Linux 2MB 大页内存，并使用 sudo 运行以启用 MSR 寄存器加速
sudo sysctl -w vm.nr_hugepages=1280
./start-scash-p2pool-linux.sh
```

### 可选：家用路由器端口转发（Port Forwarding）
**无需设置路由器即可正常挖矿！** 如果您熟悉路由器端口映射，将 **TCP `8344`**（以及可选 **TCP `8343`**）转发到挖矿电脑的内网 IP，可允许其他 P2Pool 矿工主动连入您的节点，进一步降低份额广播延迟：

| TCP 端口 | 用途说明 | 是否建议在路由器转发？ |
| :--- | :--- | :--- |
| **`8344`** | **Scash P2Pool 份额链通信** | **可选（推荐）** —— 转发 TCP `8344` 可接收其他矿工入站连接 |
| **`8343`** | **Scash 主网全节点同步** | **可选** —— 转发 TCP `8343` 协助主网转发区块 |
| **`8345`** | **本地网页控制台与 Stratum 挖矿端口** | **切勿公网暴露！** 仅限本机或家庭局域网内其他电脑连接挖矿 |
| **`8342`** | **节点内部 RPC 接口** | **严禁开放或转发 `8342`！** 仅供本机 `127.0.0.1` 内部调用 |

### 校验安装包哈希值（`sha256sum`）
您可以在 PowerShell 中核对下载包的 SHA256 是否与发布页一致：
```powershell
Get-FileHash C:\Scash-P2Pool\scash-p2pool-0.2.0-win64.zip -Algorithm SHA256
```
