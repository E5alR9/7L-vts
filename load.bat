
echo =========================================
echo        7L 系統環境智能快速檢查
echo =========================================

:: 【第一關：檢查 Python 套件 (已包含雙軌高速 Whisper 核心與 Discord 聯網)】
echo [系統] 正在檢測 Python 核心套件...
python -c "import aiohttp, pyvts, edge_tts, pygame, pyautogui, speech_recognition, numpy, soundcard, psutil, dotenv, tavily, pyaudio, google.genai, groq, firebase_admin, PIL, faster_whisper, discord, cv2" >nul 2>&1
if %errorlevel% neq 0 (
    echo [系統] 發現缺少的套件，正在自動下載中...
    pip install aiohttp pyvts edge-tts pygame pyautogui SpeechRecognition numpy soundcard psutil python-dotenv tavily-python PyAudio google-genai groq firebase-admin tzdata Pillow faster-whisper discord.py opencv-python
) else (
    echo [系統] Python 核心套件、雙軌 Whisper 與聯網模組已齊全，光速跳過安裝！
)
