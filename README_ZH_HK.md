### 🌐 語言 / Language: [🇺🇸 English README](README.md) &nbsp;|&nbsp; [🇨🇳 简体中文（中国大陆/北京）](README_ZH_CN.md) &nbsp;|&nbsp; **🇭🇰 繁體中文（香港/港澳台）**

# Scash P2Pool — 一鍵式去中心化 CPU 聯合礦池（QtKawaii 版 `v0.2.0`）

**發佈團隊：** `magicalgirlsunite` | **開源社區：** [`ScashNetworkCommunity`](https://github.com/ScashNetworkCommunity) | **礦池費率：** **99%** 區塊獎勵鏈上直發礦工錢包，**1%** 礦池作者維護費（`scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc`）

歡迎使用 **Scash P2Pool**！這是一款開箱即用的全合一 **Scash (`SCASH`)** 去中心化點對點（P2P）CPU 挖礦程式。您只需用家用電腦的處理器（CPU）即可與其他礦工聯合挖礦——**無需註冊賬戶**、**無中心化伺服器託管資金**、**無最低出金門檻**，亦**無需額外安裝繁瑣環境**。

所有組件已完整打包於同一資料夾內：
- **官方 Scash 2.3.0 (Core 30.4.0) 全節點**（[`ScashNetworkCommunity/scash`](https://github.com/ScashNetworkCommunity/scash/releases/tag/scash_v2.3.0-mid-world-core-30.4.0)）—— 自動連接 Scash 主網節點；若電腦已安裝 Scash 錢包，程式會自動共用現有區塊鏈資料，無需重新下載！
- **Scash P2Pool 份額鏈（Sharechain）** —— 將全球家用 CPU 礦工的算力點對點連結起來，合力尋找下一個 `50 SCASH` 區塊並按 PPLNS 穩定累積份額。
- **內置高速 RandomX CPU 挖礦核心**（[`ScashNetworkCommunity/xmrigCC`](https://github.com/ScashNetworkCommunity/xmrigCC) + [`WinRing0x64.sys`](https://github.com/xmrig/xmrig/blob/master/bin/WinRing0/WinRing0x64.sys) MSR 硬體暫存器加速驅動）—— 預先調校滿血 `rx/scash` 算力（挖礦核心 **0% 額外抽成**，全局僅收 P2Pool 份額鏈 **1%** 作者維護費）。
- **QtKawaii 本地網頁控制面板** —— 啟動後自動喺瀏覽器打開，貼上您的 `scash1...` 錢包地址即可一鍵開挖，支援滑桿調節 CPU 執行緒數量並即時查看算力同預計收益。

## 1. 應該下載邊個檔案？

前往 [**Releases 發佈頁面**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) 揀選適合您電腦系統的檔案：

| 下載檔案名稱 | 適用對象 | 是否內置 CPU 挖礦程式？ |
| :--- | :--- | :--- |
| **`scash-p2pool-0.2.0-win64.zip`** | **Windows 用戶首選推薦！** 解壓縮即可一鍵開挖。 | **包含**（內置 `xmrigDaemon.exe` + `xmrigMiner.exe` + `WinRing0x64.sys` 加速驅動） |
| **`scash-p2pool-0.2.0-win64-nodeonly.zip`** | 希望自行使用外部挖礦軟件的進階 Windows 用戶。 | **不包含**（僅含全節點、P2Pool 及網頁控制面板） |
| **`scash-p2pool-0.2.0-x86_64-pc-linux-gnu.tgz`** | **Linux (64 位元) 用戶。** 開箱即用。 | **包含**（內置支援 MSR 加速的 `xmrigDaemon` + `xmrigMiner`） |

*（開挖前請確認已安裝 [Scash 官方錢包](https://github.com/ScashNetworkCommunity/scash/releases)，並準備好您自己的 **`scash1...`** 收款地址！）*

## 2. Windows 新手四步開挖教學

### 第一步：喺 Windows 安全性新增專用排除資料夾（只需設定一次）
同 [Monero 官方挖礦程式](https://www.getmonero.org/get-started/faq/)一樣，Scash P2Pool 內含開源 CPU 挖礦軟件及標準 `WinRing0x64.sys` 硬體加速驅動。由於防毒軟件預設會攔截所有挖礦程式，**請先建立一個專用排除資料夾，以免核心檔案被誤刪**：

> **安全提示：** 切勿將系統預設的「下載 (Downloads)」資料夾加入排除項目，建議專門建立一個獨立資料夾：

1. 打開**檔案總管** -> **本機** -> **本機磁碟 (C:)**，新增一個名為 **`Scash-P2Pool`** 的資料夾（路徑為 **`C:\Scash-P2Pool`**）。
2. 點擊開始選單，搜尋並打開 **Windows 安全性 (Windows Security)**。
3. 點擊 **病毒與威脅防護** -> 在「病毒與威脅防護設定」下點擊 **管理設定**。
4. 向下捲動至 **排除項目 (Exclusions)**，點擊 **新增或移除排除項目**。
5. 點擊 **新增排除項目** -> 揀選 **資料夾** -> 選取 **`C:\Scash-P2Pool`**（[Microsoft 官方步驟教學](https://learn.microsoft.com/en-us/answers/questions/3187645/how-to-add-an-exception-to-windows-defender)）。

### 第二步：儲存並解壓縮至 `C:\Scash-P2Pool`
1. 喺 [**Releases 發佈頁面**](https://github.com/ScashNetworkCommunity/Scash-peer-to-peer-mining-pool/releases) 右鍵點擊 **`scash-p2pool-0.2.0-win64.zip`**，揀選 **另存連結為...**，直接儲存入 **`C:\Scash-P2Pool`**。
2. 打開 **`C:\Scash-P2Pool`**，右鍵點擊 `.zip` 壓縮檔 -> **全部解壓縮 (Extract All...)**。

### 第三步：雙擊執行 `Start-Scash-P2Pool.exe`
進入解壓縮後的資料夾，雙擊 **`Start-Scash-P2Pool.exe`**（或 **`Start-Scash-P2Pool-Windows.bat`**）。首次啟動時 Windows 可能會顯示以下正常提示：
1. **「Windows 已保護您的電腦」（藍色 SmartScreen 視窗）：** 點擊 **其他資訊 (More info)** -> **仍要執行 (Run anyway)**。
2. **系統管理員權限提示（UAC 視窗）：** 請點擊 **是 (Yes)**！以系統管理員身分執行可自動啟用 **MSR 快取加速 (`WinRing0x64.sys`)** 同 **Windows 大頁記憶體 (HugePages)**，令 RandomX CPU 算力提升 **2 至 4 倍**。
3. **Windows 防火牆提示：** 勾選**私人網路**與**公用網路**並點擊**允許存取**，以便與全球其他 P2Pool 礦工節點互連。

### 第四步：貼上 `scash1...` 錢包地址並開始挖礦！
1. 瀏覽器會自動打開 **QtKawaii 網頁控制面板**（`http://127.0.0.1:8345/static/`）。
   - *首次同步區塊鏈？* 若本機尚未同步完 Scash 區塊鏈，頂部橫幅會顯示同步進度（`0%` -> `100%`）。您可以先貼上錢包地址儲存，同步完成後會自動開挖！
2. 喺您的 **Scash 錢包**複製一個 **`scash1...`** 收款地址，貼入控制面板的 **"Your Scash Wallet Address"** 欄位，再點擊 **Start Built-in XMRig** 即可開始挖礦！
3. **滿血算力小貼士：** 首次以系統管理員身分執行後，建議**重新開機一次**。重啟後 Windows 大頁記憶體（HugePages）權限會完全生效，之後每次挖礦可額外獲得 **20%–35%** 算力提升！

### 如何停止挖礦
- **完全關閉所有程式：** 直接點擊黑色終端機視窗右上角的 **`X`** 關閉按鈕（或按 `Ctrl + C`）。內置 Scash 節點、P2Pool 及 CPU 挖礦程序會一併乾淨退出，唔會殘留背景程序！（亦可隨時雙擊 `Stop-Scash-P2Pool-Windows.bat`。）
- **只暫停 CPU 挖礦：** 喺網頁控制面板點擊 **Stop Built-in XMRig Miner**。

## 3. 常見問題（FAQ）

**問：點解「Accepted Shares（已接受份額）」一直增加，但錢包餘額仲係 0？**
答：**份額（Shares）** 代表您過去 24 小時內對聯合礦池貢獻的工作量比重。P2Pool 唔會每分鐘派發碎銀，而係**每當 P2Pool 全網任何礦工成功解出一個完整 Scash 區塊（`50 SCASH`）時**，區塊鏈會喺該區塊的 Coinbase 創幣交易入面**即時將 99% 區塊獎勵按 PPLNS 份額比例直接打入每位在榜礦工自己的 `scash1...` 錢包**，其餘 **1%**（`0.50 SCASH`）則發放至礦池作者維護地址（`scash1qct8wwcl6p8z6rhgmy9f6v8mxehrpa22ra32vwc`）。收益鏈上即時到賬，礦池絕不託管或扣留您的資金！

**問：可唔可以同桌面版 Scash 錢包（`scash-qt`）裝喺同一部電腦？**
答：完全可以！Scash P2Pool 會自動偵測並共用 `AppData\Local\Scash` 內已同步的區塊資料。*（提示：如果首次啟動 P2Pool 前已經開住 Scash 錢包視窗，建議先關閉一次錢包再啟動 P2Pool，即可順暢共用區塊資料夾。）*

**問：挖礦期間仲可唔可以正常睇片、上網或打機？**
答：可以！內置挖礦程式預設只綁定實體核心快取執行緒，日常操作依然順暢。如果想進一步降低電腦負載，只需喺控制面板調低 **CPU Threads（執行緒數量）** 滑桿並重新啟動挖礦即可。

## 4. Linux 快速啟動及路由器端口轉發（進階選用）

### Linux (64 位元) 快速啟動
```bash
tar -xzf scash-p2pool-0.2.0-x86_64-pc-linux-gnu.tgz
cd scash-p2pool-0.2.0
# 選用：啟用 Linux 2MB 大頁記憶體，並以 sudo 執行以開啟 MSR 暫存器加速
sudo sysctl -w vm.nr_hugepages=1280
./start-scash-p2pool-linux.sh
```

### 選用：家用路由器端口轉發（Port Forwarding）
**無需改動路由器設定即可正常挖礦！** 如您熟悉路由器 Port Forwarding 設定，將 **TCP `8344`**（及選用 **TCP `8343`**）轉發至挖礦電腦的內網 IP，可讓其他 P2Pool 礦工主動連入您的節點，進一步降低份額廣播延遲：

| TCP 端口 | 用途說明 | 是否建議喺路由器轉發？ |
| :--- | :--- | :--- |
| **`8344`** | **Scash P2Pool 份額鏈連線** | **選用（推薦）** —— 轉發 TCP `8344` 可接收其他礦工入站連線 |
| **`8343`** | **Scash 主網全節點同步** | **選用** —— 轉發 TCP `8343` 協助主網轉發區塊 |
| **`8345`** | **本地網頁控制面板及 Stratum 挖礦端口** | **切勿對外公開！** 僅限本機或屋企 Wi-Fi 內其他電腦連接挖礦 |
| **`8342`** | **節點內部 RPC 介面** | **嚴禁開放或轉發 `8342`！** 僅供本機 `127.0.0.1` 內部呼叫 |

### 驗證下載檔案雜湊值（`sha256sum`）
您可於 PowerShell 核對壓縮檔的 SHA256 是否與發佈頁一致：
```powershell
Get-FileHash C:\Scash-P2Pool\scash-p2pool-0.2.0-win64.zip -Algorithm SHA256
```
