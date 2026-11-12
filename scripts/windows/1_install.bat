@echo off
title amv-cp-bridge Local Setup ^& Launcher
cd /d "%~dp0..\.."

echo =====================================================================
echo  [amv-cp-bridge] M365 Copilot Bridge One-Click Setup
echo =====================================================================
echo.

REM 1. Check executable Python runtime
python -c "import sys" >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Python runtime was not detected.
    echo [*] Trying to install Python 3.11 via winget...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [-] Automatic installation failed. Install Python from https://www.python.org and retry.
        pause
        exit /b 1
    )
    echo [+] Python installation finished. Restart terminal or batch script to refresh PATH.
)

for /f "usebackq tokens=*" %%i in (`python -c "import sys; print(sys.version.split()[0])"`) do set PY_VER=%%i
echo [+] Python version detected: v%PY_VER%

REM 2. Install dependencies and register amv-cp-bridge editable package
echo.
echo [*] Installing dependencies and registering editable amv-cp-bridge package...
python -m pip install --upgrade pip --quiet
python -m pip install -e . --quiet
if %errorlevel% neq 0 (
    echo [-] Package installation failed.
    pause
    exit /b 1
)
echo [+] amv-cp-bridge package registration complete.

REM 3. Verify SQLite telemetry DB
python -c "from amv_cp_bridge.telemetry_db import telemetry_db; print('[+] Telemetry DB ready:', telemetry_db.db_path)"

echo.
echo =====================================================================
echo  [+] Setup complete. Starting dashboard at http://localhost:11500/dashboard
echo =====================================================================
echo.

set "PYTHONPATH=%CD%;%PYTHONPATH%"
python -m amv_cp_bridge.cli dashboard --port 11500
pause
