@echo off
chcp 65001 >nul
title 7L Discord Bot 啟動中...
cd /d "%~dp0"

if not exist 7L.py (
    echo [錯誤] 找不到本機 7L.py，請確認檔案存在。
    echo         （已拔除自動從 GitHub 下載覆寫的行為，避免本機修改被洗掉）
    pause
    exit /b 1
)

if not exist .deps_ok (
    if exist requirements.txt (
        echo [1/2] 首次啟動：安裝本機 requirements.txt 依賴...
        python -m pip install -r requirements.txt
        if not errorlevel 1 echo done> .deps_ok
    ) else (
        echo [1/2] 找不到 requirements.txt，跳過依賴安裝。
        echo done> .deps_ok
    )
) else (
    echo [1/2] 依賴已就緒（如需重新安裝請刪除專案中的 .deps_ok 檔案）。
)

:run_loop
echo [2/2] 正在啟動 7L.py 機器人...
python 7L.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 【⚠️ 提示】機器人連線中斷或 Discord 官方伺服器暫時異常 (500/503)！
    echo 【🔄 自動重試】將在 10 秒後自動嘗試重新連線... (若要退出請按 Ctrl + C)
    timeout /t 10
    goto run_loop
)
pause