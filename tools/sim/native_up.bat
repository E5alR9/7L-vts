@echo off
chcp 65001 >nul
:: 用原生終端機開模擬直播（跟 V7.bat 一樣的環境，但走 sim_run.py：截圖入口照樣擋掉、不開麥克風）。
:: 不自動重開：崩了就停在這裡，看 data\crash.log。開好後在 Claude 那邊跑 tools/sim/native_check.sh 確認看不到螢幕。
title 7L 模擬直播（原生終端機）
cd /d "%~dp0..\.."
python tools\sim\sim_run.py
echo.
echo [模擬直播] 7L 已退出，代碼 %errorlevel%（%date% %time%）。崩潰紀錄在 data\crash.log
pause
