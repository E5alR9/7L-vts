@echo off
chcp 65001 >nul
title 啟動 6.env Bot...
cd /d "%~dp0"

if not exist bot.py (
    echo [錯誤] 找不到本機 bot.py。
    echo         （已拔除自動從 GitHub 下載覆寫 bot.py 的行為，避免本機修改被洗掉）
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

echo [2/2] 正在使用 6.env 啟動程式...
python -c "from dotenv import load_dotenv; load_dotenv('6.env'); import runpy; runpy.run_path('bot.py', run_name='__main__')"

pause