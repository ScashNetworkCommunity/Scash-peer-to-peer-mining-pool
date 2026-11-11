@echo off
setlocal
cd /d "%~dp0"
title Scash P2Pool - peer2peer-pool (QtKawaii Edition v0.2.0-beta.5)
if exist "%~dp0Start-Scash-P2Pool.exe" (
    "%~dp0Start-Scash-P2Pool.exe" %*
) else if exist "%~dp0runtime\pypy2\pypy.exe" (
    "%~dp0runtime\pypy2\pypy.exe" "%~dp0start_scash_p2pool.py" %*
) else (
    where pypy >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        pypy "%~dp0start_scash_p2pool.py" %*
    ) else (
        python "%~dp0start_scash_p2pool.py" %*
    )
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [NOTICE] Scash P2Pool exited with status code %ERRORLEVEL%.
    pause
)
endlocal
