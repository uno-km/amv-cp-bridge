@echo off
cd /d "%~dp0"

REM ASCII only: cmd.exe reads batch files with OEM code page; non-ASCII + LF breaks parsing.
REM 1. Check executable Python runtime
python -c "import sys" >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ runtime was not detected.
    echo Run scripts\windows\1_install.bat first or install Python 3.10+.
    pause
    exit /b 1
)

REM 2. Prioritize local repo source and verify required dependencies
set "PYTHONPATH=%CD%;%PYTHONPATH%"
python -c "import customtkinter, fastapi, uvicorn, playwright" >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Required Python packages are missing.
    echo Run scripts\windows\1_install.bat or run: pip install -e .
    pause
    exit /b 1
)

REM 3. Resolve windowless pythonw.exe adjacent to sys.executable
set "PY_GUI="
for /f "usebackq delims=" %%P in (`python -c "import sys, os; pw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'); print(pw if os.path.isfile(pw) else sys.executable)"`) do set "PY_GUI=%%P"
if "%PY_GUI%"=="" set "PY_GUI=python"

REM 4. Launch 6-step diagnostic splash, version check, and native GUI
start "amv-cp-bridge" "%PY_GUI%" -m amv_cp_bridge.cli
exit /b 0
