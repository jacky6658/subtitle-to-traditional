@echo off
chcp 65001 >nul
title 字幕轉繁體工具

:: ── Already installed → start main server directly ────────────────────────
if exist "%~dp0.deps_installed" (
  echo 啟動工具中...
  start /b python "%~dp0server.py"
  :wait_main
  timeout /t 1 /nobreak >nul
  curl -s http://127.0.0.1:8765/ >nul 2>&1
  if %errorlevel% neq 0 goto wait_main
  start http://127.0.0.1:8765
  echo 工具已開啟！關閉此視窗即可停止。
  pause
  exit /b 0
)

:: ── First run: ensure Python is available before launching wizard ──────────
echo 檢查 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
  echo 安裝 Python 中（約 1 分鐘）...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  if %errorlevel% neq 0 (
    echo 安裝 Python 失敗，請至 https://www.python.org 手動安裝後重試
    pause & exit /b 1
  )
  set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
)

:: ── Launch visual setup wizard ────────────────────────────────────────────
echo 啟動安裝精靈...
start /b python "%~dp0setup_server.py"

:wait_setup
timeout /t 1 /nobreak >nul
curl -s http://127.0.0.1:8766/ >nul 2>&1
if %errorlevel% neq 0 goto wait_setup

start http://127.0.0.1:8766
echo 安裝精靈已在瀏覽器開啟，請依照畫面指示完成安裝。

:: Wait for install marker
:wait_marker
timeout /t 3 /nobreak >nul
if not exist "%~dp0.deps_installed" goto wait_marker

timeout /t 5 /nobreak >nul
echo 安裝完成！
pause
