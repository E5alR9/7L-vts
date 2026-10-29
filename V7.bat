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

:: 🛡️ Watchdog：V7 掃掉就自動重啟（5 秒退避）；建立停止旗標（見下面 if exist 那行）可停止重啟
:: 停止旗標的檔名只寫在 if exist／del 這兩行（2026-10-29）：chcp 65001 之後 cmd 讀中文行會錯位，把半行當指令跑；以前 echo 裡寫著檔名，旗標在的時候被當成「打開這個檔」，一直跳出「選取應用程式以開啟」的視窗
:RESTART_LOOP
if exist "%~dp0STOP_7L.flag" (
    del "%~dp0STOP_7L.flag"
    echo [Watchdog] 偵測到停止旗標，停止重啟。
    pause
    exit /b 0
)
python vts_7L_test.py
echo.
echo [Watchdog] V7 已退出 ^(%date% %time%^)。5 秒後自動重啟；建立停止旗標可阻止。
timeout /t 5 /nobreak >nul
goto RESTART_LOOP