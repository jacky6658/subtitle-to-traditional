$ErrorActionPreference = "Continue"
$dir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$log    = Join-Path $dir "setup.log"
$marker = Join-Path $dir ".deps_installed"

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

function FindPython {
    $candidates = @(
        (Get-Command python  -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Get-Command python3 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) {
            $ver = & $p --version 2>&1
            if ($ver -match "Python 3") { return $p }
        }
    }
    return $null
}

function KillExistingServer {
    $conn = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep 1
        Log "Killed existing server"
    }
}

function WaitForPort($port) {
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep 1
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { return $true }
        } catch {}
    }
    return $false
}

function CreateDesktopShortcut {
    $shortcutPath = "$env:USERPROFILE\Desktop\AIJobvideo.lnk"
    $vbsPath = Join-Path $dir "AIJobvideo.vbs"
    $icoPath = Join-Path $dir "logo.ico"
    if (-not (Test-Path $icoPath)) {
        $py = FindPython
        if ($py) {
            $pngPath = Join-Path $dir "logo.png"
            & $py -c "
try:
    from PIL import Image
    Image.open(r'$pngPath').save(r'$icoPath', format='ICO', sizes=[(256,256),(64,64),(32,32)])
except Exception:
    pass
" 2>$null
        }
    }
    $ws = New-Object -comObject WScript.Shell
    $sc = $ws.CreateShortcut($shortcutPath)
    $sc.TargetPath = "wscript.exe"
    $sc.Arguments = "`"$vbsPath`""
    $sc.WorkingDirectory = $dir
    $sc.Description = "AIJobvideo"
    if (Test-Path $icoPath) { $sc.IconLocation = $icoPath + ",0" }
    $sc.Save()
    Log "Desktop shortcut created"
}

Log "=== Starting AIJobvideo ==="

if (Test-Path $marker) {
    Log "Already installed, starting main server..."
    $python = FindPython
    if (-not $python) {
        Write-Host "Python not found. Please reinstall." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
    KillExistingServer
    Start-Process $python -ArgumentList "`"$(Join-Path $dir 'server.py')`"" -WindowStyle Hidden
    Log "Waiting for server..."
    if (WaitForPort 8765) {
        CreateDesktopShortcut
        Start-Process "http://127.0.0.1:8765"
        Log "Tool opened."
    } else {
        Write-Host "Server failed to start. Check setup.log" -ForegroundColor Red
    }
    Read-Host "Press Enter to close"
    exit 0
}

Log "First run - checking environment..."

$python = FindPython
if (-not $python) {
    Log "Python not found, installing via winget..."
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    $pyDir = "$env:LOCALAPPDATA\Programs\Python\Python312"
    $pyScripts = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
    $env:PATH = "$pyDir;$pyScripts;$env:PATH"
    $python = FindPython
    if (-not $python) {
        Write-Host "Python install failed. Download from https://www.python.org" -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
}
Log "Python: $python"

Log "Starting setup wizard server..."
$setupScript = Join-Path $dir "setup_server.py"
Start-Process $python -ArgumentList "`"$setupScript`"" -WindowStyle Hidden

Log "Waiting for setup wizard..."
if (WaitForPort 8766) {
    Start-Process "http://127.0.0.1:8766"
    Log "Setup wizard opened."
} else {
    Write-Host "Setup wizard failed to start. Check setup.log" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

Log "Waiting for installation to complete..."
while (-not (Test-Path $marker)) {
    Start-Sleep 3
    Write-Host "." -NoNewline
}

Log ""
Log "Installation complete! Starting main server..."
$python2 = FindPython
KillExistingServer
Start-Process $python2 -ArgumentList "`"$(Join-Path $dir 'server.py')`"" -WindowStyle Hidden

Log "Waiting for main server..."
if (WaitForPort 8765) {
    CreateDesktopShortcut
    Start-Process "http://127.0.0.1:8765"
    Log "Tool opened!"
} else {
    Write-Host "Server failed to start. Check setup.log" -ForegroundColor Red
}

Read-Host "Press Enter to close"
