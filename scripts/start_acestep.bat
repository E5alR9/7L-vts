@echo off
chcp 65001 >nul
title ACE-Step 1.5 作曲服務（7L 用，埠 7865）
:: 7L 的 AI 作曲（music.generate_song）要先開這個。官方 REST API，埠改 7865（預設 8001 跟 VTube Studio 撞）。
:: 第一次跑會裝套件（PyTorch 等，約 5～10 GB）；第一次作曲會再下載模型（約 6 GB），之後就快。
:: 顯卡 12GB 要跟 7L 搶：模型等到第一次作曲才載、放 CPU 記憶體輪流上顯卡（ACESTEP_NO_INIT／OFFLOAD）。
set ACE_DIR=%USERPROFILE%\ACE-Step-1.5
if not exist "%ACE_DIR%" git clone https://github.com/ACE-Step/ACE-Step-1.5.git "%ACE_DIR%"
cd /d "%ACE_DIR%"
if not exist .venv (
    echo [ACE-Step] 第一次安裝套件，要幾分鐘到半小時...
    uv sync
)
set ACESTEP_API_HOST=127.0.0.1
set ACESTEP_API_PORT=7865
set ACESTEP_CONFIG_PATH=acestep-v15-turbo
set ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B
set ACESTEP_INIT_LLM=auto
set ACESTEP_NO_INIT=true
set ACESTEP_OFFLOAD_TO_CPU=true
uv run acestep-api
echo.
echo [ACE-Step] 服務已停止
pause
