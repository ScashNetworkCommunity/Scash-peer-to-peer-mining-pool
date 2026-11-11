Scash P2Pool Built-in CPU Miner Folder (v0.2.0-beta.7)
======================================================

You do NOT need to run anything inside this folder manually!
Just double-click Start-Scash-P2Pool.exe in the main folder above.

What is inside this folder (Full Edition):
- xmrigDaemon / xmrigMiner: Built from ScashNetworkCommunity/xmrigCC with
  -DWITH_MSR=ON and -DWITH_ASM=ON (0% internal miner fee).
- WinRing0x64.sys (Windows): Standard Ring0 MSR driver used by XMRig to tune
  CPU hardware cache prefetchers while mining RandomX (rx/scash) for full speed.
