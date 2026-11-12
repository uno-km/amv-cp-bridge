@echo off
cd /d "%~dp0..\.."
set "PYTHONPATH=%CD%;%PYTHONPATH%"
title amv-cp-bridge Core Dashboard [Port 11500]
cls
echo ============================================================
echo   [amv-cp-bridge] Sovereign AI Gateway ^& Dashboard
echo ============================================================
echo.
echo [*] Starting gateway and web telemetry dashboard...
echo [*] Dashboard URL: http://localhost:11500/dashboard
echo [*] Close this window or press Ctrl+C to stop.
echo.
python -m amv_cp_bridge.cli dashboard --port 11500
pause
