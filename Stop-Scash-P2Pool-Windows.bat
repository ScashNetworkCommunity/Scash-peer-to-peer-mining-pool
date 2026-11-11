@echo off
setlocal
cd /d "%~dp0"
echo Stopping Scash P2Pool background worker and headless scashd node...
if exist "%~dp0node\scash-cli.exe" (
    "%~dp0node\scash-cli.exe" -chain=scash -rpcport=8342 stop >nul 2>nul
    timeout /t 2 /nobreak >nul
)
taskkill /F /IM xmrigMiner.exe >nul 2>nul
taskkill /F /IM xmrigDaemon.exe >nul 2>nul
taskkill /F /IM scashd.exe >nul 2>nul
echo Done! All headless P2Pool / scashd background processes are stopped.
endlocal
