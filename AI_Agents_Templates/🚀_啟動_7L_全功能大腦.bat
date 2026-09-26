@echo off
chcp 65001 > nul
title 🌟 7L 全功能智慧一體化核心系統 (VM 獨立專屬主機版)

echo ╔═══════════════════════════════════════════════════════════════╗
echo   🌸 7L 全功能智慧一體化核心系統 (VM 獨立專屬主機版)
echo   🎙️ 音訊模式: [Hyper-V 本機麥克風直連] + [Discord 語音頻道]
echo   👁️ 形象模式: [虛擬機桌面陪伴] + [NDI 局域網透明投影]
echo   🧠 旗艦大腦: Google Gemini (3.7 / 3.6 / 3.1 Pro / 3.5)
echo ╚═══════════════════════════════════════════════════════════════╝
echo.

cd /d C:\AI_Agents

REM 1. 檢查 VTube Studio 是否已啟動
tasklist /FI "IMAGENAME eq VTube Studio.exe" 2>NUL | find /I /N "VTube Studio.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] VTube Studio 已在運行中。
) else (
    echo [..] 正在自動啟動 VTube Studio...
    if exist "C:\Program Files (x86)\Steam\steamapps\common\VTube Studio\VTube Studio.exe" (
        start "" "C:\Program Files (x86)\Steam\steamapps\common\VTube Studio\VTube Studio.exe"
    ) else (
        echo [提示] 請確認 VTube Studio 安裝路徑。
    )
)

echo.
echo [🚀] 正在啟動 7L AI-VTuber 智慧一體化主程式...
echo ─────────────────────────────────────────────────────────────
python vts_7L_test.py

pause
