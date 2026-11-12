@echo off
cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%;%PYTHONPATH%"
title amv-cp-bridge Gateway [Port 11500]
cls
echo ============================================================
echo   [amv-cp-bridge] 365 Copilot AI Gateway
echo ============================================================
echo.
echo [*] Starting API gateway at http://localhost:11500 ...
echo [*] Close this window or press Ctrl+C to stop.
echo.
python -m amv_cp_bridge.cli gateway --port 11500
pause
