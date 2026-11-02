param(
    [switch]$KeepPlaywright,
    [switch]$KeepEXE
)

$ProgressPreference = 'SilentlyContinue'
$script:Failures = 0

function Write-Ok([string]$Message) { Write-Host "[v] $Message" -ForegroundColor Green }
function Write-Skip([string]$Message) { Write-Host "[-] $Message" -ForegroundColor DarkGray }
function Write-Fail([string]$Message) { Write-Host "[x] $Message" -ForegroundColor Red; $script:Failures++ }

function Remove-PathChecked([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $Path) {
        Write-Fail "$Label could not be removed: $Path"
    } else {
        Write-Ok "$Label removed: $Path"
    }
}

Write-Host '================================================'
Write-Host ' amv-cp-bridge uninstall (Windows)'
Write-Host '================================================'

$dataDir = Join-Path $env:USERPROFILE '.amv_cp_bridge'
$installRoot = Join-Path $env:LOCALAPPDATA 'amv-cp-bridge'
$profiles = @(
    (Join-Path $env:USERPROFILE 'copilot_profile_default'),
    (Join-Path $env:USERPROFILE 'copilot_profile_secondary')
)
$accountsFile = Join-Path $dataDir 'accounts.json'
if (Test-Path -LiteralPath $accountsFile) {
    try {
        $accounts = Get-Content -LiteralPath $accountsFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($account in $accounts) {
            if ($account.profile_dir) {
                if ((Split-Path $account.profile_dir -Leaf) -like 'copilot_profile*' -or $account.profile_dir -like "$dataDir*") {
                    $profiles += $account.profile_dir
                } else {
                    Write-Skip "Custom Edge profile kept: $($account.profile_dir)"
                }
            }
        }
    } catch {
        Write-Fail "accounts.json could not be read: $($_.Exception.Message)"
    }
}
$profiles = @($profiles | Select-Object -Unique)

$exePaths = @(Join-Path $installRoot 'amv-cp-bridge.exe')
$processes = @(Get-Process -Name 'amv-cp-bridge' -ErrorAction SilentlyContinue)
$exePaths += @($processes | ForEach-Object { $_.Path } | Where-Object { $_ })
$exePaths += Join-Path $env:USERPROFILE 'Downloads\amv-cp-bridge.exe'
$desktop = [Environment]::GetFolderPath('Desktop')
if ($desktop) { $exePaths += Join-Path $desktop 'amv-cp-bridge.exe' }
$exePaths = @($exePaths | Select-Object -Unique)

if ($processes.Count -gt 0) {
    $processes | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
    Write-Ok "Stopped amv-cp-bridge processes: $($processes.Count)"
} else {
    Write-Ok 'No amv-cp-bridge process running'
}

foreach ($line in (& netstat -ano -p TCP)) {
    if ($line -match 'TCP\s+\S+:11500\s+\S+\s+LISTENING\s+(\d+)') {
        $ownerId = $Matches[1]
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
        if ($owner -and $owner.CommandLine -match 'amv[-_]cp[-_]bridge') {
            Stop-Process -Id $ownerId -Force -ErrorAction SilentlyContinue
            Write-Ok "Released port 11500 (PID $ownerId)"
        } else {
            Write-Skip "Port 11500 belongs to another application and was left alone (PID $ownerId)"
        }
    }
}

$edgeWorkers = @(Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $commandLine = $_.CommandLine
    $commandLine -and ($profiles | Where-Object { $commandLine -like "*--user-data-dir=$_*" })
})
foreach ($worker in $edgeWorkers) { Stop-Process -Id $worker.ProcessId -Force -ErrorAction SilentlyContinue }
if ($edgeWorkers.Count -gt 0) { Start-Sleep -Milliseconds 800 }
Write-Ok "Stopped dedicated Edge processes: $($edgeWorkers.Count)"

foreach ($edgeProfile in $profiles) { Remove-PathChecked $edgeProfile 'Edge profile' }
Remove-PathChecked $dataDir 'Settings, database, and logs'

if ($KeepEXE) {
    if (Test-Path -LiteralPath $installRoot) {
        Get-ChildItem -LiteralPath $installRoot -Force | Where-Object { $_.Name -ne 'amv-cp-bridge.exe' } | ForEach-Object {
            Remove-PathChecked $_.FullName 'Installed component'
        }
    }
    Write-Skip 'EXE kept (-KeepEXE)'
} else {
    foreach ($exe in $exePaths) { Remove-PathChecked $exe 'EXE' }
    Remove-PathChecked $installRoot 'Install folder'
}

$binDir = Join-Path $installRoot 'bin'
$environment = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$userPath = [string]$environment.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$pathEntries = @($userPath -split ';' | Where-Object { $_ })
$keptEntries = @($pathEntries | Where-Object { $_ -ne $binDir })
if ($keptEntries.Count -ne $pathEntries.Count) {
    $environment.SetValue('Path', ($keptEntries -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
    Write-Ok 'PATH entry removed'
}
$environment.Close()
[Environment]::SetEnvironmentVariable('AMV_CP_BRIDGE_HOME', $null, 'User')

if ($desktop) { Remove-PathChecked (Join-Path $desktop 'amv-cp-bridge.lnk') 'Desktop shortcut' }

$python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($python) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python.Source -m pip show amv-cp-bridge *> $null
    if ($LASTEXITCODE -eq 0) {
        & $python.Source -m pip uninstall -y amv-cp-bridge *> $null
        if ($LASTEXITCODE -eq 0) { Write-Ok 'pip package removed' } else { Write-Fail 'pip package could not be removed' }
    }
    $ErrorActionPreference = $previousPreference
}

foreach ($config in @((Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'), (Join-Path $env:USERPROFILE '.config\Claude\claude_desktop_config.json'))) {
    if (-not (Test-Path -LiteralPath $config)) { continue }
    try {
        $settings = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($settings.mcpServers -and $settings.mcpServers.PSObject.Properties.Name -contains 'copilot') {
            $settings.mcpServers.PSObject.Properties.Remove('copilot')
            [IO.File]::WriteAllText($config, ($settings | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
            Write-Ok "MCP entry removed: $config"
        }
    } catch {
        Write-Fail "MCP configuration could not be updated: $config"
    }
}

if ($KeepPlaywright) {
    Write-Skip 'Playwright cache kept (-KeepPlaywright)'
} else {
    Remove-PathChecked (Join-Path $env:LOCALAPPDATA 'ms-playwright') 'Playwright cache'
    Remove-PathChecked (Join-Path $env:USERPROFILE '.cache\ms-playwright') 'Playwright cache'
}

Write-Host '================================================'
if ($script:Failures -eq 0) {
    Write-Ok 'Uninstall complete'
} else {
    Write-Fail "Uninstall finished with $($script:Failures) problem(s). See the lines marked [x]."
}
Write-Host 'Browser extension: remove it at chrome://extensions, edge://extensions, or whale://extensions.'
Write-Host '================================================'
