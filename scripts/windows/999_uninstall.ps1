# =============================================================================
#  amv-cp-bridge :: Complete Uninstaller
#  Usage: PowerShell -ExecutionPolicy Bypass -File 999.delete.ps1
#  Optional flags:
#    -KeepPlaywright   : skip Playwright browser cache removal
#    -KeepEXE          : do not prompt to delete dist\amv-cp-bridge.exe
# =============================================================================
param(
    [switch]$KeepPlaywright,
    [switch]$KeepEXE
)

$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "amv-cp-bridge Uninstaller"

function Step { param($msg) Write-Host "  >> $msg" -ForegroundColor Yellow }
function OK   { param($msg) Write-Host "  [v] $msg" -ForegroundColor Green }
function SKIP { param($msg) Write-Host "  [-] $msg" -ForegroundColor DarkGray }
function WARN { param($msg) Write-Host "  [!] $msg" -ForegroundColor Red }

Clear-Host
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "   amv-cp-bridge :: Complete Uninstaller" -ForegroundColor Cyan
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Kill amv-cp-bridge GUI/server processes ───────────────────────────────
Step "Stopping amv-cp-bridge processes..."
$procs = Get-Process -Name "amv-cp-bridge" -ErrorAction SilentlyContinue
if ($procs) {
    $procs | Stop-Process -Force
    Start-Sleep -Milliseconds 500
    OK "amv-cp-bridge process(es) terminated  ($($procs.Count) killed)"
} else {
    OK "No amv-cp-bridge process running"
}

# ── 2. Release port 11500 ─────────────────────────────────────────────────────
Step "Releasing port 11500..."
$netOut = & netstat -ano -p TCP 2>$null
foreach ($line in $netOut) {
    if ($line -match "TCP\s+\S+:11500\s+\S+\s+LISTENING\s+(\d+)") {
        $pid11 = $Matches[1]
        if ($pid11 -and $pid11 -ne "0") {
            & taskkill /F /PID $pid11 2>$null | Out-Null
        }
    }
}
OK "Port 11500 released"

# ── 3. Kill orphaned headless Edge workers ────────────────────────────────────
Step "Terminating orphaned Edge worker processes..."
$headless = Get-Process -Name "msedge" -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -eq "" }
if ($headless) {
    $headless | Stop-Process -Force -ErrorAction SilentlyContinue
    OK "Edge headless processes terminated  ($($headless.Count) killed)"
} else {
    OK "No orphaned Edge processes found"
}

# ── 4. Remove ~/.amv_cp_bridge/ (config, DB, logs) ───────────────────────────
Step "Removing data directory..."
$dataDir = Join-Path $env:USERPROFILE ".amv_cp_bridge"
if (Test-Path $dataDir) {
    Remove-Item -Recurse -Force $dataDir
    OK "Data directory removed:  $dataDir"
} else {
    OK "Data directory not found (already clean)"
}

# ── 5. Uninstall pip package ──────────────────────────────────────────────────
Step "Uninstalling pip package (amv-cp-bridge)..."
$pipOut = & python -m pip show amv-cp-bridge 2>&1
if ($pipOut -match "Name: amv") {
    & python -m pip uninstall -y amv-cp-bridge 2>&1 | Out-Null
    OK "pip package uninstalled"
} else {
    OK "pip package not installed (skipped)"
}

# ── 6. Remove MCP config entry from claude_desktop_config.json ───────────────
Step "Cleaning MCP configuration..."
$cfgCandidates = @(
    (Join-Path $env:APPDATA   "Claude\claude_desktop_config.json"),
    (Join-Path $env:USERPROFILE ".config\Claude\claude_desktop_config.json")
)
$mcpCleaned = $false
foreach ($cfgPath in $cfgCandidates) {
    if (Test-Path $cfgPath) {
        try {
            $raw = Get-Content $cfgPath -Raw
            $cfg = $raw | ConvertFrom-Json
            if ($cfg.mcpServers -and $cfg.mcpServers.PSObject.Properties.Name -contains "copilot") {
                $cfg.mcpServers.PSObject.Properties.Remove("copilot")
                $cfg | ConvertTo-Json -Depth 10 | Out-File $cfgPath -Encoding utf8 -NoNewline
                OK "MCP entry 'copilot' removed from  $cfgPath"
                $mcpCleaned = $true
            }
        } catch {
            WARN "Failed to parse MCP config: $cfgPath"
        }
    }
}
if (-not $mcpCleaned) { OK "No MCP config entry to remove" }

# ── 7. Playwright browser cache (optional) ────────────────────────────────────
if (-not $KeepPlaywright) {
    Step "Removing Playwright browser cache..."
    $pwPaths = @(
        (Join-Path $env:LOCALAPPDATA "ms-playwright"),
        (Join-Path $env:USERPROFILE  ".cache\ms-playwright")
    )
    $pwRemoved = $false
    foreach ($p in $pwPaths) {
        if (Test-Path $p) {
            Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
            OK "Playwright cache removed:  $p"
            $pwRemoved = $true
        }
    }
    if (-not $pwRemoved) { OK "No Playwright cache found" }
} else {
    SKIP "Playwright cache kept  (-KeepPlaywright flag set)"
}

# ── 8. Optionally delete the EXE ─────────────────────────────────────────────
if (-not $KeepEXE) {
    $exePath = Join-Path $PSScriptRoot "dist\amv-cp-bridge.exe"
    if (Test-Path $exePath) {
        Step "Removing EXE file..."
        try {
            Remove-Item -Force $exePath
            $internalDir = Join-Path $PSScriptRoot "dist\_internal"
            if (Test-Path $internalDir) { Remove-Item -Recurse -Force $internalDir }
            OK "EXE removed:  $exePath"
        } catch {
            WARN "Could not remove EXE (may be running). Close it first and re-run."
        }
    } else {
        OK "No EXE found in dist\ (skipped)"
    }
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "   All amv-cp-bridge data has been removed." -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Reminder: browser extensions must be removed manually." -ForegroundColor Yellow
Write-Host "    Chrome / Whale / Edge : go to  chrome://extensions" -ForegroundColor DarkGray
Write-Host "               and click Remove on  amv-cp-bridge Sidecar" -ForegroundColor DarkGray
Write-Host ""
