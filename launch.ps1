$ErrorActionPreference = "Continue"
$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$log     = Join-Path $dir "setup.log"
$marker  = Join-Path $dir ".deps_installed"

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
            # Exclude Microsoft Store stub (returns empty on --version)
            $ver = & $p --version 2>&1
            if ($ver -match "Python 3") { return $p }
        }
    }
    return $null
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

Log "=== 字幕轉繁體工具 啟動 ==="

# ── Already installed → start main server ──────────────────────────────────
if (Test-Path $marker) {
    Log "已安裝，啟動主工具..."
    $python = FindPython
    if (-not $python) {
        Write-Host "找不到 Python，請重新執行安裝" -ForegroundColor Red
        Read-Host "按 Enter 關閉"
        exit 1
    }
    Start-Process $python -ArgumentList "`"$(Join-Path $dir 'server.py')`"" -WindowStyle Hidden
    Log "等待主工具啟動..."
    if (WaitForPort 8765) {
        Start-Process "http://127.0.0.1:8765"
        Log "工具已開啟，關閉此視窗即可停止。"
    } else {
        Write-Host "主工具啟動失敗，請查看 setup.log" -ForegroundColor Red
    }
    Read-Host "按 Enter 關閉"
    exit 0
}

# ── First run ───────────────────────────────────────────────────────────────
Log "首次執行，檢查環境..."

# Step 1: Python
$python = FindPython
if (-not $python) {
    Log "Python 未找到，嘗試安裝..."
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    $env:PATH = "$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts;$env:PATH"
    $python = FindPython
    if (-not $python) {
        Write-Host "Python 安裝失敗，請至 https://www.python.org 下載安裝後重試" -ForegroundColor Red
        Read-Host "按 Enter 關閉"
        exit 1
    }
}
Log "Python: $python"

# Step 2: Start setup wizard server
Log "啟動安裝精靈伺服器..."
$setupScript = Join-Path $dir "setup_server.py"
Start-Process $python -ArgumentList "`"$setupScript`"" -WindowStyle Hidden

# Step 3: Wait for wizard server then open browser
Log "等待安裝精靈啟動..."
if (WaitForPort 8766) {
    Start-Process "http://127.0.0.1:8766"
    Log "安裝精靈已在瀏覽器開啟，請依照畫面指示完成安裝。"
} else {
    Write-Host "安裝精靈啟動失敗，請查看 setup.log" -ForegroundColor Red
    Read-Host "按 Enter 關閉"
    exit 1
}

# Step 4: Wait for install to finish
Log "等待安裝完成..."
while (-not (Test-Path $marker)) {
    Start-Sleep 3
    Write-Host "." -NoNewline
}

Log ""
Log "安裝完成！"
Read-Host "按 Enter 關閉"
