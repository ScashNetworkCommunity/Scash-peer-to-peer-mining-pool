@echo off
setlocal
cd /d "%~dp0"
title Scash P2Pool v0.2.0-beta.1 (Standalone QtKawaii Edition)
echo ==================================================================
echo   Scash Peer-to-Peer Mining Pool (Standalone Windows x64 Runtime)
echo ==================================================================
if exist "runtime\pypy2\pypy.exe" (
    "runtime\pypy2\pypy.exe" start_scash_p2pool.py %*
) else (
    python start_scash_p2pool.py %*
)
pause
