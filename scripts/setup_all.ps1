$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Ok([string]$Message) { Write-Host "[v] $Message" -ForegroundColor Green }
function Write-Busy([string]$Message) { Write-Host "[ ] $Message" -ForegroundColor DarkGray }

function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$Log) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments *>> $Log
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        $tail = (Get-Content $Log -Tail 15) -join "`n"
        throw "Command failed (exit $code): $Exe $($Arguments -join ' ')`n$tail"
    }
}

function Find-Python {
    $probe = 'import sys,tkinter,venv;assert sys.version_info>=(3,10);print(sys.executable)'
    $candidates = @()
    foreach ($name in 'python', 'python3') {
        $found = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $candidates += ,@($found.Source) }
    }
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) { $candidates += ,@($launcher.Source, '-3') }
    $userRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $userRoot) {
        Get-ChildItem $userRoot -Directory -Filter 'Python3*' | Sort-Object Name -Descending | ForEach-Object {
            $candidates += ,@((Join-Path $_.FullName 'python.exe'))
        }
    }
    foreach ($candidate in $candidates) {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $exe = $candidate[0]
            $extra = @($candidate | Select-Object -Skip 1)
            $output = & $exe @extra -c $probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) { return ([string]($output | Select-Object -Last 1)).Trim() }
        } catch {
            continue
        } finally {
            $ErrorActionPreference = $previous
        }
    }
    return $null
}

function Install-Python([string]$Version, [string]$Log) {
    $parts = $Version.Split('.')
    $target = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$($parts[0])$($parts[1])"
    $installer = Join-Path $env:TEMP "python-$Version-amd64.exe"
    Write-Busy "Downloading Python $Version"
    Invoke-WebRequest "https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe" -OutFile $installer -UseBasicParsing
    Write-Busy "Installing Python $Version"
    $arguments = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=0', 'Include_test=0', 'Include_doc=0', "TargetDir=`"$target`"", "/log", "`"$Log.python.txt`"")
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Python installer failed with exit code $($process.ExitCode). See $Log.python.txt" }
    Remove-Item $installer -Force
    $env:Path = "$target;$target\Scripts;$env:Path"
}

function Find-Edge {
    $paths = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
    )
    return $paths | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Install-Exe($Release, [string]$Target) {
    $asset = $Release.assets | Where-Object { $_.name -eq 'amv-cp-bridge.exe' } | Select-Object -First 1
    if (-not $asset) { throw "Release $($Release.tag_name) has no amv-cp-bridge.exe asset" }
    New-Item -ItemType Directory -Force (Split-Path $Target) | Out-Null
    $temp = "$Target.download"
    Write-Busy "Downloading amv-cp-bridge.exe $($Release.tag_name) ($([math]::Round($asset.size / 1MB, 1)) MB)"
    Invoke-WebRequest $asset.browser_download_url -OutFile $temp -UseBasicParsing
    if ($asset.digest) {
        $expected = $asset.digest -replace '^sha256:', ''
        $actual = (Get-FileHash $temp -Algorithm SHA256).Hash
        if ($actual -ne $expected) {
            Remove-Item $temp -Force
            throw "SHA-256 mismatch for amv-cp-bridge.exe. Expected $expected, received $actual"
        }
    }
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            Move-Item $temp $Target -Force
            return
        } catch {
            if ($attempt -eq 30) { throw "Could not replace $Target. Close amv-cp-bridge and retry. $_" }
            Start-Sleep -Seconds 1
        }
    }
}

function Add-UserPath([string]$Directory) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    try {
        $current = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        if (($current -split ';') -notcontains $Directory) {
            $key.SetValue('Path', (($current.TrimEnd(';'), $Directory) -join ';').TrimStart(';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
        }
    } finally {
        $key.Close()
    }
    [Environment]::SetEnvironmentVariable('AMV_CP_BRIDGE_HOME', (Split-Path $Directory), 'User')
}

function New-DesktopShortcut([string]$Target) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'amv-cp-bridge.lnk'))
    $link.TargetPath = $Target
    $link.WorkingDirectory = Split-Path $Target
    $link.Save()
}

function Invoke-AmvSetup {
    $repo = 'uno-km/amv-cp-bridge'
    $pythonVersion = if ($env:AMV_PY_VERSION) { $env:AMV_PY_VERSION } else { '3.12.10' }
    $root = Join-Path $env:LOCALAPPDATA 'amv-cp-bridge'
    $exePath = if ($env:AMV_EXE_PATH) { $env:AMV_EXE_PATH } else { Join-Path $root 'amv-cp-bridge.exe' }
    $log = Join-Path $root 'setup.log'

    Write-Host '================================================'
    Write-Host ' amv-cp-bridge setup (Windows)'
    Write-Host '================================================'
    New-Item -ItemType Directory -Force $root | Out-Null
    Set-Content -Path $log -Value "Setup started $(Get-Date -Format o)" -Encoding UTF8

    if ($env:AMV_WAIT_PID) {
        Write-Busy "Waiting for running amv-cp-bridge to exit"
        Wait-Process -Id ([int]$env:AMV_WAIT_PID) -Timeout 30 -ErrorAction SilentlyContinue
        Write-Ok 'Previous process closed'
    }

    $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'amv-cp-bridge-setup' }
    Write-Ok "Latest release: $($release.tag_name)"

    $python = Find-Python
    if (-not $python) {
        Install-Python $pythonVersion $log
        $python = Find-Python
        if (-not $python) { throw "Python $pythonVersion was installed but could not be executed" }
    }
    Write-Ok "Python: $((& $python --version) -join '') ($python)"

    $edge = Find-Edge
    if (-not $edge) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Microsoft Edge is not installed and winget is unavailable. Install from https://www.microsoft.com/edge and retry.'
        }
        Write-Busy 'Installing Microsoft Edge'
        Invoke-Native 'winget' @('install', '--id', 'Microsoft.Edge', '--silent', '--accept-package-agreements', '--accept-source-agreements') $log
        $edge = Find-Edge
        if (-not $edge) { throw 'Microsoft Edge installation finished but msedge.exe was not found' }
    }
    Write-Ok "Microsoft Edge: $edge"

    $app = Join-Path $root 'app'
    $archive = Join-Path $root 'source.zip'
    $extract = Join-Path $root 'source.tmp'
    Write-Busy "Downloading source $($release.tag_name)"
    Invoke-WebRequest "https://github.com/$repo/archive/refs/tags/$($release.tag_name).zip" -OutFile $archive -UseBasicParsing
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive $archive $extract -Force
    if (Test-Path $app) { Remove-Item $app -Recurse -Force }
    Move-Item (Get-ChildItem $extract -Directory | Select-Object -First 1).FullName $app
    Remove-Item $extract -Recurse -Force
    Remove-Item $archive -Force
    Write-Ok "Source: $app"
    Write-Ok "Browser extension folder: $(Join-Path $app 'extension')"

    $venv = Join-Path $root 'venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        Write-Busy 'Creating virtual environment'
        Invoke-Native $python @('-m', 'venv', $venv) $log
    }
    Write-Ok "Virtual environment: $venv"

    Write-Busy 'Installing Python packages'
    Invoke-Native $venvPython @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', '--quiet', 'pip', 'setuptools', 'wheel') $log
    Invoke-Native $venvPython @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', '--quiet', '-r', (Join-Path $app 'requirements.txt')) $log
    Write-Ok 'Python packages'

    Invoke-Native $venvPython @('-m', 'pip', 'install', '--upgrade', '--force-reinstall', '--no-deps', '--disable-pip-version-check', '--quiet', $app) $log
    $installed = (& $venvPython -I -c 'import amv_cp_bridge; print(amv_cp_bridge.__version__)' | Select-Object -Last 1).Trim()
    if ("v$installed" -ne $release.tag_name) { throw "Installed package version $installed does not match release $($release.tag_name)" }
    Write-Ok "amv-cp-bridge package: $installed"

    Invoke-Native $venvPython @('-I', '-c', 'from amv_cp_bridge.engine import CopilotEngine; from amv_cp_bridge.telemetry_db import telemetry_db; CopilotEngine()') $log
    Write-Ok "Configuration: $(Join-Path $env:USERPROFILE '.amv_cp_bridge')"

    Install-Exe $release $exePath
    Write-Ok "Application: $exePath"

    if (-not $env:AMV_NO_INTEGRATION) {
        $bin = Join-Path $root 'bin'
        New-Item -ItemType Directory -Force $bin | Out-Null
        Set-Content -Path (Join-Path $bin 'amv-cp-bridge.cmd') -Value "@`"$venvPython`" -m amv_cp_bridge.cli %*" -Encoding ASCII
        Add-UserPath $bin
        Write-Ok "Command: amv-cp-bridge ($bin)"
        New-DesktopShortcut $exePath
        Write-Ok 'Desktop shortcut'
    }

    Write-Host '================================================'
    Write-Ok "Setup complete: amv-cp-bridge $($release.tag_name)"
    Write-Host '================================================'
    Start-Process -FilePath $exePath -WorkingDirectory (Split-Path $exePath)
    Write-Ok 'Application started'
}

try {
    Invoke-AmvSetup
} catch {
    Write-Host "[x] $($_.Exception.Message)" -ForegroundColor Red
    if ($env:AMV_WAIT_PID) { Read-Host 'Update failed. The existing version was kept when possible. Press Enter to close' | Out-Null }
    throw
}
