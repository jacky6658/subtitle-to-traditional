@echo off
chcp 65001 >nul
title 字幕轉繁體工具
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
pause
