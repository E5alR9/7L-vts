@echo off
chcp 65001 >nul
title 7L VM Dedicated Agent Server
echo ======================================================
echo    🤖 7L VM Dedicated Agent Server 正在啟動...
echo ======================================================
cd /d "%~dp0"
python server.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [❌ 錯誤] 伺服器異常終止。
    pause
)
