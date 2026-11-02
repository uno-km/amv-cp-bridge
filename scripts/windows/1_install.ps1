# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
param (
    [switch]$SetupOnly = $false,
    [int]$Port = 11500
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host " amv-cp-bridge :: Installer" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Cyan

# 1. Check Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[!] Python is not installed on this system." -ForegroundColor Yellow
    Write-Host "[*] Attempting automatic installation via winget..." -ForegroundColor Cyan
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[-] Automatic Python installation failed. Please install Python manually from https://python.org"
        exit 1
    }
}

$pyVer = python -c "import sys; print(sys.version.split()[0])"
Write-Host "[+] Python verified: v$pyVer" -ForegroundColor Green

# 2. Install dependencies & amv-cp-bridge
Write-Host "[*] Installing dependencies (fastapi, uvicorn, websockets, pydantic)..." -ForegroundColor Cyan
python -m pip install fastapi uvicorn websockets pydantic --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "[-] Failed to install dependencies."
    exit 1
}

Write-Host "[*] Registering amv-cp-bridge in editable mode..." -ForegroundColor Cyan
python -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "[-] Failed to install amv-cp-bridge."
    exit 1
}
Write-Host "[+] amv-cp-bridge registered successfully." -ForegroundColor Green

# 3. Telemetry DB verify
python -c "from amv_cp_bridge.telemetry_db import telemetry_db; print('[+] Telemetry SQLite DB ready: ~/.amv_cp_bridge/telemetry.db')"

if ($SetupOnly) {
    Write-Host "`n[+] Setup completed successfully! (-SetupOnly mode enabled)" -ForegroundColor Green
    Write-Host "[*] You can run the dashboard at any time using:" -ForegroundColor Yellow
    Write-Host "    amv-cp-bridge dashboard --port $Port" -ForegroundColor White
    exit 0
}

# 4. Launch Dashboard
Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host " [+] Setup complete! Launching Cyber Telemetry Dashboard..." -ForegroundColor Green
Write-Host " [*] Opening http://localhost:$Port/dashboard in your default browser" -ForegroundColor Yellow
Write-Host "=====================================================================" -ForegroundColor Cyan

amv-cp-bridge dashboard --port $Port
