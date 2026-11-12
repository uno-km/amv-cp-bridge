@echo off
cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%;%PYTHONPATH%"
title amv-cp-bridge ^| Memory Purge (0MB)
cls
echo ============================================================
echo   [amv-cp-bridge] 0MB Memory Purge Utility
echo ============================================================
echo.
echo [*] Terminating residual Edge processes on ports 9333 / 9334...
echo.
python -m amv_cp_bridge.cli purge
echo.
echo [*] Current worker status:
python -m amv_cp_bridge.cli status
echo.
echo ============================================================
echo [DONE] Memory purge complete.
echo ============================================================
pause
