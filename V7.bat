@echo off
chcp 65001 >nul

:: 【啟動升級：自動切換至高畫質 Windows Terminal】
where wt >nul 2>&1
if %errorlevel% equ 0 (
    if "%WT_SESSION%"=="" (
        echo [系統] 偵測到傳統小黑窗，正在自動切換至高畫質 Windows Terminal...
        wt -d . "%~f0"
        exit
    )
)

title 7L AI VTuber

:: 統一切到腳本所在資料夾，確保相對路徑（data/ models/ .env）都能命中
cd /d "%~dp0"

echo.
echo =========================================
echo          7L AI VTuber 啟動中...
echo =========================================

:: 🛡️ Watchdog：V7 掃掉就自動重啟（5 秒退避）；建立 STOP_7L.flag 可停止重啟
:RESTART_LOOP
if exist "%~dp0STOP_7L.flag" (
    del "%~dp0STOP_7L.flag"
    echo [Watchdog] 偵測到 STOP_7L.flag，停止重啟。
    pause
    exit /b 0
)
python vts_7L_test.py
echo.
echo [Watchdog] V7 已退出 ^(%date% %time%^)。5 秒後自動重啟；建立 STOP_7L.flag 可阻止。
timeout /t 5 /nobreak >nul
goto RESTART_LOOP