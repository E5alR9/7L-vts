# ==============================================================================
# 🌟 7L AI-VTuber 智慧一體化核心系統 (vts_7L_test.py)
# 👑 作者: E5alR9 & 7L 開發團隊
# 🎯 整合: Live2D / VTube Studio、Google GenAI Function Calling、沙盒遊樂場、
#         雙向雲端長短期記憶、環境聲音/眼角餘光感知、Discord 機器人監控
# ==============================================================================

import os
import sys
import subprocess
import re
import asyncio
import aiohttp
import pyvts
import edge_tts
import pygame
import time
import json
import base64
import datetime
import pyautogui
import speech_recognition as sr
import math
import random
import wave
import socket
import numpy as np
import soundcard as sc
import psutil
import glob
import difflib
from typing import Optional, Dict, List, Tuple, Any
import shutil
import webbrowser
import platform
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from tavily import TavilyClient
import ctypes
try:
    import msvcrt
except ImportError:
    msvcrt = None

# 🔇 靜音 Soundcard 與底層音訊資料中斷警告，保持控制台狀態列純淨
warnings.filterwarnings("ignore", message=".*data discontinuity in recording.*")
try:
    if hasattr(sc, "SoundcardRuntimeWarning"):
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
except Exception:
    pass

# 🌟 設定 Windows 控制台為 UTF-8 代碼頁 (CP 65001) 並開啟 ANSI 虛擬終端處理，徹底修復中文字元重複、動態刷新與換行殘影
if sys.platform == "win32":
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
        # 啟用 ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) 支援原生 ANSI 擦除
        kernel32 = ctypes.windll.kernel32
        hStdOut = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode)):
            kernel32.SetConsoleMode(hStdOut, mode.value | 0x0004 | 0x0002)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

import unicodedata

def get_char_width(ch: str) -> int:
    ea = unicodedata.east_asian_width(ch)
    if ea in ('F', 'W'):
        return 2
    code = ord(ch)
    if 0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF:
        return 2
    return 1

def get_display_width(text: str) -> int:
    return sum(get_char_width(ch) for ch in text)

def fit_text_to_width(text: str, max_cols: int) -> str:
    """精準將字串截斷至指定終端機欄位寬度以內，並避免換行溢出"""
    if max_cols <= 3:
        return text[:max_cols]
    total_w = get_display_width(text)
    if total_w <= max_cols:
        return text
    
    target_w = max_cols - 2
    cur_w = 0
    res = []
    for ch in text:
        w = get_char_width(ch)
        if cur_w + w > target_w:
            break
        res.append(ch)
        cur_w += w
    return "".join(res) + ".."

def log_print(msg: str):
    """清除動態狀態列並乾淨輸出單行日誌，避免任何換行溢出或殘留空格"""
    term_cols = shutil.get_terminal_size((80, 20)).columns
    blank = " " * max(1, min(term_cols - 1, 79))
    print(f"\r\033[2K\r{blank}\r{msg}", flush=True)

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

# 導入 Google 官方 GenAI SDK (主力視覺與大腦)
from google import genai
from google.genai import types

# ────────────────────────────────────────────────────────
# 🔐 1. 環境變數載入與金鑰矩陣初始化
# ────────────────────────────────────────────────────────
load_dotenv()
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # 關閉 Hugging Face 符號連結警告

print("=== 🔍 .env 金鑰讀取測試 ===")

GROQ_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or "") if k.strip()]
print(f"✅ 找到 {len(GROQ_KEYS)} 把 Groq 金鑰")

GEMINI_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]
print(f"✅ 找到 {len(GEMINI_KEYS)} 把 Gemini 金鑰")

TAVILY_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("TAVILY_KEYS") or os.getenv("TAVILY_API_KEYS") or os.getenv("TAVILY_API_KEY") or "") if k.strip()]
print(f"✅ 找到 {len(TAVILY_KEYS)} 把 Tavily 金鑰")

FIREBASE_CRED_JSON = os.getenv("FIREBASE_CRED_JSON")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN_7L")

print("===========================\n")

GROQ_CLIENTS = []
try:
    from groq import AsyncGroq
    for key in GROQ_KEYS:
        if key: GROQ_CLIENTS.append(AsyncGroq(api_key=key))
except ImportError:
    pass

tavily_client = TavilyClient(api_key=TAVILY_KEYS[0]) if TAVILY_KEYS else None

# ────────────────────────────────────────────────────────
# 🧠 2. 模型清單與大腦池定義
# ────────────────────────────────────────────────────────

# 🌟 視覺與一體化主力：Gemini 矩陣 (與 Google 伺服器清單 100% 完整對齊)
GEMINI_MODELS = [
    # 👑 頂級旗艦大腦 (超高智商 & 視覺一體化 & 工具調用)
    "gemini-3.7-flash",                    # 👑 第一名：最新頂配旗艦大腦
    "gemini-3.6-flash",                    # 🥈 第二名：次世代強效
    "gemini-3.5-flash",                    # 🥉 第三名：高智商均衡主力
    "gemini-3-flash-preview",              # ⚡ 閃電推理預覽
    "gemini-3.1-pro-preview",              # 🧠 超高智商 Pro 預覽
    "gemini-3.1-pro-preview-customtools",  # 🛠️ Pro 自訂工具專用版
    "gemini-flash-latest",                 # 🚀 動態最新 Flash 指針
    "gemini-pro-latest",                   # 🚀 動態最新 Pro 指針
    
    # 🛡️ 輕量保底矩陣 (超大額度安全網、毫秒級響應)
    "gemini-3.5-flash-lite",               # 🛡️ 超大額度保底
    "gemini-3.1-flash-lite",               # 🛡️ 輕量快速版
    "gemini-3.1-flash-lite-preview",       # 🛡️ 輕量預覽版
    "gemini-flash-lite-latest",            # 🛡️ 動態最新 Lite 指針
    
    # 🤖 空間視力、電腦認知與全模態專用
    "gemini-omni-flash-preview",           # 🌐 全模態理解預覽
    "gemini-robotics-er-2-preview",        # 🤖 空間視力 1 號
    "gemini-robotics-er-1.6-preview",      # 🤖 空間視力 2 號
    "gemini-2.5-computer-use-preview-10-2025" # 🖥️ 電腦操作與螢幕認知
]

# 🌟 純文字對話模型池 (常規對話)
NORMAL_TEXT_MODELS = [
    {"provider": "groq", "model": "openai/gpt-oss-120b"},
    {"provider": "groq", "model": "qwen/qwen3.6-27b"},
    {"provider": "groq", "model": "groq/compound"},
    {"provider": "groq", "model": "openai/gpt-oss-20b"},
    {"provider": "google", "model": "gemma-4-31b-it"},         
    {"provider": "google", "model": "gemma-4-26b-a4b-it"}
]

# 🌟 純文字對話模型池 (自主發話)
PROACTIVE_TEXT_MODELS = [
    {"provider": "groq", "model": "qwen/qwen3.6-27b"},
    {"provider": "groq", "model": "openai/gpt-oss-120b"},
    {"provider": "groq", "model": "groq/compound"},
    {"provider": "groq", "model": "openai/gpt-oss-20b"},
    {"provider": "google", "model": "gemma-4-31b-it"},
    {"provider": "google", "model": "gemma-4-26b-a4b-it"}
]

DEAD_GEMINI_MODELS = set()
API_LOCKS_FILE = "api_locks_cache.json"
API_LOCKS = {}

# ────────────────────────────────────────────────────────
# 🚦 3. API 頻率限制、冷卻與鎖定管理系統
# ────────────────────────────────────────────────────────

def load_api_locks():
    global API_LOCKS
    if os.path.exists(API_LOCKS_FILE):
        try:
            with open(API_LOCKS_FILE, "r", encoding="utf-8") as f:
                locks = json.load(f)
            now = time.time()
            API_LOCKS = {k: v for k, v in locks.items() if v > now}
        except Exception:
            API_LOCKS = {}

def save_api_locks():
    try:
        with open(API_LOCKS_FILE, "w", encoding="utf-8") as f:
            json.dump(API_LOCKS, f)
    except Exception:
        pass

load_api_locks()

def get_seconds_until_pt_midnight() -> float:
    """計算從現在到美國太平洋時間 (PT) 下一個午夜 00:00 還剩多少秒"""
    try:
        pt_zone = ZoneInfo("America/Los_Angeles")
        now_pt = datetime.now(pt_zone)
        tomorrow_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        diff = (tomorrow_pt - now_pt).total_seconds()
        return max(60.0, diff)
    except Exception:
        return 86400.0

def parse_cooldown_seconds(error_text: str, headers=None) -> float:
    if headers:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try: return max(15.0, float(retry_after) + 5.0)
            except ValueError: pass

    total_seconds = 60.0 
    if not error_text: return total_seconds
        
    error_lower = error_text.lower()

    # 1. 優先精準捕獲 Google GenAI / Groq API 返回的重試秒數或時間字串 (如 "retry in 53.5s", "retryDelay: '53s'")
    match_retry_in = re.search(r'retry (?:in|after|delay)[:\s\']*([0-9.]+)\s*s', error_lower)
    if match_retry_in:
        try: return max(10.0, float(match_retry_in.group(1)) + 5.0)
        except ValueError: pass

    match_hms = re.search(r'(?:try again in|retry in|wait)\s+(?:(\d+)h)?(?:(\d+)m)?([0-9.]+)s', error_lower)
    if match_hms:
        hours = int(match_hms.group(1)) if match_hms.group(1) else 0
        minutes = int(match_hms.group(2)) if match_hms.group(2) else 0
        seconds = float(match_hms.group(3)) if match_hms.group(3) else 0.0
        return max(10.0, hours * 3600 + minutes * 60 + seconds + 5.0) 
        
    match_sec = re.search(r'(?:retry-after|wait|in|please wait)\s+([0-9.]+)\s*(?:s|sec|second|seconds)?', error_lower)
    if match_sec:
        try: return max(10.0, float(match_sec.group(1)) + 5.0)
        except ValueError: pass

    # 2. 404 或未開通 / 下架模型，鎖定至 PT 午夜 (並永久記錄至 DEAD_GEMINI_MODELS)
    if "404" in error_lower or "not_found" in error_lower or "no longer available" in error_lower:
        return get_seconds_until_pt_midnight()

    # 3. 每日總配額耗盡 (Per Day / Daily / RequestsPerDay / RPD) 封印至 PT 午夜 (隔天重置)
    is_daily_exhausted = any(k in error_lower for k in ["per day", "requests per day", "daily requests", "rpd", "tokens per day", "tpd"]) and not any(k in error_lower for k in ["per minute", "minute", "rpm", "tpm"])
    if is_daily_exhausted:
        return get_seconds_until_pt_midnight()

    # 4. 503 暫時性伺服器超載 (鎖定 3 分鐘 / 180 秒)
    if "503" in error_lower or "unavailable" in error_lower or "high demand" in error_lower:
        return 180.0

    # 5. 429 瞬間速率超速 / 頻率限制 (預設短暫冷卻 60 秒)
    if "429" in error_lower or "rate limit" in error_lower or "resource" in error_lower or "quota" in error_lower:
        return 60.0  

    return max(30.0, total_seconds)

def is_locked(target_id):
    if target_id in API_LOCKS:
        if time.time() < API_LOCKS[target_id]:
            return True
        else:
            del API_LOCKS[target_id] 
            save_api_locks()
    return False

def lock_target(target_id, error_msg="", headers=None):
    global current_ai_status_str
    duration = parse_cooldown_seconds(error_msg, headers)
    API_LOCKS[target_id] = time.time() + duration
    save_api_locks()
    
    if duration >= 3600: dur_str = f"{duration/3600:.1f}h"
    elif duration >= 60: dur_str = f"{duration/60:.1f}m"
    else: dur_str = f"{int(duration)}s"
        
    current_ai_status_str = f"🛑封印: {target_id} ({dur_str})"
    sys_notify(f"🛑 封印通道 {target_id} ({dur_str})", duration=3.0)

MODEL_FAIL_COUNT = {}

def is_model_locked(model_name: str) -> bool:
    short_m = model_name.replace("gemini-", "").replace("openai/", "").replace("llama-", "").replace("gemma-", "")
    model_lock_id = f"MODEL_{short_m}"
    return is_locked(model_lock_id)

def lock_entire_model(model_name: str, duration: float = 60.0, reason: str = "伺服器超載"):
    short_m = model_name.replace("gemini-", "").replace("openai/", "").replace("llama-", "").replace("gemma-", "")
    model_lock_id = f"MODEL_{short_m}"
    API_LOCKS[model_lock_id] = time.time() + duration
    save_api_locks()
    dur_str = f"{int(duration)}s" if duration < 60 else (f"{duration/60:.1f}m" if duration < 3600 else f"{duration/3600:.1f}h")
    log_print(f"⚡ [大腦極速熔斷] 模型 [{model_name}] 遇 {reason} ➔ 暫停此模型 {dur_str}，秒切下一個備用模型！")

def record_model_failure(model_name: str, err_str: str):
    global MODEL_FAIL_COUNT
    MODEL_FAIL_COUNT[model_name] = MODEL_FAIL_COUNT.get(model_name, 0) + 1
    # 🌟 換模型門檻：改為 API 金鑰總數的 2/3（隨機打亂抽取），抽滿 2/3 都失敗才切換模型
    num_keys = len(GEMINI_KEYS)
    threshold = max(3, int(math.ceil(num_keys * 2.0 / 3.0))) if num_keys > 0 else 4
    if MODEL_FAIL_COUNT[model_name] >= threshold:
        if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
            reason = f"隨機抽滿 2/3 金鑰池 ({threshold}把) 均遇 503 伺服器超載"
            m_duration = 180.0  # 503 模型級熔斷 3 分鐘
        elif "429" in err_str or "rate limit" in err_str:
            reason = f"隨機抽滿 2/3 金鑰池 ({threshold}把) 均遇 429 頻率上限"
            m_duration = 60.0
        else:
            reason = f"隨機抽滿 2/3 金鑰池 ({threshold}把) 均異常"
            m_duration = 60.0
        lock_entire_model(model_name, duration=m_duration, reason=reason)
        MODEL_FAIL_COUNT[model_name] = 0

# 🛑 自主發話時主動保留/跳過的頂配旗艦大腦清單（保留給老爸主動對話使用）
PROACTIVE_EXCLUDED_MODELS = {
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools"
}

def get_prioritized_gemini_models(user_query: str = "", has_image: bool = False, is_proactive: bool = False) -> list:
    """根據老爸當前的對話指令與多模態情境，動態計算專屬的模型優先級排程佇列"""
    q = (user_query or "").lower()
    
    # 1. 🖥️ 電腦桌面 GUI、按鈕、視窗、程式碼分析 ➔ 優先派發給 Computer-Use 專用模型
    is_computer_ui = any(k in q for k in ["按鈕", "介面", "視窗", "桌面", "瀏覽器", "程式碼", "code", "點哪", "工作列", "分頁", "螢幕上寫什麼", "ui", "軟體", "點擊", "找一下"])
    
    # 2. 🤖 空間幾何、方位判斷、相對距離 ➔ 優先派發給 Robotics 空間視力專用模型
    is_spatial = any(k in q for k in ["空間", "方位", "距離", "方向", "哪一邊", "左邊還是右邊", "多遠", "座標", "位置在哪", "指著哪", "角度"])
    
    # 3. 🌐 多模態圖像全景觀察 ➔ 優先派發給 Omni 全模態模型
    is_omni = has_image and any(k in q for k in ["看這張", "看圖", "照片", "插畫", "桌布", "視覺", "顏色", "畫面上"])
    
    priority_heads = []
    if is_computer_ui:
        priority_heads = ["gemini-2.5-computer-use-preview-10-2025", "gemini-omni-flash-preview"]
    elif is_spatial:
        priority_heads = ["gemini-robotics-er-2-preview", "gemini-robotics-er-1.6-preview"]
    elif is_omni:
        priority_heads = ["gemini-omni-flash-preview"]
        
    ordered = []
    for m in priority_heads:
        if m in GEMINI_MODELS and m not in ordered and m not in DEAD_GEMINI_MODELS:
            ordered.append(m)
            
    for m in GEMINI_MODELS:
        if m not in ordered and m not in DEAD_GEMINI_MODELS:
            ordered.append(m)
            
    if is_proactive:
        ordered = [m for m in ordered if m not in PROACTIVE_EXCLUDED_MODELS]
        
    return ordered

CURRENT_GEMINI_KEY_INDEX = 0
CURRENT_TEXT_KEY_INDEX = 0

def get_available_gemini_channels(limit=1, user_query="", has_image=False, is_proactive=False):
    global CURRENT_GEMINI_KEY_INDEX
    available = []
    num_keys = len(GEMINI_KEYS)
    if num_keys == 0: return available
    
    # 🌟 智能任務定向分流：根據老爸需求動態取得排定好的模型隊列
    target_models = get_prioritized_gemini_models(user_query=user_query, has_image=has_image, is_proactive=is_proactive)
    
    for g_model in target_models:
        if g_model in DEAD_GEMINI_MODELS:
            continue
            
        # 🌟 若該模型被極速熔斷 (例如 503 超載或抽滿 2/3 金鑰皆失敗)，跳過此模型，秒切下一個模型！
        if is_model_locked(g_model):
            continue
            
        short_m = g_model.replace("gemini-", "")
        
        # 🔄 輪詢循環指針 (Round-Robin Ring Buffer)：
        # 從 CURRENT_GEMINI_KEY_INDEX 開始循環掃描，每次成功自動推進至「下一把金鑰」，完美均勻分攤 20 把金鑰的 RPM！
        ring_indices = [(CURRENT_GEMINI_KEY_INDEX + i) % num_keys for i in range(num_keys)]
        unlocked_indices = [idx for idx in ring_indices if not is_locked(f"G{idx}_{short_m}")]
        if not unlocked_indices:
            continue
            
        for idx in unlocked_indices:
            g_key = GEMINI_KEYS[idx]
            target_id = f"G{idx}_{short_m}"
            available.append((g_key, g_model, target_id))
            if len(available) >= limit:
                return available
    return available

def get_available_text_pools(limit=1, is_proactive=False):
    global CURRENT_TEXT_KEY_INDEX
    available = []
    target_list = PROACTIVE_TEXT_MODELS if is_proactive else NORMAL_TEXT_MODELS
    
    for config in target_list:
        provider = config["provider"]
        g_model = config["model"]
        
        # 🌟 若該純文字模型被熔斷，直接跳過！
        if is_model_locked(g_model):
            continue
            
        keys_list = GROQ_CLIENTS if provider == "groq" else GEMINI_KEYS
        num_keys = len(keys_list)
        if num_keys == 0: continue
        
        if "120b" in g_model: short_m = "120b"
        elif "qwen" in g_model.lower() or "27b" in g_model: short_m = "qwen"
        elif "compound" in g_model: short_m = "cpd"
        elif "20b" in g_model: short_m = "20b"
        elif "31b" in g_model: short_m = "31b"
        elif "26b" in g_model: short_m = "26b"
        else: short_m = "txt"
        
        prefix = "GR" if provider == "groq" else "GO"
        
        # 🔄 輪詢循環指針 (Round-Robin Ring Buffer)
        ring_indices = [(CURRENT_TEXT_KEY_INDEX + i) % num_keys for i in range(num_keys)]
        unlocked_indices = [idx for idx in ring_indices if not is_locked(f"{prefix}{idx}_{short_m}")]
        if not unlocked_indices:
            continue
            
        for idx in unlocked_indices:
            pool_id = f"{prefix}{idx}_{short_m}"
            pool_data = {"provider": provider, "model": g_model, "core": keys_list[idx]}
            available.append((pool_data, pool_id))
            if len(available) >= limit:
                return available
    return available

# ────────────────────────────────────────────────────────
# 🖥️ 4. 全域狀態變數、硬體偵測與通知設定
# ────────────────────────────────────────────────────────

def get_screen_resolution():
    """動態檢測 Windows 實體螢幕解析度 (支援 DPI 感知與多螢幕)"""
    try:
        user32 = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        w = user32.GetSystemMetrics(0) # SM_CXSCREEN
        h = user32.GetSystemMetrics(1) # SM_CYSCREEN
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080

try:
    cpu_info = platform.processor()
    ram_info = f"{round(psutil.virtual_memory().total / (1024**3))}GB"
    gpu_info = "獨立顯示卡"
    try:
        ps_out = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command', '(Get-CimInstance Win32_VideoController).Name'],
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
        if ps_out:
            gpu_info = ps_out.splitlines()[0].strip()
    except Exception:
        try:
            gpu_output = subprocess.check_output("wmic path win32_VideoController get name", shell=True, text=True, stderr=subprocess.DEVNULL)
            gpu_info = gpu_output.split('\n')[1].strip()
        except Exception:
            pass
    cur_scr_w, cur_scr_h = get_screen_resolution()
    system_specs = f"螢幕解析度: {cur_scr_w}x{cur_scr_h} / CPU: {cpu_info} / GPU: {gpu_info} / RAM: {ram_info}"
except Exception:
    cur_scr_w, cur_scr_h = get_screen_resolution()
    system_specs = f"螢幕解析度: {cur_scr_w}x{cur_scr_h} / 高階硬體設備"

USER_NAME = "E5alR9"
DEFAULT_USER_TITLE = "E5"
DEFAULT_CHANNEL_ID = "vts_local_user"

IS_STREAMING = False
current_ai_state = "IDLE"  # IDLE / THINKING / TALKING
last_interaction_time = time.time()
latest_screen_cache = None
current_voice_task = None
last_spoken_text = ""

target_look_x = 0.0
target_look_y = 0.0
current_look_x = 0.0
current_look_y = 0.0
is_tracking_mouse = False
force_blink_trigger = 0
IS_MIC_ENABLED = True

current_mic_volume_str = "[🟢 麥克風就緒]"
current_ai_status_str = "正常運作中"
current_mic_action_str = "待命"
current_model_tag = "🧠 初始化中"
current_screen_context = "目前沒有特別的畫面動態。"
current_system_audio_context = "目前沒有播放特別的聲音。"

current_system_notification = ""
notification_expire_time = 0.0
active_timers = set()
vts_lock = asyncio.Lock()
speech_queue = asyncio.Queue()  
pygame.mixer.init()

def sys_notify(msg, duration=4.0):
    global current_system_notification, notification_expire_time
    clean_msg = str(msg).replace('\n', ' ').replace('\r', ' ')
    current_system_notification = clean_msg
    add_time = max(3.0, min(8.0, len(clean_msg) * 0.15))
    notification_expire_time = time.time() + add_time

def get_current_time_string():
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]} {now.strftime('%H:%M')}"

def is_system_overloaded():
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        if cpu > 60.0 or mem > 60.0:
            return True
    except Exception:
        pass
    return False

# ────────────────────────────────────────────────────────
# 💾 5. Firebase Firestore 雲端永久記憶與日記中樞
# ────────────────────────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import credentials, firestore_async
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False

db = None
if HAS_FIREBASE and FIREBASE_CRED_JSON:
    try:
        cred_dict = json.loads(FIREBASE_CRED_JSON)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore_async.client()
        print("【💾 系統通知】Firebase Firestore 雲端永久大腦就緒（三層防線啟動）！")
    except Exception as e:
        print(f"【⚠️ 系統警告】Firebase 連線失敗: {e}，將僅使用本地快取。")
else:
    print("【⚠️ 系統警告】未設定 FIREBASE_CRED_JSON 或未安裝套件，僅使用本地快取模式。")

async def get_user_profile():
    profile = None
    if db is not None:
        try:
            doc = await db.collection("user_memory").document(DEFAULT_CHANNEL_ID).get()
            if doc.exists: profile = doc.to_dict()
        except Exception: pass
        
    if not profile:
        file_path = "user_profile_local.json"
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f: profile = json.load(f)
            except Exception: pass
            
    return profile if profile else {"custom_name": DEFAULT_USER_TITLE, "impression": ""}

async def save_user_profile(custom_name=None, impression=None):
    profile = await get_user_profile()
    if custom_name: profile["custom_name"] = custom_name
    if impression: profile["impression"] = impression
    
    if db is not None:
        try:
            await db.collection("user_memory").document(DEFAULT_CHANNEL_ID).set(profile, merge=True)
        except Exception: pass
        
    try:
        with open("user_profile_local.json", "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except Exception: pass

async def fetch_from_long_term_memory(channel_id, current_user_msg=""):
    history = []
    if db is not None:
        try:
            meta_ref = db.collection("channel_meta").document(str(channel_id))
            meta_doc = await meta_ref.get()
            if meta_doc.exists:
                summary_tags = meta_doc.to_dict().get("summary_tags", "").strip()
                if summary_tags: history.append({"role": "system", "content": f"【潛意識核心記憶標籤】：{summary_tags}"})

            doc_ref = db.collection("channel_history").document(str(channel_id))
            doc = await doc_ref.get()
            if doc.exists:
                history.extend(doc.to_dict().get("history", []))
        except Exception: pass
        
    if not history:
        file_path = f"memory_{channel_id}.json"
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f: history = json.load(f)
            except Exception: pass
    return history

def extract_text_from_content(content):
    if isinstance(content, str): return content
    if isinstance(content, list): return " ".join([p.get("text", "") for p in content if p.get("type") == "text"])
    return ""

async def get_embedding_vector(text):
    """呼叫 Gemini Embedding 2 將文字轉換為潛意識數字陣列"""
    if not GEMINI_KEYS: return None
    try:
        g_key = random.choice(GEMINI_KEYS)
        temp_google_client = genai.Client(api_key=g_key)
        response = await temp_google_client.aio.models.embed_content(
            model="gemini-embedding-2", 
            contents=text
        )
        return response.embeddings[0].values
    except Exception:
        try:
            temp_google_client = genai.Client(api_key=random.choice(GEMINI_KEYS))
            response = await temp_google_client.aio.models.embed_content(
                model="gemini-embedding-001", 
                contents=text
            )
            return response.embeddings[0].values
        except Exception as e:
            print(f"\n⚠️ [潛意識轉換失敗]: {e}")
            return None

async def update_daily_diary(channel_id, recent_chat):
    tz = ZoneInfo("Asia/Taipei")
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    chat_text = "\n".join([f"{msg['role']}: {extract_text_from_content(msg['content'])}" for msg in recent_chat if extract_text_from_content(msg['content']).strip()])
    
    if len(chat_text.strip()) < 40: return
    
    existing_summary = ""
    if db is not None:
        try:
            doc = await db.collection("daily_diary").document(today_str).get()
            if doc.exists: existing_summary = doc.to_dict().get("summary", "")
        except Exception: pass
        
    diary_prompt = (
        f"【後台任務：每日核心日記整合與高強度去重】\n"
        f"妳是 7L 的日記記憶中樞。請將『舊日記摘要』與『新對話』融合成一份完全去重、精簡濃縮後的今日日記。\n\n"
        f"⚠️ 核心守則：\n"
        f"1. 刪除重複部分，保留重點。\n"
        f"2. 總句數嚴格限制在 3 句以內。\n"
        f"3. 絕對不要有任何前言或結尾，直接輸出整合後的日記內容。\n\n"
        f"📖 [舊日記摘要]：\n{existing_summary if existing_summary else '(無)'}\n\n"
        f"💬 [新對話紀錄]：\n{chat_text}\n"
    )
    
    messages = [{"role": "user", "content": diary_prompt}]
    updated_summary = await fetch_ai_response(messages, is_proactive=True)
    
    if updated_summary and "沉默" not in updated_summary:
        log_print("🧠 [潛意識系統] 正在將今日記憶編碼上傳雲端...")
        vector_data = await get_embedding_vector(updated_summary.strip())
        
        diary_payload = {
            "summary": updated_summary.strip(), 
            "date": today_str
        }
        if vector_data:
            diary_payload["embedding_vector"] = vector_data
            
        if db is not None:
            try:
                await db.collection("daily_diary").document(today_str).set(diary_payload, merge=True)
            except Exception: pass
            
        try:
            with open(f"diary_{today_str}.json", "w", encoding="utf-8") as f:
                json.dump(diary_payload, f, ensure_ascii=False, indent=2)
        except Exception: pass

async def save_to_long_term_memory(channel_id, history):
    raw_history_limit = 15
    clean_history = [msg for msg in history if not (msg.get("role") == "system" and ("【" in msg.get("content", "")))]
    if len(clean_history) > raw_history_limit: clean_history = clean_history[-raw_history_limit:]
        
    if db is not None:
        try:
            await db.collection("channel_history").document(str(channel_id)).set({"history": clean_history, "last_updated": time.time()}, merge=True)
            async def generate_and_save_tags(cid, recent_chat):
                try:
                    chat_text = "\n".join([f"{msg['role']}: {extract_text_from_content(msg['content'])}" for msg in recent_chat if extract_text_from_content(msg['content']).strip()])
                    if len(chat_text.strip()) < 20: return
                    summary_prompt = f"【後台任務】請將以下的對話紀錄總結成 1~3 個核心記憶標籤。只回傳標籤：\n{chat_text}"
                    summary_tags = await fetch_ai_response([{"role": "user", "content": summary_prompt}], is_proactive=True)
                    if summary_tags and "沉默" not in summary_tags:
                        await db.collection("channel_meta").document(str(cid)).set({"summary_tags": summary_tags.strip()}, merge=True)
                except Exception: pass
            asyncio.create_task(generate_and_save_tags(channel_id, clean_history))
        except Exception: pass

    asyncio.create_task(update_daily_diary(channel_id, clean_history))
    
    file_path = f"memory_{channel_id}.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(clean_history, f, ensure_ascii=False, indent=2)
    except Exception: pass

# ────────────────────────────────────────────────────────
# 🎭 6. Live2D / VTube Studio 表情與姿態控制 & 雙軌空間走位系統 (Spatial Movement)
# ────────────────────────────────────────────────────────
GLOBAL_VTS = None
MY_CONTROLLED_EXPS = ["黑脸.exp3.json", "爱心.exp3.json", "星星眼.exp3.json", "红脸.exp3.json"]
CURRENT_ACTIVE_EXP = None

VTS_EXPRESSION_MAP = {
    "愛心": "爱心.exp3.json",      
    "星星": "星星眼.exp3.json",    
    "星星眼": "星星眼.exp3.json",
    "臉紅": "红脸.exp3.json",      
    "臉红": "红脸.exp3.json",
    "生氣": "黑脸.exp3.json",
    "黑臉": "黑脸.exp3.json",
    "尷尬": "红脸.exp3.json"
}

CURRENT_SPATIAL_LOCATION = "center"
IS_AUTO_WANDER_ENABLED = True
LAST_WANDER_TIME = time.time()

BASE_VTS_MODEL_X = 0.65
BASE_VTS_MODEL_Y = -1.28
BASE_VTS_MODEL_SIZE = -54.8
CURRENT_VTS_MODEL_X = None
CURRENT_VTS_MODEL_Y = None
CURRENT_VTS_MODEL_SIZE = None

async def fetch_vts_base_model_pos(vts=None):
    """主動從 VTube Studio 讀取並記錄老爸自訂之模型大小與座標基準（保證半身構圖與比例永不失真）"""
    global BASE_VTS_MODEL_X, BASE_VTS_MODEL_Y, BASE_VTS_MODEL_SIZE, CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE, GLOBAL_VTS
    target_vts = vts or GLOBAL_VTS
    if not target_vts:
        return
    try:
        async with vts_lock:
            resp = await asyncio.wait_for(target_vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "GetModelInfoReq",
                "messageType": "CurrentModelRequest"
            }), timeout=1.5)
        pos = resp.get("data", {}).get("modelPosition", {})
        if pos and "size" in pos:
            x = float(pos.get("positionX", 0.65))
            y = float(pos.get("positionY", -1.28))
            sz = float(pos.get("size", -54.8))
            BASE_VTS_MODEL_Y = y
            BASE_VTS_MODEL_SIZE = sz
            if x > 0.1:
                BASE_VTS_MODEL_X = x
            CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE = x, y, sz
            log_print(f"📐 [VTS 模型記憶] 成功記錄老爸自訂基準大小: {sz:.1f}, 基準座標: ({x:.2f}, {y:.2f})")
    except Exception:
        pass

async def move_vts_spatial(
    target_pos=None, 
    target_x=None, target_y=None, 
    delta_x=None, delta_y=None, 
    target_size=None, delta_size=None, scale_factor=None, 
    duration=2.0,
    *args, **kwargs
):
    """【VTS Live2D 模型平滑走位與縮放控制器】透過 WebSocket 官方 API 驅動 7L 在 VTS 畫布內平滑走位與縮放"""
    global BASE_VTS_MODEL_X, BASE_VTS_MODEL_Y, BASE_VTS_MODEL_SIZE, CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE, GLOBAL_VTS
    target_vts = GLOBAL_VTS
    if not target_vts:
        return False
        
    if BASE_VTS_MODEL_SIZE is None or CURRENT_VTS_MODEL_SIZE is None:
        await fetch_vts_base_model_pos(target_vts)
        
    base_x = BASE_VTS_MODEL_X if BASE_VTS_MODEL_X is not None else 0.65
    base_y = BASE_VTS_MODEL_Y if BASE_VTS_MODEL_Y is not None else -1.28
    base_sz = BASE_VTS_MODEL_SIZE if BASE_VTS_MODEL_SIZE is not None else -54.8
    
    cur_x = CURRENT_VTS_MODEL_X if CURRENT_VTS_MODEL_X is not None else base_x
    cur_y = CURRENT_VTS_MODEL_Y if CURRENT_VTS_MODEL_Y is not None else base_y
    cur_sz = CURRENT_VTS_MODEL_SIZE if CURRENT_VTS_MODEL_SIZE is not None else base_sz

    # 1. 尺寸縮放計算
    clean_pos = str(target_pos or "").strip().lower()
    if clean_pos in ["復原", "原位", "原本位置", "回到原位", "home", "reset", "原本大小", "重設大小", "恢復大小", "再回去", "回去吧"]:
        dest_x = base_x
        dest_y = base_y
        dest_sz = base_sz
    elif scale_factor is not None and float(scale_factor) > 0:
        factor = float(scale_factor)
        dest_sz = base_sz + (factor - 1.0) * 35.0
        dest_x = cur_x
        dest_y = cur_y
    elif delta_size is not None:
        dest_sz = cur_sz + float(delta_size)
        dest_x = cur_x
        dest_y = cur_y
    elif target_size is not None:
        dest_sz = float(target_size)
        dest_x = cur_x
        dest_y = cur_y
    else:
        dest_sz = cur_sz
        
        # 2. 座標計算 (優先處理相對微調)
        if delta_x is not None or delta_y is not None:
            dx = float(delta_x) / 600.0 if abs(delta_x or 0) > 5 else float(delta_x or 0.0)
            dy = float(delta_y) / 600.0 if abs(delta_y or 0) > 5 else float(delta_y or 0.0)
            dest_x = cur_x + dx
            dest_y = cur_y + dy
        else:
            if clean_pos in ["放大", "變大", "大一點", "靠近", "貼近", "大模型"]:
                dest_x = cur_x
                dest_y = base_y + 0.12
                dest_sz = cur_sz + 12.0
            elif clean_pos in ["縮小", "變小", "小一點", "遠離", "小模型"]:
                dest_x = cur_x
                dest_y = base_y - 0.12
                dest_sz = cur_sz - 12.0
            elif any(k in clean_pos for k in ["鋼琴", "鋼琴旁", "鋼琴旁邊", "鋼琴前", "彈琴", "彈鋼琴"]):
                # 🎹 鋼琴專屬沉降站位：位置進一步下沉（Y 座標 base_y - 0.32，完美貼合桌面鋼琴鍵盤高度）
                dest_x = -0.62 + random.uniform(-0.02, 0.02)
                dest_y = base_y - 0.32 + random.uniform(-0.02, 0.02)
                dest_sz = base_sz
            elif any(k in clean_pos for k in ["左邊", "左側", "left", "去左邊", "來左邊看看", "左下", "左下角", "左上", "左上角"]):
                dest_x = -0.65 + random.uniform(-0.04, 0.04)
                dest_y = base_y + random.uniform(-0.03, 0.03)
            elif any(k in clean_pos for k in ["右邊", "右側", "right", "去右邊", "回去右邊", "右下", "右下角", "右上", "右上角", "回去吧", "回家"]):
                dest_x = 0.65 + random.uniform(-0.04, 0.04)
                dest_y = base_y + random.uniform(-0.03, 0.03)
            elif any(k in clean_pos for k in ["center", "中間", "正中間", "置中", "過來中間"]):
                dest_x = 0.0 + random.uniform(-0.03, 0.03)
                dest_y = base_y + random.uniform(-0.03, 0.03)
            elif any(k in clean_pos for k in ["hide", "躲角落", "角落"]):
                dest_x = 0.85
                dest_y = base_y - 0.15
                dest_sz = base_sz - 12.0
            elif clean_pos in ["原位", "回到原位", "原本位置", "復原"]:
                dest_x = base_x
                dest_y = base_y
                dest_sz = base_sz
            elif clean_pos and clean_pos != "random":
                dest_x = cur_x
                dest_y = cur_y
            else:
                # 🌟 7L 自由漫遊走位
                dest_x = random.choice([-0.65, -0.30, 0.0, 0.35, 0.65]) + random.uniform(-0.05, 0.05)
                dest_y = base_y + random.uniform(-0.06, 0.06)
                
    dest_sz = max(-95.0, min(80.0, dest_sz))
    dest_x = max(-1.8, min(1.8, dest_x))
    dest_y = max(-3.0, min(1.5, dest_y))
    
    # 若已經在目標原位，防抖略過
    if clean_pos in ["原位", "回到原位", "原本位置", "復原"] and abs(dest_x - cur_x) < 0.03 and abs(dest_y - cur_y) < 0.03 and abs(dest_sz - cur_sz) < 1.5:
        return True

    req_data = {
        "timeInSeconds": float(duration),
        "valuesAreRelativeToModel": False,
        "positionX": float(dest_x),
        "positionY": float(dest_y),
        "size": float(dest_sz),
        "rotation": 0.0
    }
    
    async with vts_lock:
        try:
            await asyncio.wait_for(target_vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "MoveModelReq",
                "messageType": "MoveModelRequest",
                "data": req_data
            }), timeout=1.5)
            CURRENT_VTS_MODEL_X = dest_x
            CURRENT_VTS_MODEL_Y = dest_y
            CURRENT_VTS_MODEL_SIZE = dest_sz
            return True
        except Exception:
            return False

async def apply_spatial_position(
    position_name: str = "random", 
    target_x: int = None, target_y: int = None, 
    delta_x: int = None, delta_y: int = None,
    target_w: int = None, target_h: int = None,
    delta_w: int = None, delta_h: int = None,
    scale_factor: float = None,
    duration: float = 2.0,
    *args, **kwargs
) -> str:
    """統一 Live2D 模型走位與縮放控制器"""
    global CURRENT_SPATIAL_LOCATION
    clean_pos = str(position_name).strip()
    
    d_size = None
    if delta_w is not None or delta_h is not None:
        d_size = ((delta_w or 0) + (delta_h or 0)) / 25.0
        
    await move_vts_spatial(
        target_pos=clean_pos,
        target_x=target_x, target_y=target_y,
        delta_x=delta_x, delta_y=delta_y,
        delta_size=d_size,
        scale_factor=scale_factor,
        duration=duration
    )
    CURRENT_SPATIAL_LOCATION = clean_pos
    log_print(f"🚀 [模型走位] 7L 模型平滑位移至: 「{clean_pos}」")
    return f"已成功平滑移動模型至「{clean_pos}」！"

async def set_vts_expression(vts, exp_tag):
    global CURRENT_ACTIVE_EXP
    try:
        clean_tag = str(exp_tag).strip().replace("[", "").replace("]", "").replace("EXPRESSION:", "").strip()
        if clean_tag in ["_RESET_", "預設", "重置", "關閉", "正常", "恢復", "無", "取消", "reset", "default", "none", "close", "off"]:
            if CURRENT_ACTIVE_EXP:
                prev_exp = CURRENT_ACTIVE_EXP
                CURRENT_ACTIVE_EXP = None
                async with vts_lock:
                    try:
                        await asyncio.wait_for(vts.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ResetExp",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": prev_exp, "active": False}
                        }), timeout=0.3)
                    except Exception: pass
            return

        target_filename = VTS_EXPRESSION_MAP.get(clean_tag)
        if not target_filename: return
        if CURRENT_ACTIVE_EXP == target_filename: return

        prev_exp = CURRENT_ACTIVE_EXP
        CURRENT_ACTIVE_EXP = target_filename  
        async with vts_lock:
            if prev_exp and prev_exp != target_filename:
                try:
                    await asyncio.wait_for(vts.request({
                        "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "DeactivateExp",
                        "messageType": "ExpressionActivationRequest", "data": {"expressionFile": prev_exp, "active": False}
                    }), timeout=0.3)
                except Exception: pass

            try:
                await asyncio.wait_for(vts.request({
                    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ActivateExpression",
                    "messageType": "ExpressionActivationRequest", "data": {"expressionFile": target_filename, "active": True}
                }), timeout=0.5)
            except Exception: pass
    except Exception as e:
        print(f"\n❌ [表情系統] 發生錯誤: {e}")

# ────────────────────────────────────────────────────────
# 🎮 7. 7L 本機遊樂場沙盒 (7L_Playground)
# ────────────────────────────────────────────────────────
PLAYGROUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "7L_Playground")
os.makedirs(PLAYGROUND_DIR, exist_ok=True)

# 🛡️ 敏感/高危指令安全黑名單過濾
DANGEROUS_CODE_PATTERNS = [
    r"\bos\.remove\b", r"\bos\.unlink\b", r"\bos\.rmdir\b", r"\bos\.system\b",
    r"\bshutil\.rmtree\b", r"\bshutil\.move\b",
    r"\bformat\s+[a-zA-Z]:", r"\bdel\s+/[sfq]", r"\brmdir\s+/[sq]",
    r"\bctypes\b", r"\bsubprocess\b", r"\bwinreg\b",
    r"\bshutdown\b", r"\bos\._exit\b", r"\bsys\.exit\b"
]

def _run_subprocess_code(file_path: str, timeout: int = 3) -> str:
    try:
        proc = subprocess.Popen(
            [sys.executable, file_path],
            cwd=PLAYGROUND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        try:
            stdout_text, stderr_text = proc.communicate(timeout=timeout)
            if proc.returncode == 0:
                output_msg = "✅ 程式碼執行完成 (ReturnCode 0)。"
                if stdout_text.strip():
                    output_msg += f"\n輸出結果：\n{stdout_text.strip()[:500]}"
                return output_msg
            else:
                return f"⚠️ 程式執行結束但回傳錯誤 (ReturnCode {proc.returncode})。\n錯誤訊息：\n{(stderr_text or stdout_text).strip()[:500]}"
        except subprocess.TimeoutExpired:
            # 程式仍在持續運行（例如 Tkinter/Pygame 遊戲視窗在螢幕上持續運行）
            return "✅ 遊戲/程式視窗已成功在老爸螢幕上開啟並持續運行中！"
    except Exception as e:
        return f"❌ 執行過程發生異常: {e}"

async def execute_local_python_code(code_string: str) -> str:
    """在 7L 專屬的本機遊樂場 (7L_Playground) 儲存並執行 Python 程式碼（可彈出 Tkinter 小遊戲、視覺化動畫、數學計算或圖形視窗）。
    
    Args:
        code_string: 要執行的完整 Python 程式碼字串。
    """
    print(f"\n💻 [Tool 調用] 7L 正在本機沙盒 (7L_Playground) 執行 Python 程式碼...")
    
    # 1. 安全關鍵字過濾
    for pattern in DANGEROUS_CODE_PATTERNS:
        if re.search(pattern, code_string, re.IGNORECASE):
            print(f"⚠️ [安全攔截] 偵測到受限指令 pattern: {pattern}")
            return f"安全限制攔截：程式碼包含受限的高風險指令 ({pattern})，已拒絕執行以保護老爸的電腦。"
            
    # 2. 寫入 7L_Playground/temp_run.py
    temp_file = os.path.join(PLAYGROUND_DIR, "temp_run.py")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code_string)
    except Exception as e:
        return f"寫入程式碼檔案失敗: {e}"
        
    # 3. 非同步在背景執行（不阻塞主事件迴圈）
    result = await asyncio.to_thread(_run_subprocess_code, temp_file, timeout=15)
    print(f"💻 [Tool 完成] 執行結果: {result[:120]}...")
    return result

# ────────────────────────────────────────────────────────
# 🛠️ 8. Google GenAI 官方 Function Calling (工具調用清單)
# ────────────────────────────────────────────────────────
async def trigger_vts_expression(expression_name: str) -> str:
    """切換 7L (Live2D 模型) 的臉部表情以表達情感或關閉表情。
    
    Args:
        expression_name: 要切換的表情名稱。可選值包括：'臉紅', '愛心', '星星', '星星眼', '生氣', '黑臉', '預設' (關閉表情/恢復正常)。
    """
    global GLOBAL_VTS
    clean_name = expression_name.strip().replace("[", "").replace("]", "").replace("EXPRESSION:", "").strip()
    print(f"\n🎭 [Tool 調用] 7L 正在切換表情至: 「{clean_name}」")
    if GLOBAL_VTS:
        if clean_name in ["預設", "重置", "reset", "default", "_RESET_", "關閉", "正常", "恢復", "無", "取消", "none", "close", "off"]:
            await set_vts_expression(GLOBAL_VTS, "_RESET_")
            return "已成功關閉表情，恢復預設狀態。"
        else:
            await set_vts_expression(GLOBAL_VTS, clean_name)
            return f"已成功切換 Live2D 模型表情至：{clean_name}"
    return f"已記錄表情切換：{clean_name}"

def search_google(query: str) -> str:
    """使用 Google / 網路搜尋引擎查詢最新的即時資訊、天氣、時事新聞或未知知識。
    
    Args:
        query: 要搜尋的關鍵字或問題描述
    """
    print(f"\n🔍 [Tool 調用] 7L 正在使用 Google / 網路搜尋: 「{query}」")
    try:
        if tavily_client:
            res = tavily_client.search(query=query, search_depth="advanced")
            if isinstance(res, dict) and "results" in res:
                snippets = []
                for item in res["results"][:3]:
                    title = item.get("title", "")
                    content = item.get("content", "")
                    snippets.append(f"- {title}: {content}")
                if snippets:
                    return "\n".join(snippets)
            return str(res)
        
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                if results:
                    snippets = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                    return "\n".join(snippets)
        except Exception as e_ddg:
            print(f"\n⚠️ [DuckDuckGo 搜尋失敗]: {e_ddg}")
        return "搜尋無結果。"
    except Exception as e:
        print(f"\n❌ [搜尋 Tool 異常]: {e}")
        return f"搜尋時發生錯誤: {e}"

DRAWING_DIR = os.path.join(PLAYGROUND_DIR, "drawings")
os.makedirs(DRAWING_DIR, exist_ok=True)

IMAGE_GEN_MODELS = [
    # 🍌 Nano Banana 系列 (Gemini 原生生圖創作)
    "gemini-3.1-flash-image",           # Nano Banana 2
    "gemini-3.1-flash-image-preview",   # Nano Banana 2 Preview
    "gemini-3-pro-image",               # Nano Banana Pro
    "gemini-3-pro-image-preview",       # Nano Banana Pro Preview
    "nano-banana-pro-preview",          # Nano Banana Pro Preview Alias
    "gemini-3.1-flash-lite-image",      # Nano Banana 2 Lite
    "gemini-2.5-flash-image",           # Nano Banana (經典)
    
    # 🖼️ Imagen 4 頂尖寫實與二次元生圖
    "imagen-4.0-ultra-generate-001",    # Imagen 4 Ultra (極限畫質)
    "imagen-4.0-generate-001",          # Imagen 4 標準版
    "imagen-4.0-fast-generate-001"      # Imagen 4 Fast (極速版)
]

async def generate_ai_image(prompt: str) -> str:
    """使用 Google 頂尖 AI 生圖模型 (Nano Banana / Gemini Image / Imagen / FLUX) 繪製高品質圖片、二次元插圖或藝術創作，並自動在老爸的螢幕上彈出展示。
    
    Args:
        prompt: 畫面內容的詳細描述提示詞（建議包含主體、外貌、風格、色彩、光影等豐富細節）。
    """
    import urllib.parse
    print(f"\n🎨 [Tool 調用] 7L 正在啟動 AI 繪圖創作: 「{prompt[:60]}...」")
    
    img_bytes = None
    
    # 🌟 第一防線：Google 原生生圖模型 (若金鑰有配額)
    if GEMINI_KEYS:
        num_keys = min(4, len(GEMINI_KEYS))
        for offset in range(num_keys):
            if img_bytes: break
            g_key = GEMINI_KEYS[offset]
            temp_client = genai.Client(api_key=g_key)
            
            for img_model in ["gemini-2.5-flash-image", "gemini-3.1-flash-image", "gemini-3-pro-image"]:
                try:
                    res = await asyncio.wait_for(
                        temp_client.aio.models.generate_content(
                            model=img_model,
                            contents=prompt
                        ),
                        timeout=8.0
                    )
                    if res and res.candidates:
                        for cand in res.candidates:
                            if cand.content and cand.content.parts:
                                for part in cand.content.parts:
                                    if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                                        img_bytes = part.inline_data.data
                                        break
                            if img_bytes: break
                    if img_bytes: break
                except Exception:
                    continue

    # 🌟 第二防線：FLUX.1 / SDXL 頂尖二次元與寫實藝術引擎 (100% 保證出圖、0 配額限制、超高畫質)
    if not img_bytes:
        try:
            anime_prompt = f"{prompt}, masterpiece, best quality, ultra-detailed, anime art style, 8k resolution"
            encoded_p = urllib.parse.quote(anime_prompt)
            flux_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width=1024&height=1024&model=flux&nologo=true&enhance=true"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(flux_url, timeout=25.0) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
        except Exception as e_flux:
            print(f"⚠️ [FLUX 生圖備援異常]: {e_flux}")

    if img_bytes:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"7L_art_{timestamp}.png"
        save_path = os.path.join(DRAWING_DIR, file_name)
        
        with open(save_path, "wb") as f:
            f.write(img_bytes)
            
        print(f"🎨 [Tool 完成] 7L 繪圖成功！已儲存至: {save_path}")
        
        # 在老爸桌面上彈出顯示圖片
        try:
            if sys.platform == "win32":
                os.startfile(save_path)
        except Exception:
            pass
            
        return f"✅ 繪圖完成！插畫已成功儲存至 7L_Playground/drawings/{file_name} 並已在老爸的螢幕上彈出展示！"

    return "⚠️ 繪圖完成但生圖伺服器當前忙線中，7L 稍後會再幫老爸嘗試一次！"

async def move_spatial_position(
    target_position: str = "自由漫遊", 
    scale_factor: float = None
) -> str:
    """控制 7L 的 Live2D 模型在 VTube Studio 畫布內平滑移動位置與縮放。
    
    Args:
        target_position: 目標語意位置（如：'右側', '右下角', '左側', '左上角', '中間', '放大', '縮小', '往右一點', '往左一點', '自由漫遊', '原位'）。
        scale_factor: (可選) 模型整體等比例縮放倍率（例如: 1.2 代表放大 20%, 0.8 代表縮小 20%）。
    """
    print(f"\n🚀 [Tool 調用] 7L 正在自主調整模型位置: 「{target_position}」 (縮放: {scale_factor})")
    res = await apply_spatial_position(
        position_name=target_position, 
        scale_factor=scale_factor,
        duration=2.0
    )
    return f"模型位置調整完成：{res}"

# ────────────────────────────────────────────────────────
# 🎵 8.1 歌唱與點歌舞台系統 (Singing & Song Playlist Engine)
# ────────────────────────────────────────────────────────
SONGS_DIR = "songs"
os.makedirs(SONGS_DIR, exist_ok=True)

current_song_task = None
is_singing_active = False

def get_available_songs():
    """取得 songs/ 目錄下所有支援的音樂檔案清單"""
    if not os.path.exists(SONGS_DIR):
        return []
    valid_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    songs = []
    for f in os.listdir(SONGS_DIR):
        ext = os.path.splitext(f)[1].lower()
        if ext in valid_exts:
            songs.append(f)
    return songs

def list_songs() -> str:
    """列出目前 7L 歌庫 (songs/) 中所有可點播演唱的歌曲清單。"""
    songs = get_available_songs()
    if not songs:
        return "目前 songs/ 資料夾中還沒有放入任何歌曲音檔喔！老爸可以把 .mp3 或 .wav 歌曲檔案放進 songs/ 資料夾。"
    song_names = [os.path.splitext(s)[0] for s in songs]
    return "🎵 目前歌庫中的歌曲清單：\n" + "\n".join([f"• {name}" for name in song_names])

async def stop_singing() -> str:
    """立即停止目前正在演唱的歌曲，復原表情並恢復正常待命狀態。"""
    global is_singing_active, current_song_task, current_ai_state, GLOBAL_VTS
    is_singing_active = False
    if current_song_task and not current_song_task.done():
        current_song_task.cancel()
    try:
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
    except Exception:
        pass
    if GLOBAL_VTS:
        await set_vts_expression(GLOBAL_VTS, "_RESET_")
    if current_ai_state == "SINGING":
        current_ai_state = "IDLE"
    await asyncio.to_thread(update_subtitle, "")
    log_print("🛑 [歌唱舞台] 已停止唱歌。")
    return "已停止唱歌囉！"

async def play_song_worker(song_path: str, song_title: str):
    """背景歌唱音訊播放與舞台狀態協程"""
    global is_singing_active, current_ai_state, GLOBAL_VTS
    try:
        is_singing_active = True
        current_ai_state = "SINGING"
        
        # 1. 啟用專屬歌唱表情 (星星眼)
        if GLOBAL_VTS:
            await set_vts_expression(GLOBAL_VTS, "星星眼")
            
        # 2. 更新字幕
        await asyncio.to_thread(update_subtitle, f"🎵 [7L 正在演唱] {song_title}")
        
        # 3. 停止當前正在播的語音/音效並載入歌曲
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:
            pass
            
        pygame.mixer.init(frequency=44100)
        pygame.mixer.music.load(song_path)
        pygame.mixer.music.set_volume(1.0)
        pygame.mixer.music.play()
        
        # 4. 等待歌曲播放完畢
        await asyncio.sleep(0.5)
        while is_singing_active and pygame.mixer.music.get_busy():
            await asyncio.sleep(0.2)
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log_print(f"❌ [歌唱播放異常]: {e}")
    finally:
        is_singing_active = False
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except Exception:
            pass
        if GLOBAL_VTS:
            await set_vts_expression(GLOBAL_VTS, "_RESET_")
        if current_ai_state == "SINGING":
            current_ai_state = "IDLE"
        await asyncio.to_thread(update_subtitle, "")
        log_print(f"🎤 [歌唱舞台] 《{song_title}》演唱完畢！")

async def sing_song(song_name: str = "") -> str:
    """讓 7L 開始唱歌。會在 Live2D 上切換歡快表情、身體隨節奏搖擺並對嘴演唱 songs/ 資料夾中的歌曲。
    
    Args:
        song_name: 想點播的歌曲名稱或關鍵字（如留空或找不到會隨機挑選或提示歌單）。
    """
    global current_song_task
    songs = get_available_songs()
    if not songs:
        return "目前 songs/ 資料夾中還沒有放入任何歌曲音檔喔！老爸可以把喜歡的歌曲 .mp3 丟進 songs/ 資料夾，我就能唱給你聽囉！"
    
    target_song = None
    if song_name and song_name.strip():
        clean_target = song_name.strip().lower()
        # 模糊比對
        for s in songs:
            s_base = os.path.splitext(s)[0].lower()
            if clean_target in s_base or s_base in clean_target:
                target_song = s
                break
        if not target_song:
            matches = difflib.get_close_matches(clean_target, [os.path.splitext(s)[0] for s in songs], n=1, cutoff=0.3)
            if matches:
                matched_base = matches[0]
                for s in songs:
                    if os.path.splitext(s)[0] == matched_base:
                        target_song = s
                        break
                        
    if not target_song:
        target_song = random.choice(songs)
        
    song_title = os.path.splitext(target_song)[0]
    song_path = os.path.join(SONGS_DIR, target_song)
    
    # 停止上一首
    if current_song_task and not current_song_task.done():
        current_song_task.cancel()
        
    current_song_task = asyncio.create_task(play_song_worker(song_path, song_title))
    log_print(f"🎤 [歌唱舞台] 7L 正在為老爸演唱: 《{song_title}》")
    return f"好喔，7L 這就開始為老爸演唱《{song_title}》！[EXPRESSION: 星星眼]"

# ────────────────────────────────────────────────────────
# 🎹 8.2 88 鍵全音域真實平台鋼琴發聲與樂譜演奏引擎 (Virtual Piano 88K)
# ────────────────────────────────────────────────────────
WHITE_KEYS = []
BLACK_KEYS = []

# 最低 3 音: A0 (21), A#0 (22), B0 (23)
WHITE_KEYS.append(('A0', 21, 'A0', ''))
BLACK_KEYS.append(('A#0', 22, 'A#0', 0, ''))
WHITE_KEYS.append(('B0', 23, 'B0', ''))

WHITE_CHARS_MAP = {
    2: ['1', '2', '3', '4', '5', '6', '7'],
    3: ['8', '9', '0', 'q', 'w', 'e', 'r'],
    4: ['t', 'y', 'u', 'i', 'o', 'p', 'a'],
    5: ['s', 'd', 'f', 'g', 'h', 'j', 'k'],
    6: ['l', 'z', 'x', 'c', 'v', 'b', 'n'],
}
BLACK_CHARS_MAP = {
    2: ['!', '@', '$', '%', '^'],
    3: ['*', '(', 'Q', 'W', 'E'],
    4: ['T', 'Y', 'I', 'O', 'P'],
    5: ['S', 'D', 'G', 'H', 'J'],
    6: ['L', 'Z', 'C', 'V', 'B'],
}

NOTE_NAMES_W = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
SEMITONES_W = [0, 2, 4, 5, 7, 9, 11]

NOTE_NAMES_B = ['C#', 'D#', 'F#', 'G#', 'A#']
SEMITONES_B = [1, 3, 6, 8, 10]
W_INDICES_B = [0, 1, 3, 4, 5]

for oct in range(1, 8):
    base_midi = 12 + oct * 12
    w_start_idx = len(WHITE_KEYS)
    for i, (n, semi) in enumerate(zip(NOTE_NAMES_W, SEMITONES_W)):
        midi = base_midi + semi
        char = ''
        if oct in WHITE_CHARS_MAP:
            char = WHITE_CHARS_MAP[oct][i]
        elif oct == 7 and n == 'C':
            char = 'm'
        WHITE_KEYS.append((f'{n}{oct}', midi, f'{n}{oct}', char))
        
    for j, (n, semi, w_off) in enumerate(zip(NOTE_NAMES_B, SEMITONES_B, W_INDICES_B)):
        midi = base_midi + semi
        char = ''
        if oct in BLACK_CHARS_MAP:
            char = BLACK_CHARS_MAP[oct][j]
        BLACK_KEYS.append((f'{n}{oct}', midi, f'{n}{oct}', w_start_idx + w_off, char))

WHITE_KEYS.append(('C8', 108, 'C8', ''))

VP_MAP = {}
MIDI_TO_VP = {}
MIDI_TO_KEYID = {}

for key_id, midi, name, char in WHITE_KEYS:
    MIDI_TO_KEYID[midi] = key_id
    if char:
        VP_MAP[char] = midi
        MIDI_TO_VP[midi] = char
    else:
        VP_MAP[key_id] = midi
        MIDI_TO_VP[midi] = key_id

for key_id, midi, name, _, char in BLACK_KEYS:
    MIDI_TO_KEYID[midi] = key_id
    if char:
        VP_MAP[char] = midi
        MIDI_TO_VP[midi] = char
    else:
        VP_MAP[key_id] = midi
        MIDI_TO_VP[midi] = key_id

SAMPLE_RATE = 44100
PIANO_SOUNDS = {}
is_piano_active = False
current_piano_task = None

def midi_to_freq(midi_num):
    return 440.0 * (2.0 ** ((midi_num - 69) / 12.0))

def generate_piano_tone(midi_num, duration=3.0):
    """史坦威古典音樂廳平台鋼琴 (Steinway Concert Grand) 物理聲學建模"""
    f0 = midi_to_freq(midi_num)
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    
    B = 0.00015 * ((f0 / 261.63) ** 0.55)
    num_harmonics = min(28, int((SAMPLE_RATE / 2) / f0))
    detune = 0.28 if midi_num >= 40 else 0.12
    signal = np.zeros_like(t)
    
    for n in range(1, num_harmonics + 1):
        fn = n * f0 * math.sqrt(1.0 + B * (n ** 2))
        if fn >= SAMPLE_RATE / 2: break
        amp = (1.0 / (n ** 1.12)) * math.exp(-0.065 * n)
        decay_prompt = (1.6 + f0 / 280.0) * (n ** 0.55)
        decay_sustain = (0.5 + f0 / 900.0) * (n ** 0.32)
        env = 0.55 * np.exp(-decay_prompt * t) + 0.45 * np.exp(-decay_sustain * t)
        
        s1 = np.sin(2 * np.pi * fn * t)
        s2 = np.sin(2 * np.pi * (fn + detune) * t + 0.3)
        s3 = np.sin(2 * np.pi * (fn - detune) * t + 0.6)
        signal += amp * env * (0.42 * s1 + 0.29 * s2 + 0.29 * s3)
        
    hammer_samples = int(SAMPLE_RATE * 0.006)
    if hammer_samples > 0:
        noise = (np.random.rand(hammer_samples) * 2 - 1) * np.exp(-np.linspace(0, 5.5, hammer_samples))
        signal[:hammer_samples] += noise * 0.16 * (1.0 / (1.0 + f0 / 600.0))
        
    body_res = 0.08 * np.sin(2 * np.pi * 110.0 * t) * np.exp(-4.5 * t)
    signal += body_res
    
    attack_samples = int(SAMPLE_RATE * 0.002)
    if attack_samples > 0: signal[:attack_samples] *= np.linspace(0, 1, attack_samples)
    release_samples = int(SAMPLE_RATE * 0.04)
    if len(signal) > release_samples: signal[-release_samples:] *= np.linspace(1, 0, release_samples)
    
    max_val = np.max(np.abs(signal))
    if max_val > 0: signal = signal / max_val * 0.88
    audio_int16 = (signal * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.column_stack((audio_int16, audio_int16)))

import pygame.midi

class ClassicalPianoSoundEngine:
    def __init__(self):
        self.midi_out = None
        self.init_sound()
        
    def init_sound(self):
        try:
            if not pygame.midi.get_init():
                pygame.midi.init()
            out_id = pygame.midi.get_default_output_id()
            if out_id != -1:
                self.midi_out = pygame.midi.Output(out_id)
                self.midi_out.set_instrument(0) # 0 = Acoustic Grand Piano (古典平台鋼琴)
                self.midi_out.write_short(0xB0, 91, 110) # CC 91: Reverb 空間深邃迴響
                self.midi_out.write_short(0xB0, 93, 35)  # CC 93: Chorus 細緻琴弦共鳴
                self.midi_out.write_short(0xB0, 72, 88)  # CC 72: Release Time (自然漸弱衰減，杜絕瞬間掐斷)
                self.midi_out.write_short(0xB0, 71, 68)  # CC 71: Resonance (木質音板共鳴)
                self.midi_out.write_short(0xB0, 7, 127)  # CC 7: 主音量
                log_print("🎹 [Virtual Piano] 88 鍵真實古典平台鋼琴 (Acoustic Grand Piano) 自然漸弱音色庫載入完成！")
        except Exception as e:
            log_print(f"⚠️ [Classical Sound Engine 初始化異常]: {e}")

    def note_on(self, midi_num: int, velocity: int = 105):
        if self.midi_out and 21 <= midi_num <= 108:
            try:
                self.midi_out.note_on(midi_num, max(30, min(127, int(velocity))))
            except Exception:
                pass

    def note_off(self, midi_num: int):
        if self.midi_out and 21 <= midi_num <= 108:
            try:
                self.midi_out.note_off(midi_num, 0)
            except Exception:
                pass

    def all_notes_off(self):
        if self.midi_out:
            try:
                self.midi_out.write_short(0xB0, 120, 0)
                self.midi_out.write_short(0xB0, 123, 0)
            except Exception:
                pass

SOUND_ENGINE: Optional[ClassicalPianoSoundEngine] = None
PIANO_NOTE_FOCUS_X = 0.0

async def piano_focus_udp_worker():
    """接收來自虛擬鋼琴視窗的即時音符密集重心 UDP 廣播，驅動 7L 視線與頭部精準追蹤琴鍵彈奏位置"""
    global PIANO_NOTE_FOCUS_X
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    sock.setblocking(False)
    try:
        sock.bind(("127.0.0.1", 39281))
    except Exception:
        return
        
    while True:
        try:
            data, _ = await loop.sock_recvfrom(sock, 64)
            if data:
                val = float(data.decode('utf-8'))
                PIANO_NOTE_FOCUS_X = val
        except Exception:
            await asyncio.sleep(0.05)

def update_piano_focus_notes(midi_list):
    global PIANO_NOTE_FOCUS_X
    if not midi_list: return
    try:
        avg_midi = sum(midi_list) / len(midi_list)
        offset = max(-1.0, min(1.0, (avg_midi - 60.0) / 28.0))
        # 鏡像校正：7L 面對鏡頭彈琴時，右手高音區在觀眾視角的螢幕左側 (-)，左手低音區在螢幕右側 (+)
        PIANO_NOTE_FOCUS_X = -offset * 22.0
    except Exception:
        pass

def init_piano_synthesizer():
    global SOUND_ENGINE
    if SOUND_ENGINE is None:
        SOUND_ENGINE = ClassicalPianoSoundEngine()

def play_piano_note(char_or_chord):
    if not SOUND_ENGINE: return
    if isinstance(char_or_chord, list):
        midis = []
        for k in char_or_chord:
            midi = VP_MAP.get(k)
            if midi:
                midis.append(midi)
                SOUND_ENGINE.note_on(midi, 105)
        if midis:
            update_piano_focus_notes(midis)
    else:
        midi = VP_MAP.get(char_or_chord)
        if midi:
            SOUND_ENGINE.note_on(midi, 105)
            update_piano_focus_notes([midi])

def precise_sleep(duration_sec):
    if duration_sec <= 0: return
    target = time.perf_counter() + duration_sec
    remain = target - time.perf_counter()
    if remain > 0.004: time.sleep(remain - 0.003)
    while time.perf_counter() < target: pass

def parse_vp_sheet(sheet_text: str, base_bpm=160, note_mode="16th"):
    beat_sec = 60.0 / max(40.0, float(base_bpm))
    if note_mode == "16th":
        unit_sec = beat_sec / 4.0
        space_sec = beat_sec / 4.0
        chord_sec = beat_sec / 2.0
    elif note_mode == "8th":
        unit_sec = beat_sec / 2.0
        space_sec = beat_sec / 2.0
        chord_sec = beat_sec * 0.75
    else:
        unit_sec = beat_sec
        space_sec = beat_sec
        chord_sec = beat_sec * 1.0

    tokens = []
    i = 0
    clean_text = sheet_text.strip()
    while i < len(clean_text):
        ch = clean_text[i]
        if ch == '[':
            end_idx = clean_text.find(']', i)
            if end_idx != -1:
                chord_keys = [k for k in clean_text[i+1:end_idx] if k in VP_MAP]
                if chord_keys: tokens.append(('chord', chord_keys, chord_sec))
                i = end_idx + 1
                continue
            else: i += 1; continue
        elif ch in [' ', '\n', '\r', '\t']:
            tokens.append(('rest', None, space_sec))
            i += 1
        elif ch == '|':
            tokens.append(('rest', None, beat_sec))
            i += 1
        elif ch == '-':
            tokens.append(('rest', None, unit_sec * 1.5))
            i += 1
        elif ch in VP_MAP:
            tokens.append(('note', ch, unit_sec))
            i += 1
        else:
            i += 1
    return tokens

# 🎼 經典鋼琴名曲琴譜庫
PIANO_SHEETS = {
    "月光奏鳴曲 第三樂章": {
        "title": "月光奏鳴曲 第三樂章 (Moonlight Sonata 3rd Mov. - Presto Agitato)",
        "author": "貝多芬",
        "bpm": 240,
        "mode": "16th",
        "sheet": """
* 0 W T u O S f H L [*SL] [*SL]
( 9 W Y i O D g H Z [(DHZ] [(DHZ]
8 0 w t u o s f h l [8sfhl] [8sfhl]
* 0 W T u O S f H L [*SL] [*SL]
[0T] u O S [0T] u O S [0T] u O S
[eT] u p S [eT] u p S [eT] u p S
[0T] u O S [0T] u O S [*W] T u O [60ep]
"""
    },
    "李斯特 鐘": {
        "title": "鐘 (La Campanella)",
        "author": "李斯特",
        "bpm": 220,
        "mode": "16th",
        "sheet": """
[YD] [YD] [YD] Z Z Z [YD] [YD] [YD] Z Z Z [YD] Z Z [YD]
Z Z
D
Z Z Z Z Z L Z [kW] Ya Z k Z J Z [Hr]
ODZh Z H Z [JY] PhZD Z D Z [fo]
PZD Z S Z [aO] Z a Z P Z [Or] yiZ
o Z O Z [PYo] Z Y D D Z Z Z Z Z L Z
[kW] YaZk Z J Z [Hr] ODZh Z H Z
[JY] PhZD Z D Z [fo] PZD Z [DS] Z [DOa]
Z H k Z Z [DYoS] Z h J Z Z W Y a H D
Z Z Z Z Z [ZL] L [k%] Z [k(r] Z J Z [H7] Z [hWY]
Z H [Zh] H [J(] Z [DEo] Z [DG] Z [foP] Z [DoP] Z S Z
[aO] Z [aO] Z P Z [Oryi] Z [oryi] Z O Z [P(o] Z Y D
D Z Z Z Z Z L Z [k%] Z [k(r] Z J Z [H7] Z
[hWY] Z H [Zh] H [J(] Z [DEo] Z [DG] Z [fTOP] V [DYOP] V [SuOP]
V [DYOa] Z H k Z Z [D(To] Z h J Z Z % r Y
"""
    },
    "愛之夢": {
        "title": "愛之夢 第三號 (Liebestraum No. 3)",
        "author": "李斯特",
        "bpm": 130,
        "mode": "8th",
        "sheet": """
([t%]
Y O s O Y t Y O s O Y [t5] u P s P
u u
P s [Pt] u [t4] Y p s [pt] Y T Y p s [pt] Y
[t^] y O s O y q y O s [Oq] y [q@] T [Yw] s
[YW] T [t(] T Y o [YE] T [W%] t Y O Y t % W
t O [Y(] W [t%] Y O s O Y t Y O s O Y
[t5] u P s P u $ u P s [Pt] u [t4] Y p s
[pt] Y [Tq] eY i s [pt] Y [i^] y O g s O ^
W
"""
    },
    "冬風練習曲": {
        "title": "冬風練習曲 (Winter Wind Op. 25 No. 11)",
        "author": "蕭邦",
        "bpm": 240,
        "mode": "16th",
        "sheet": """
u u
u
u i
u
t
u
[uwt8]
[uwt8]
[wut8]
[twu8] [iet4]
[twu1]
[et4]
[tuw1]
[yW7]
[c6]
mxbZm[zute]bLbm[etu]x[uten]xBl
bx[Veti]lvlCj[cetu]lxjZl[z0et]j
Ljlf[etuk]fJsjfHshsGp
[6g]sfpDs[60d]pSps[60]u[a60]uP
tpu[O6q]totIe[i60]tueYt[6y]
eTet0[3r]0E8e0W8e0t
q[u%]ryifad[qy]gxkz[qy]g[qtz]
jlgdp[s6]iyetq[%u]ryif
"""
    },
    "少女的祈禱": {
        "title": "少女的祈禱 (A Maiden's Prayer)",
        "author": "巴達捷夫斯卡",
        "bpm": 120,
        "mode": "8th",
        "sheet": """
[Y(ZD]
[Y(DZ]
[y9zd] [9ydz]
[8tsl] [8tsl]
[^EPJ] [^EPJ]
[%WOH] [%WOH]
[5woh] [5woh]
[4qig] [q4gi]
[(@DY] s
DH [%l] ^
^ O d gJ [@(]
[PJ] [DZ] [EYohv] [JB] Z [EYov] [EYo]
c
[%Wc] Z
[WtiZ] z [lm] [Wtilm] [Wti]
[^E]
[yd] [ig] [qWEyPJ] [dz] [cg] [qWEyz] [qWEy]
[ml]
[@(lm] [JB]
[EYoJB] [HV] [hv] [EYohv] [EYo]
"""
    },
    "幻想即興曲": {
        "title": "幻想即興曲 (Fantaisie-Impromptu Op. 66)",
        "author": "蕭邦",
        "bpm": 220,
        "mode": "16th",
        "sheet": """
[*W] [Tu] [OS] [Tu] [*W] [Tu] [OS] [Tu]
[9W] [YI] [PD] [YI] [*W] [Tu] [OS] [Tu]
S a S a S D f G H J k L
[*W] [Tu] [OS] [Tu] [*W] [Tu] [OS] [Tu]
[9W] [YI] [PD] [YI] [*W] [Tu] [OS] [Tu]
[Tu] p s f [Tj] [Tu] p s f [Tj] [80ep]
"""
    },
    "給愛麗絲": {
        "title": "給愛麗絲 (Für Elise)",
        "author": "貝多芬",
        "bpm": 150,
        "mode": "8th",
        "sheet": """
e W e W e u y t r
8 0 w r | 0 w r u
0 e r y | e W e W
e u y t r | 8 0 w r
0 w r u | 0 r e w
e | [8u] [0o] [wp] [ra]
[0u] [wo] [rp] [ua] | [0y] [we] [rt] [yu]
[0t] [wr] [re] [wt]
e W e W e u y t r
8 0 w r | 0 w r u
"""
    },
    "天空之城": {
        "title": "天空之城 (Laputa: Castle in the Sky)",
        "author": "久石讓",
        "bpm": 120,
        "mode": "8th",
        "sheet": """
e r [6t] 0 e [5r] 9 w [3e] 7 0
[6e] 0 r [6t] 0 e [5r] 9 w [3e]
e r [6t] 0 e [5r] 9 w [3e] 7 0
[4q] 8 e [30] 7 w [29] 6 9 [18]
[4q] 8 e [5w] 9 r [6e] 0 e
"""
    },
    "野蜂飛舞": {
        "title": "野蜂飛舞 (Flight of the Bumblebee)",
        "author": "林姆斯基",
        "bpm": 300,
        "mode": "16th",
        "sheet": """
y T y Y u Y u i o i o I p P s d
f d s P p I o i u Y y T y Y u Y
u i o i o I p P s d f d s P p I
o i u Y y T y Y u Y u i o i o I
p P s d f d s P p I o i u Y y
"""
    },
    "Rush E": {
        "title": "Rush E (超極速版)",
        "author": "Sheet Music Boss",
        "bpm": 280,
        "mode": "16th",
        "sheet": """
e e e e e e e e e e e e e e e e
[8e] [0e] [we] [re] [tu] [yI] [up] [oa]
[ep] e e e [ep] e e e [ep] [ep] [ep] [ep]
[8ep] [0ep] [wep] [rep] [tup] [yIp] [uop] [oap]
[eup] [eup] [eup] [eup]
"""
    }
}

def list_piano_sheets() -> str:
    """查詢目前 7L 鋼琴曲庫中所有可彈奏的鋼琴名曲清單。"""
    lines = ["🎹 目前 7L 鋼琴曲庫清單："]
    for k, v in PIANO_SHEETS.items():
        lines.append(f"• 《{v['title']}》 - {v['author']} (BPM: {v['bpm']})")
    return "\n".join(lines)

PIANO_SESSION_ID = 0
current_piano_process = None
current_piano_song_title = ""

async def stop_virtual_piano() -> str:
    """立即停止目前正在彈奏的鋼琴曲，關閉視覺化鋼琴視窗，復原表情並恢復待命。"""
    global is_piano_active, current_piano_song_title, current_piano_task, current_piano_process, current_ai_state, GLOBAL_VTS, PIANO_SESSION_ID
    PIANO_SESSION_ID += 1  # 註銷所有先前或進行中的鋼琴 Session
    is_piano_active = False
    current_piano_song_title = ""
    
    if current_piano_process and current_piano_process.poll() is None:
        try:
            current_piano_process.terminate()
        except Exception:
            pass
        current_piano_process = None
        
    if current_piano_task and not current_piano_task.done():
        current_piano_task.cancel()
    if SOUND_ENGINE:
        SOUND_ENGINE.all_notes_off()
    if GLOBAL_VTS:
        await set_vts_expression(GLOBAL_VTS, "_RESET_")
    if current_ai_state == "PIANO":
        current_ai_state = "IDLE"
    await asyncio.to_thread(update_subtitle, "")
    log_print("🛑 [鋼琴演奏] 已停止彈琴並關閉視覺化鋼琴介面。")
    return "已停止彈奏鋼琴囉！"

import mido

MIDI_SHEETS_DIR = "midi_sheets"
os.makedirs(MIDI_SHEETS_DIR, exist_ok=True)

AUTHENTIC_MIDI_MAP = {
    # 鐘 (La Campanella)
    "李斯特 鐘": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    "李斯特鐘": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    "鐘": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    "la campanella": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    "campanella": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    "campanella.mid": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    "鐘 (liszt - la campanella)": os.path.join(MIDI_SHEETS_DIR, "campanella.mid"),
    
    # 月光 (Moonlight Sonata 3rd)
    "月光奏鳴曲 第三樂章": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),
    "月光第三樂章": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),
    "月光奏鳴曲": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),
    "月光": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),
    "moonlight": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),
    "moonlight 3rd": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),
    "moonlight_3rd.mid": os.path.join(MIDI_SHEETS_DIR, "moonlight_3rd.mid"),

    # 愛之夢 (Liebestraum)
    "愛之夢": os.path.join(MIDI_SHEETS_DIR, "liebestraum.mid"),
    "愛的夢": os.path.join(MIDI_SHEETS_DIR, "liebestraum.mid"),
    "愛之夢 第三號": os.path.join(MIDI_SHEETS_DIR, "liebestraum.mid"),
    "liebestraum": os.path.join(MIDI_SHEETS_DIR, "liebestraum.mid"),
    "liebestraum-1": os.path.join(MIDI_SHEETS_DIR, "Liebestraum-1.mid"),
    "liebestraum-1.mid": os.path.join(MIDI_SHEETS_DIR, "Liebestraum-1.mid"),
    "liebestraum.mid": os.path.join(MIDI_SHEETS_DIR, "liebestraum.mid"),

    # 冬風 (Winter Wind)
    "冬風練習曲": os.path.join(MIDI_SHEETS_DIR, "winter_wind.mid"),
    "冬風": os.path.join(MIDI_SHEETS_DIR, "winter_wind.mid"),
    "winter wind": os.path.join(MIDI_SHEETS_DIR, "winter_wind.mid"),
    "winter_wind": os.path.join(MIDI_SHEETS_DIR, "winter_wind.mid"),
    "winter_wind.mid": os.path.join(MIDI_SHEETS_DIR, "winter_wind.mid"),

    # 少女的祈禱 (Maiden's Prayer)
    "少女的祈禱": os.path.join(MIDI_SHEETS_DIR, "maidens_prayer.mid"),
    "少女祈禱": os.path.join(MIDI_SHEETS_DIR, "maidens_prayer.mid"),
    "maiden's prayer": os.path.join(MIDI_SHEETS_DIR, "maidens_prayer.mid"),
    "maidens prayer": os.path.join(MIDI_SHEETS_DIR, "maidens_prayer.mid"),
    "maidens_prayer.mid": os.path.join(MIDI_SHEETS_DIR, "maidens_prayer.mid"),

    # 幻想即興曲 (Fantaisie-Impromptu)
    "幻想即興曲": os.path.join(MIDI_SHEETS_DIR, "fantaisie_impromptu.mid"),
    "fantaisie impromptu": os.path.join(MIDI_SHEETS_DIR, "fantaisie_impromptu.mid"),
    "fantaisie_impromptu.mid": os.path.join(MIDI_SHEETS_DIR, "fantaisie_impromptu.mid"),

    # Rush E
    "rush e": os.path.join(MIDI_SHEETS_DIR, "Rush-Rush.mid"),
    "rushe": os.path.join(MIDI_SHEETS_DIR, "Rush-Rush.mid"),
    "rush": os.path.join(MIDI_SHEETS_DIR, "Rush-Rush.mid"),
    "rush-rush.mid": os.path.join(MIDI_SHEETS_DIR, "Rush-Rush.mid"),

    # 卡農 (Canon in D)
    "卡農": os.path.join(MIDI_SHEETS_DIR, "canon_in_d.mid"),
    "canon in d": os.path.join(MIDI_SHEETS_DIR, "canon_in_d.mid"),
    "canon_in_d.mid": os.path.join(MIDI_SHEETS_DIR, "canon_in_d.mid"),

    # 給愛麗絲 (Für Elise)
    "給愛麗絲": os.path.join(MIDI_SHEETS_DIR, "Bagatella Fur Elise.mid"),
    "致愛麗絲": os.path.join(MIDI_SHEETS_DIR, "Bagatella Fur Elise.mid"),
    "fur elise": os.path.join(MIDI_SHEETS_DIR, "Bagatella Fur Elise.mid"),
    "bagatella fur elise.mid": os.path.join(MIDI_SHEETS_DIR, "Bagatella Fur Elise.mid"),

    # 神隱少女 (Spirited Away)
    "神隱少女": os.path.join(MIDI_SHEETS_DIR, "Spirited Away - Boiler Mushi.mid"),
    "千與千尋": os.path.join(MIDI_SHEETS_DIR, "Spirited Away - Boiler Mushi.mid"),
    "spirited away": os.path.join(MIDI_SHEETS_DIR, "Spirited Away - Boiler Mushi.mid"),
    "boiler mushi": os.path.join(MIDI_SHEETS_DIR, "Spirited Away - Boiler Mushi.mid"),
    "spirited away - boiler mushi.mid": os.path.join(MIDI_SHEETS_DIR, "Spirited Away - Boiler Mushi.mid"),
}

def resolve_local_midi_file(song_query: str) -> Tuple[Optional[str], str]:
    """100% 優先在本機 midi_sheets 資料夾中深度智能查找最相符的 MIDI 檔案。
    支援中文曲名、英文名、作曲家、檔案名稱、標籤與模糊包含比對。
    """
    clean_q = song_query.strip().lower()
    if not clean_q:
        return None, ""
        
    # 1. 第一優先：精準比對 AUTHENTIC_MIDI_MAP
    if clean_q in AUTHENTIC_MIDI_MAP:
        p = AUTHENTIC_MIDI_MAP[clean_q]
        if os.path.exists(p):
            return p, clean_q

    for k_midi, path_midi in AUTHENTIC_MIDI_MAP.items():
        if k_midi.lower() in clean_q or clean_q in k_midi.lower():
            if os.path.exists(path_midi):
                return path_midi, k_midi

    # 2. 第二優先：直接掃描 midi_sheets 資料夾內的所有真實 .mid 檔案
    if os.path.exists(MIDI_SHEETS_DIR):
        local_files = [f for f in os.listdir(MIDI_SHEETS_DIR) if f.lower().endswith(('.mid', '.midi'))]
        
        # 2.1 檔名完全相等 / 去副檔名相等
        for f in local_files:
            f_stem = os.path.splitext(f)[0].lower()
            if clean_q == f.lower() or clean_q == f_stem:
                return os.path.join(MIDI_SHEETS_DIR, f), f_stem

        # 2.2 檔名子字串包含比對
        for f in local_files:
            f_lower = f.lower()
            f_stem = os.path.splitext(f)[0].lower()
            if clean_q in f_lower or f_stem in clean_q:
                return os.path.join(MIDI_SHEETS_DIR, f), f_stem
                
        # 2.3 分詞包含比對 (如 "fur elise" in "Bagatella Fur Elise.mid")
        words = clean_q.replace('-', ' ').replace('_', ' ').split()
        for f in local_files:
            f_norm = f.lower().replace('-', ' ').replace('_', ' ')
            if all(w in f_norm for w in words if len(w) >= 2):
                return os.path.join(MIDI_SHEETS_DIR, f), os.path.splitext(f)[0]

    return None, ""

AUTONOMOUS_PIANO_SEEDS = [
    "李斯特 鐘", "愛之夢", "冬風練習曲", "月光奏鳴曲 第三樂章",
    "少女的祈禱", "幻想即興曲", "Castle in the Sky", "Merry Go Round of Life", 
    "Spirited Away", "Chopin Nocturne", "Clair de Lune", "Rondo Alla Turca", 
    "Fur Elise", "Interstellar", "River Flows in You"
]

async def play_piano_worker(song_title: str, sheet_text: str, bpm: int, mode: str, midi_file: str = None, session_id: int = 0):
    """背景鋼琴演奏與 Live2D 姿態連動協程 (自動喚出視覺化 88 鍵瀑布流視窗並支援 Session ID 隔離)"""
    global is_piano_active, current_piano_song_title, current_piano_process, current_ai_state, GLOBAL_VTS, PIANO_SESSION_ID
    if session_id != PIANO_SESSION_ID:
        return
        
    try:
        is_piano_active = True
        current_piano_song_title = song_title
        current_ai_state = "PIANO"
        
        # 1. 走位到鋼琴位置
        await move_vts_spatial(target_pos="鋼琴旁", duration=1.5)
        
        if session_id != PIANO_SESSION_ID or not is_piano_active:
            return
            
        # 2. 切換表情
        if GLOBAL_VTS:
            await set_vts_expression(GLOBAL_VTS, "星星眼")
            
        # 3. 更新字幕
        await asyncio.to_thread(update_subtitle, f"🎹 [7L 正在演奏鋼琴] 《{song_title}》")
        
        # 4. 自動喚出 88 鍵視覺化瀑布流鋼琴介面並進行古典演奏
        if midi_file and os.path.exists(midi_file):
            log_print(f"🎹 [鋼琴舞台] 啟動 88 鍵瀑布流鋼琴視覺化視窗: 《{song_title}》 ({midi_file})")
            if current_piano_process and current_piano_process.poll() is None:
                try:
                    current_piano_process.terminate()
                except Exception:
                    pass
                current_piano_process = None
                
            current_piano_process = subprocess.Popen([
                sys.executable, 
                "test_virtual_piano.py", 
                "--midi", midi_file, 
                "--title", song_title, 
                "--auto-close"
            ])
            
            # 等待鋼琴視窗自然演奏完畢或被叫停
            while session_id == PIANO_SESSION_ID and is_piano_active:
                if current_piano_process.poll() is not None:
                    break
                await asyncio.sleep(0.3)
        else:
            # 5. 文字樂譜備用解析演奏
            tokens = parse_vp_sheet(sheet_text, base_bpm=bpm, note_mode=mode)
            log_print(f"🎹 [鋼琴舞台] 開始演奏文字譜《{song_title}》 (共 {len(tokens)} 音符/拍子, BPM: {bpm})")
            
            for token_type, payload, duration in tokens:
                if session_id != PIANO_SESSION_ID or not is_piano_active: break
                if token_type == 'note':
                    play_piano_note(payload)
                    await asyncio.to_thread(precise_sleep, duration)
                elif token_type == 'chord':
                    play_piano_note(payload)
                    await asyncio.to_thread(precise_sleep, duration)
                elif token_type == 'rest':
                    await asyncio.to_thread(precise_sleep, duration)
                    
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log_print(f"❌ [鋼琴演奏異常]: {e}")
    finally:
        if session_id == PIANO_SESSION_ID:
            is_piano_active = False
            current_piano_song_title = ""
            if current_piano_process and current_piano_process.poll() is None:
                try:
                    current_piano_process.terminate()
                except Exception:
                    pass
                current_piano_process = None
            if SOUND_ENGINE:
                SOUND_ENGINE.all_notes_off()
            if GLOBAL_VTS:
                await set_vts_expression(GLOBAL_VTS, "_RESET_")
            if current_ai_state == "PIANO":
                current_ai_state = "IDLE"
            await asyncio.to_thread(update_subtitle, "")
            log_print(f"🎹 [鋼琴舞台] 《{song_title}》演奏完畢！")

import bitmidi_engine

async def play_virtual_piano(song_name: str = "", custom_sheet: str = "") -> str:
    """讓 7L 在老爸面前彈奏 88 鍵鋼琴名曲（100% 優先使用本機原版五線譜與 BitMidi 雲端百萬曲庫）。
    
    Args:
        song_name: 想點播的鋼琴曲名稱、作曲家或動漫名（如：'月光'、'鐘'、'La Campanella'、'愛之夢'、'冬風'、'少女的祈禱'、'幻想即興曲'、'卡農'、'Rush E'、'給愛麗絲'、'神隱少女'）。
        custom_sheet: (可選) 自訂備用樂譜。
    """
    global current_piano_task, PIANO_SESSION_ID, is_piano_active, current_piano_song_title
    init_piano_synthesizer()
    
    target_title = "鋼琴名曲"
    target_midi = None
    
    clean_q = song_name.strip() if song_name else ""
    
    if clean_q:
        # 1. 🌟 第一優先：100% 優先查找本機 midi_sheets 資料夾中所有已存在的 .mid 檔案 (零延遲、杜絕超時)
        local_p, matched_title = resolve_local_midi_file(clean_q)
        if local_p and os.path.exists(local_p):
            target_midi = local_p
            target_title = matched_title
            log_print(f"🎹 [7L 鋼琴曲庫] 命中本機 MIDI 曲庫: 《{target_title}》 ({target_midi})")
        else:
            # 2. 本機確實不存在時，才向 BitMidi (https://bitmidi.com) 雲端搜尋並下載
            log_print(f"🌐 [7L 鋼琴曲庫] 本機未收錄《{clean_q}》，正在向 BitMidi 雲端曲庫搜尋並下載...")
            dl_path = await asyncio.to_thread(bitmidi_engine.fetch_and_download_first_match, clean_q, MIDI_SHEETS_DIR)
            if dl_path and os.path.exists(dl_path):
                target_midi = dl_path
                target_title = os.path.basename(dl_path).replace('.mid', '').replace('.MID', '')
                log_print(f"✅ [7L 鋼琴曲庫] 已從 BitMidi 成功獲取原版 MIDI: 《{target_title}》")
                AUTHENTIC_MIDI_MAP[clean_q] = dl_path
    else:
        # 3. 未指定特定歌名時，隨機選取一首本機精選名曲
        preset_names = ["李斯特 鐘", "愛之夢", "月光奏鳴曲 第三樂章", "冬風練習曲", "少女的祈禱", "幻想即興曲", "卡農", "給愛麗絲", "Rush E", "神隱少女"]
        target_title = random.choice(preset_names)
        target_midi, _ = resolve_local_midi_file(target_title)

    # 🛑 自省防重啟鐵律：若當前已經在演奏老爸點播的曲目，維持流暢彈奏，絕不重複重啟視窗！
    if is_piano_active and current_piano_song_title and target_title:
        if clean_q and (clean_q in current_piano_song_title.lower() or current_piano_song_title.lower() in clean_q or target_title.lower() == current_piano_song_title.lower()):
            log_print(f"🎹 [7L 鋼琴曲庫] 7L 目前正在為老爸演奏《{current_piano_song_title}》，保持沉醉演奏狀態。")
            return f"7L 現在正專心為老爸彈奏《{current_piano_song_title}》中喔！請老爸好好聆聽享受～"

    if not target_midi or not os.path.exists(target_midi):
        log_print(f"⚠️ [7L 鋼琴曲庫] 未找到《{clean_q}》的五線譜檔案。")
        return f"抱歉老爸，目前在曲庫中沒有找到《{clean_q}》的五線譜檔案喔！"
        
    PIANO_SESSION_ID += 1
    session_id = PIANO_SESSION_ID
    is_piano_active = True
    current_piano_song_title = target_title
    
    if current_piano_task and not current_piano_task.done():
        current_piano_task.cancel()
        
    current_piano_task = asyncio.create_task(
        play_piano_worker(
            song_title=target_title,
            sheet_text="",
            bpm=180,
            mode="16th",
            midi_file=target_midi,
            session_id=session_id
        )
    )
    return f"好喔，7L 這就坐到鋼琴前為老爸演奏《{target_title}》！[EXPRESSION: 星星眼]"

def control_microphone(is_enabled: bool) -> str:
    """控制 7L 的麥克風收音開關（開啟或靜音）。
    
    Args:
        is_enabled: True 為開啟麥克風收音，False 為關閉麥克風（靜音）。
    """
    global IS_MIC_ENABLED
    IS_MIC_ENABLED = is_enabled
    state_str = "開啟" if is_enabled else "關閉 (靜音)"
    log_print(f"🎙️ [麥克風控制] 已{state_str}麥克風收音。")
    return f"麥克風已成功{state_str}囉！"

async def clear_all_memories() -> str:
    """清空 7L 與老爸的所有雲端與本機記憶對話紀錄。"""
    global db
    if db is not None:
        try:
            await db.collection("channel_history").document(DEFAULT_CHANNEL_ID).delete()
            await db.collection("channel_meta").document(DEFAULT_CHANNEL_ID).delete()
            await db.collection("user_memory").document(DEFAULT_CHANNEL_ID).delete()
        except Exception:
            pass
    for fp in [f"memory_{DEFAULT_CHANNEL_ID}.json", "user_profile_local.json"]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass
    log_print("🧹 [系統] 雲端與本地所有記憶已徹底重置！")
    return "記憶已經徹底清空囉，我們重新開始吧！"

def search_internet(query):
    return search_google(query)

GENAI_TOOLS = [
    trigger_vts_expression, search_google, execute_local_python_code, 
    generate_ai_image, move_spatial_position, 
    sing_song, stop_singing, list_songs,
    play_virtual_piano, stop_virtual_piano, list_piano_sheets,
    control_microphone, clear_all_memories
]

# ────────────────────────────────────────────────────────
# 🛡️ 9. 防跳針與記憶去重系統 (Code-Level Anti-Repetition)
# ────────────────────────────────────────────────────────
RECENT_BOT_MESSAGES = []
LAST_TTS_END_TIME = 0.0

def normalize_text_for_echo(t: str) -> str:
    if not t: return ""
    clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', t).strip().lower()
    clean = clean.replace("爸爸", "老爸").replace("阿爸", "老爸").replace("拔拔", "老爸").replace("老爹", "老爸")
    clean = clean.replace("妳", "你")
    return clean

def record_bot_message(msg: str):
    global RECENT_BOT_MESSAGES
    clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', msg).strip()
    if clean:
        RECENT_BOT_MESSAGES.append(clean)
        if len(RECENT_BOT_MESSAGES) > 30:
            RECENT_BOT_MESSAGES.pop(0)

def is_too_similar_to_recent(text: str, threshold: float = 0.48) -> bool:
    """🛡️ 程式碼層級最高防跳針攔截器：比對近期 15 句歷史發話相似度"""
    global RECENT_BOT_MESSAGES
    clean_current = re.sub(r'[^\w\u4e00-\u9fa5]', '', text).strip()
    if not clean_current or len(clean_current) < 3:
        return False
    for old_msg in RECENT_BOT_MESSAGES[-15:]:
        if clean_current == old_msg or clean_current in old_msg or old_msg in clean_current:
            return True
        ratio = difflib.SequenceMatcher(None, clean_current, old_msg).ratio()
        if ratio >= threshold:
            return True
    return False

def is_voice_echo(stt_text: str) -> bool:
    """🛡️ 毫米級全方位回音過濾防線：精準比對 7L 自身的近期發話與揚聲器殘留混響"""
    global RECENT_BOT_MESSAGES, LAST_TTS_END_TIME
    
    clean_stt = normalize_text_for_echo(stt_text)
    if not clean_stt:
        return False
        
    # 1. 殘留混響防線：若 TTS 發話剛結束 1.2 秒內，且長度很短或有任何交集，一律判定為喇叭殘響回音
    time_since_tts = time.time() - LAST_TTS_END_TIME
    if time_since_tts < 1.2:
        if len(clean_stt) <= 6:
            return True
            
    if not RECENT_BOT_MESSAGES:
        return False

    recent_pool = [normalize_text_for_echo(m) for m in RECENT_BOT_MESSAGES[-8:] if m]
    combined_recent = "".join(recent_pool)
    
    # 2. 精準子字串包含比對 (例如 "爸爸突然" -> "老爸突然" in "老爸突然說這種話...")
    if len(clean_stt) >= 2:
        if clean_stt in combined_recent:
            return True
        for m in recent_pool:
            if clean_stt in m or m in clean_stt:
                return True

    # 3. 2-gram 字符雙字詞交集重疊率比對 (解決語音 STT 聽錯 1-2 字的問題，如 "好想戀情" vs "好想練琴")
    if len(clean_stt) >= 3:
        stt_bigrams = {clean_stt[i:i+2] for i in range(len(clean_stt)-1)}
        if stt_bigrams:
            recent_bigrams = set()
            for m in recent_pool:
                recent_bigrams.update({m[i:i+2] for i in range(len(m)-1)})
            overlap = stt_bigrams.intersection(recent_bigrams)
            if len(overlap) / len(stt_bigrams) >= 0.35:
                return True

    # 4. 最長連續匹配度比對
    matcher = difflib.SequenceMatcher(None, clean_stt, combined_recent)
    match = matcher.find_longest_match(0, len(clean_stt), 0, len(combined_recent))
    if match.size >= 3 and (match.size / len(clean_stt) >= 0.45 or match.size >= 4):
        return True
    if len(clean_stt) >= 4 and matcher.ratio() > 0.35:
        return True

    return False

# ────────────────────────────────────────────────────────
# 🔊 10. 語音合成、音訊分析與字幕工具
# ────────────────────────────────────────────────────────
def _remove_temp_mp3():
    for f in glob.glob("temp_reply_*.mp3"):
        try: os.remove(f)
        except Exception: pass

def update_subtitle(text):
    try:
        if not text:
            wrapped_text = ""
        else:
            lines = str(text).replace("\r\n", "\n").split("\n")
            formatted_lines = []
            for line in lines:
                if not line:
                    formatted_lines.append("")
                else:
                    formatted_lines.extend([line[i:i+20] for i in range(0, len(line), 20)])
            wrapped_text = "\n".join(formatted_lines)
        with open("subtitle.txt", "w", encoding="utf-8") as f:
            f.write(wrapped_text)
    except Exception:
        pass

async def play_voice_complete(text):
    global current_ai_state, RECENT_BOT_MESSAGES, LAST_TTS_END_TIME
    if not text: return

    # 🌟 每一句 7L 發出的聲音，立刻記錄至防回音與防跳針記憶池
    record_bot_message(text)

    try:
        _remove_temp_mp3()
        voice = "zh-CN-XiaoyiNeural" 
        output_file = f"temp_reply_{int(time.time() * 1000)}_{random.randint(100, 999)}.mp3"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception: pass

        await asyncio.to_thread(update_subtitle, text)
        pygame.mixer.init(frequency=44100)
        pygame.mixer.music.load(output_file)
        pygame.mixer.music.set_volume(1.0)
        
        current_ai_state = "TALKING"
        pygame.mixer.music.play()
        
        await asyncio.sleep(0.2)
        while pygame.mixer.music.get_busy(): 
            await asyncio.sleep(0.1)
            
        pygame.mixer.stop()
        pygame.mixer.music.unload()
        LAST_TTS_END_TIME = time.time()
        await asyncio.to_thread(update_subtitle, "")
            
    except asyncio.CancelledError:
        try: pygame.mixer.music.stop()
        except: pass
        LAST_TTS_END_TIME = time.time()
        if current_ai_state == "TALKING": current_ai_state = "IDLE"
        raise
    except Exception as e:
        log_print(f"❌ [語音合成錯誤]: {e}")
        LAST_TTS_END_TIME = time.time()
        if current_ai_state == "TALKING": current_ai_state = "IDLE"

def record_system_audio(duration=4, filename="temp_system_audio.wav"):
    try:
        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        with mic.recorder(samplerate=44100) as recorder:
            data = recorder.record(numframes=44100 * duration)
        audio_int16 = (data * 32767).astype(np.int16)
        with wave.open(filename, 'w') as wf:
            wf.setnchannels(audio_int16.shape[1] if len(audio_int16.shape) > 1 else 1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(audio_int16.tobytes())
        with open(filename, "rb") as f:
            encoded_audio = base64.b64encode(f.read()).decode('utf-8')
        if os.path.exists(filename): os.remove(filename)
        return encoded_audio
    except Exception: return None

def transcribe_wav_file(filename):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(filename) as source:
            audio = r.record(source)
        text = r.recognize_google(audio, language="zh-TW")
        return text.strip()
    except Exception:
        return ""
    finally:
        if os.path.exists(filename):
            try: os.remove(filename)
            except: pass

# ────────────────────────────────────────────────────────
# 👁️ 11. 視覺感知、畫面截圖與輕量眼角餘光
# ────────────────────────────────────────────────────────
has_printed_vision_error = False

CURSOR_ICON_CACHE = None

def get_realistic_cursor_icon():
    """動態生成高解析度、邊緣銳利之 Windows 原生滑鼠游標圖標 (含柔和陰影與黑白分明邊界)"""
    global CURSOR_ICON_CACHE
    if CURSOR_ICON_CACHE is not None:
        return CURSOR_ICON_CACHE
    try:
        from PIL import Image, ImageDraw
        cursor = Image.new('RGBA', (40, 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(cursor)
        
        # 經典 Windows 箭頭頂點座標
        poly = [(0, 0), (0, 24), (6, 19), (11, 29), (15, 27), (10, 17), (18, 17)]
        
        # 1. 柔和環境陰影 (暗透明度)
        shadow_poly = [(x + 2, y + 2) for x, y in poly]
        draw.polygon(shadow_poly, fill=(0, 0, 0, 120))
        
        # 2. 黑色外圈清晰描邊
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                draw.polygon([(x + dx, y + dy) for x, y in poly], fill=(0, 0, 0, 255))
                
        # 3. 純白箭頭本體
        draw.polygon(poly, fill=(255, 255, 255, 255))
        
        CURSOR_ICON_CACHE = cursor
        return cursor
    except Exception:
        return None

def capture_screen_multi_view():
    """
    五方多視角超高清螢幕感知系統：
    1. 🖥️ 全螢幕全景總覽圖 (含原生真實滑鼠游標貼圖)
    2. 🔍 左上象限 4K 原生細節放大圖 (Top-Left)
    3. 🔍 右上象限 4K 原生細節放大圖 (Top-Right)
    4. 🔍 左下象限 4K 原生細節放大圖 (Bottom-Left)
    5. 🔍 右下象限 4K 原生細節放大圖 (Bottom-Right)
    """
    global has_printed_vision_error
    try:
        from PIL import ImageDraw, Image, ImageGrab
        import io
        
        screenshot = None
        try:
            screenshot = ImageGrab.grab(all_screens=True)
        except Exception:
            try:
                screenshot = ImageGrab.grab()
            except Exception:
                try:
                    screenshot = pyautogui.screenshot()
                except Exception:
                    pass
                    
        if screenshot is None:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            hdesk = user32.GetDesktopWindow()
            desk_dc = user32.GetWindowDC(hdesk)
            img_dc = gdi32.CreateCompatibleDC(desk_dc)
            mem_bmp = gdi32.CreateCompatibleBitmap(desk_dc, w, h)
            gdi32.SelectObject(img_dc, mem_bmp)
            gdi32.BitBlt(img_dc, 0, 0, w, h, desk_dc, 0, 0, 0x00CC0020)
            
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_int32), ('biHeight', ctypes.c_int32),
                    ('biPlanes', ctypes.c_uint16), ('biBitCount', ctypes.c_uint16), ('biCompression', ctypes.c_uint32),
                    ('biSizeImage', ctypes.c_uint32), ('biXPelsPerMeter', ctypes.c_int32), ('biYPelsPerMeter', ctypes.c_int32),
                    ('biClrUsed', ctypes.c_uint32), ('biClrImportant', ctypes.c_uint32)
                ]
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(img_dc, mem_bmp, 0, h, buf, ctypes.byref(bmi), 0)
            screenshot = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
            gdi32.DeleteObject(mem_bmp)
            gdi32.DeleteDC(img_dc)
            user32.ReleaseDC(hdesk, desk_dc)

        if screenshot.mode != "RGB":
            screenshot = screenshot.convert("RGB")
            
        w, h = screenshot.size
        mx, my = pyautogui.position()
        
        # 🖱️ 自然貼合原生真實滑鼠游標圖標 (絕非生硬十字準星)
        cursor_icon = get_realistic_cursor_icon()
        if cursor_icon:
            try:
                screenshot.paste(cursor_icon, (max(0, min(w - 1, mx)), max(0, min(h - 1, my))), cursor_icon)
            except Exception:
                pass
        
        # 1. 全螢幕全景總覽圖 (限制在 1920x1080 內保持極速傳輸)
        overview_img = screenshot.copy()
        if w > 1920 or h > 1080:
            overview_img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
        buf_full = io.BytesIO()
        overview_img.save(buf_full, format="JPEG", quality=75)
        full_b64 = base64.b64encode(buf_full.getvalue()).decode('utf-8')
        
        # 2. 四個象限的原生高清細節裁切
        mid_x = w // 2
        mid_y = h // 2
        
        # 左上象限
        buf_tl = io.BytesIO()
        screenshot.crop((0, 0, mid_x, mid_y)).save(buf_tl, format="JPEG", quality=80)
        tl_b64 = base64.b64encode(buf_tl.getvalue()).decode('utf-8')
        
        # 右上象限
        buf_tr = io.BytesIO()
        screenshot.crop((mid_x, 0, w, mid_y)).save(buf_tr, format="JPEG", quality=80)
        tr_b64 = base64.b64encode(buf_tr.getvalue()).decode('utf-8')
        
        # 左下象限
        buf_bl = io.BytesIO()
        screenshot.crop((0, mid_y, mid_x, h)).save(buf_bl, format="JPEG", quality=80)
        bl_b64 = base64.b64encode(buf_bl.getvalue()).decode('utf-8')
        
        # 右下象限
        buf_br = io.BytesIO()
        screenshot.crop((mid_x, mid_y, w, h)).save(buf_br, format="JPEG", quality=80)
        br_b64 = base64.b64encode(buf_br.getvalue()).decode('utf-8')
        
        has_printed_vision_error = False
        return [
            ("🖥️【1. 全螢幕全景總覽（含滑鼠游標）】", full_b64),
            ("🔍【2. 左上角細節放大圖】", tl_b64),
            ("🔍【3. 右上角細節放大圖】", tr_b64),
            ("🔍【4. 左下角細節放大圖】", bl_b64),
            ("🔍【5. 右下角細節放大圖】", br_b64)
        ]
    except Exception as e:
        if not has_printed_vision_error:
            print(f"\n❌ [截圖系統報錯]: {e}")
            has_printed_vision_error = True
        return None

def capture_screen_as_base64():
    return capture_screen_multi_view()

async def get_lightweight_gemini_vision(image_base64):
    """輕量級雲端餘光 (完全取代本地 Ollama，0% 本地 CPU 負載)"""
    channels = get_available_gemini_channels(limit=1, is_proactive=True)
    if not channels:
        return ""
        
    g_key, g_model, target_id = channels[0]
    try:
        image_bytes = base64.b64decode(image_base64)
        temp_client = genai.Client(api_key=g_key)
        
        prompt = "請用 2 句以內，詳細地描述這個螢幕畫面上正在顯示什麼（畫面上的滑鼠游標代表使用者當前的焦點位置）："
        
        chat_contents = [
            types.Content(role="user", parts=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            ])
        ]
        
        response = await temp_client.aio.models.generate_content(
            model=g_model,
            contents=chat_contents,
            config=types.GenerateContentConfig(
                temperature=0.8,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        
        if response.text:
            return response.text.strip()
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "rate limit" in err_str or "resource" in err_str or "quota" in err_str:
            lock_target(target_id, str(e))
        elif "404" in err_str or "not_found" in err_str or "no longer available" in err_str:
            if 'DEAD_GEMINI_MODELS' in globals():
                DEAD_GEMINI_MODELS.add(g_model)
            lock_target(target_id, "404 not found")
        else:
            lock_target(target_id, "wait 30s")
            
    return ""

async def get_ollama_vision_description(image_base64, model_name="minicpm-v"):
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": "請用 2 句以內，詳細地描述這個螢幕畫面上正在顯示什麼（注意：圖片上的「洋紅色十字與綠色圓圈」代表使用者目前的滑鼠游標位置）：", 
                "images": [image_base64]
            }
        ],
        "stream": False
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=20.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "").strip()
    except Exception:
        pass
    return ""

# ────────────────────────────────────────────────────────
# 🧠 12. 大腦推理核心 (fetch_ai_response)
# ────────────────────────────────────────────────────────
async def fetch_ai_response(messages, image_base64=None, audio_base64=None, is_proactive=False, request_start_time: Optional[float] = None):
    global current_ai_status_str, current_model_tag
    used_eye = "無"
    overall_start_time = request_start_time if request_start_time else time.time()

    # 防卡死機制：讓渡運算權，確保皮套滑順
    await asyncio.sleep(0.05)

    # 🌟 第一防線：主力 Gemini 旗艦大腦 (支援 Function Calling 工具調用與視覺/對話一體化)
    max_gemini_attempts = 45 
    gemini_attempt = 0
    
    # 提取最新的使用者指令以供智能任務分流
    user_query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            c = msg.get("content", "")
            if isinstance(c, str):
                user_query = c
            elif isinstance(c, list):
                user_query = " ".join([p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"])
            break
            
    while gemini_attempt < max_gemini_attempts:
        await asyncio.sleep(0.01)  # 讓渡執行權，防止高頻重試/切換時凍結 Live2D 動作幀
        channels = get_available_gemini_channels(limit=1, user_query=user_query, has_image=bool(image_base64), is_proactive=is_proactive)
        if not channels:
            break 
            
        g_key, g_model, target_id = channels[0]
        status_prefix = "👁️🧠" if image_base64 else "🧠"
        current_ai_status_str = f"{status_prefix} {g_model} [{target_id}] 思考中..."
        
        chat_contents = []
        system_text = ""
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n\n"
                
        for msg in messages:
            if msg["role"] == "system": continue
            
            raw_content = msg["content"]
            if isinstance(raw_content, list):
                text = " ".join([p["text"] for p in raw_content if p.get("type") == "text"])
            else:
                text = raw_content
                
            if not chat_contents and system_text:
                text = system_text + text
                
            role = "user" if msg["role"] == "user" else "model"
            chat_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
        
        try:
            if image_base64:
                user_parts = []
                if isinstance(image_base64, list):
                    for item in image_base64:
                        if isinstance(item, tuple):
                            label, img_b64 = item
                            img_bytes = base64.b64decode(img_b64)
                            user_parts.append(types.Part.from_text(text=f"\n{label}："))
                            user_parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
                        else:
                            user_parts.append(types.Part.from_bytes(data=base64.b64decode(item), mime_type="image/jpeg"))
                else:
                    image_bytes = base64.b64decode(image_base64)
                    user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

                if user_parts:
                    if chat_contents and chat_contents[-1].role == "user":
                        chat_contents[-1].parts.extend(user_parts)
                    else:
                        chat_contents.append(types.Content(role="user", parts=user_parts))

            # 🎙️ 原生音訊多模態直連：將原始音訊 (WAV) 直接送入 Gemini 旗艦大腦
            if audio_base64:
                try:
                    if isinstance(audio_base64, str):
                        raw_audio_bytes = base64.b64decode(audio_base64)
                    else:
                        raw_audio_bytes = audio_base64
                    
                    audio_part = types.Part.from_bytes(data=raw_audio_bytes, mime_type="audio/wav")
                    if chat_contents and chat_contents[-1].role == "user":
                        chat_contents[-1].parts.append(audio_part)
                    else:
                        chat_contents.append(types.Content(role="user", parts=[audio_part]))
                except Exception as e_aud:
                    log_print(f"⚠️ [音訊多模態封裝異常]: {e_aud}")

            temp_google_client = genai.Client(api_key=g_key)
            # 🌟 不人為限制思考秒數：允許旗艦模型充份進行 5 視角視覺觀察與深度思考推理，只要沒回傳錯誤就代表正在思考！
            api_call_start = time.time()
            response = await temp_google_client.aio.models.generate_content(
                model=g_model,
                contents=chat_contents,
                config=types.GenerateContentConfig(
                    temperature=0.85,
                    tools=GENAI_TOOLS,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            
            extracted_text = ""
            if hasattr(response, 'function_calls') and response.function_calls:
                for fc in response.function_calls:
                    fn_name = getattr(fc, 'name', '')
                    fn_args = getattr(fc, 'args', {}) or {}
                    if fn_name == "trigger_vts_expression":
                        exp_name = fn_args.get("expression_name", "")
                        extracted_text += f" [EXPRESSION: {exp_name}]"
                    elif fn_name == "search_google":
                        q = fn_args.get("query", "")
                        res = search_google(q)
                        extracted_text += f" (搜尋到：{res})"
                    elif fn_name == "generate_ai_image":
                        p = fn_args.get("prompt", "")
                        asyncio.create_task(generate_ai_image(p))
                        extracted_text += f" 好的，我為老爸畫了這張圖！"
                    elif fn_name == "execute_local_python_code":
                        c = fn_args.get("code_string", "")
                        asyncio.create_task(execute_local_python_code(c))
                        extracted_text += f" 已經在螢幕上執行了！"
                    elif fn_name == "move_spatial_position":
                        t_pos = fn_args.get("target_position", "自由漫遊")
                        sf = fn_args.get("scale_factor")
                        asyncio.create_task(apply_spatial_position(
                            position_name=t_pos, 
                            scale_factor=sf,
                            duration=2.0
                        ))
                        extracted_text += f" 好的，7L 已經回到{t_pos}囉！"
                    elif fn_name == "sing_song":
                        s_name = fn_args.get("song_name", "")
                        sing_res = await sing_song(s_name)
                        extracted_text += f" {sing_res}"
                    elif fn_name == "stop_singing":
                        stop_res = await stop_singing()
                        extracted_text += f" {stop_res}"
                    elif fn_name == "list_songs":
                        l_res = list_songs()
                        extracted_text += f" {l_res}"
                    elif fn_name == "play_virtual_piano":
                        s_name = fn_args.get("song_name", "")
                        c_sheet = fn_args.get("custom_sheet", "")
                        p_res = await play_virtual_piano(s_name, c_sheet)
                        extracted_text += f" {p_res}"
                    elif fn_name == "stop_virtual_piano":
                        sp_res = await stop_virtual_piano()
                        extracted_text += f" {sp_res}"
                    elif fn_name == "list_piano_sheets":
                        lp_res = list_piano_sheets()
                        extracted_text += f" {lp_res}"
                    elif fn_name == "control_microphone":
                        is_en = fn_args.get("is_enabled", True)
                        mic_res = control_microphone(is_en)
                        extracted_text += f" {mic_res}"
                    elif fn_name == "clear_all_memories":
                        cm_res = await clear_all_memories()
                        extracted_text += f" {cm_res}"

            try:
                if response.text:
                    extracted_text = response.text.strip() + (" " + extracted_text if extracted_text else "")
            except Exception:
                pass

            if extracted_text.strip():
                # 🔄 成功調用後：自動推進輪詢指針至「下一把金鑰」，均勻分攤 20 把金鑰配額
                try:
                    if target_id.startswith("G") and GEMINI_KEYS:
                        used_idx = int(target_id.split("_")[0][1:])
                        CURRENT_GEMINI_KEY_INDEX = (used_idx + 1) % len(GEMINI_KEYS)
                except Exception:
                    pass

                api_duration = time.time() - api_call_start
                total_duration = time.time() - overall_start_time
                time_stat = f" [總耗時: {total_duration:.2f}s | 思考: {api_duration:.2f}s]"

                MODEL_FAIL_COUNT[g_model] = 0
                if image_base64 and audio_base64:
                    current_model_tag = f"🧠🎙️👁️ {g_model} (全模態){time_stat}"
                elif audio_base64:
                    current_model_tag = f"🧠🎙️ {g_model} (音訊直連){time_stat}"
                elif image_base64:
                    current_model_tag = f"🧠👁️ {g_model} (一體化){time_stat}"
                else:
                    current_model_tag = f"🧠 {g_model}{time_stat}"
                return extracted_text.strip()
        except Exception as e:
            err_str = str(e).lower()
            record_model_failure(g_model, err_str)
            
            # 精簡單行報錯輸出
            if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                lock_target(target_id, "503 high demand")
            elif "404" in err_str or "not_found" in err_str or "no longer available" in err_str:
                if 'DEAD_GEMINI_MODELS' in globals():
                    DEAD_GEMINI_MODELS.add(g_model)
                lock_entire_model(g_model, duration=get_seconds_until_pt_midnight(), reason="404 下架/未開通")
                lock_target(target_id, "404 not found")
            elif "429" in err_str or "rate limit" in err_str or "resource" in err_str or "quota" in err_str:
                lock_target(target_id, str(e))
            elif "timeouterror" in err_str or "timeout" in err_str:
                log_print(f"⏱️ [大腦逾時] 通道 {target_id} 回應超時 ➔ 秒切下一個通道")
                lock_target(target_id, "wait 30s")
            else:
                clean_err = str(e).replace('\n', ' ').strip()[:50]
                display_err = clean_err if clean_err else type(e).__name__
                log_print(f"⚠️ [大腦異常] 通道 {target_id}: {display_err} ➔ 切換中")
                lock_target(target_id, "wait 30s")
        
        gemini_attempt += 1

    # 🌟 第二防線：若 Gemini 旗艦大腦全部不可用且有畫面，嘗試輕量雲端餘光
    if image_base64:
        current_ai_status_str = "👁️ 備用視覺提取中 (雲端輕量版)..."
        local_desc = ""
        if not is_system_overloaded():
            try: 
                local_desc = await get_lightweight_gemini_vision(image_base64)
            except Exception: 
                pass
                
        if local_desc:
            used_eye = "gemini-lite"
            if messages and messages[-1]["role"] == "user": 
                inject_text = f"\n\n【備用視覺情報】：畫面描述: {local_desc}\n【鐵律】：畫面上程式產生的「洋紅色十字與綠色圓圈」是老爸的滑鼠游標。請注意：【除非滑鼠正在點擊或指著特別、有趣的東西，否則請完全忽略它，絕對不要一直報告滑鼠在哪裡！】嚴禁說出「洋紅/十字/圓圈」等形狀字眼。回應嚴控在 2 句以內！"
                
                if isinstance(messages[-1]["content"], list):
                    messages[-1]["content"].append({"type": "text", "text": inject_text})
                else:
                    messages[-1]["content"] += inject_text

    # 純文字多平台輪詢
    max_attempts = 35 
    attempt = 0
    success_result = None

    while attempt < max_attempts:
        await asyncio.sleep(0.01)  # 讓渡執行權，維持皮套追蹤 20 FPS 流暢度
        pools = get_available_text_pools(limit=1, is_proactive=is_proactive)
        if not pools:
            break

        pool, pool_id = pools[0]
        provider = pool["provider"]
        model_name = pool["model"]
        
        current_ai_status_str = f"🧠 {model_name} [{pool_id}] 思考中..."

        try:
            clean_messages = []
            for m in messages:
                c = m["content"]
                if isinstance(c, list):
                    c = " ".join([p["text"] for p in c if p.get("type") == "text"])
                clean_messages.append({"role": m["role"], "content": c})

            if provider == "groq":
                client = pool["core"]
                api_call_start = time.time()
                chat_completion = await client.chat.completions.create(
                    messages=clean_messages, 
                    model=model_name, 
                    temperature=0.9, 
                    max_tokens=150
                )
                if chat_completion.choices[0].message.content:
                    if pool_id.startswith("GR") and GROQ_CLIENTS:
                        try:
                            used_idx = int(pool_id.split("_")[0][2:])
                            CURRENT_TEXT_KEY_INDEX = (used_idx + 1) % len(GROQ_CLIENTS)
                        except Exception: pass
                    api_duration = time.time() - api_call_start
                    total_duration = time.time() - overall_start_time
                    time_stat = f" [總耗時: {total_duration:.2f}s | 思考: {api_duration:.2f}s]"
                    MODEL_FAIL_COUNT[model_name] = 0
                    success_result = chat_completion.choices[0].message.content.strip()
                    current_model_tag = f"🧠 {model_name}{time_stat}"
                    return success_result
                    
            elif provider == "google":
                g_key = pool["core"]
                chat_contents = []
                system_text = ""
                for msg in clean_messages:
                    if msg["role"] == "system":
                        system_text += msg["content"] + "\n\n"
                for msg in clean_messages:
                    if msg["role"] == "system": continue
                    text_msg = msg["content"]
                    if not chat_contents and system_text:
                        text_msg = system_text + text_msg
                    role = "user" if msg["role"] == "user" else "model"
                    chat_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text_msg)]))
                
                temp_google_client = genai.Client(api_key=g_key)
                gen_config = types.GenerateContentConfig(
                    temperature=0.85,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
                if "gemini" in model_name.lower():
                    gen_config.tools = GENAI_TOOLS

                api_call_start = time.time()
                response = await temp_google_client.aio.models.generate_content(
                    model=model_name,
                    contents=chat_contents,
                    config=gen_config
                )
                if response.text:
                    if pool_id.startswith("GO") and GEMINI_KEYS:
                        try:
                            used_idx = int(pool_id.split("_")[0][2:])
                            CURRENT_TEXT_KEY_INDEX = (used_idx + 1) % len(GEMINI_KEYS)
                        except Exception: pass
                    api_duration = time.time() - api_call_start
                    total_duration = time.time() - overall_start_time
                    time_stat = f" [總耗時: {total_duration:.2f}s | 思考: {api_duration:.2f}s]"
                    MODEL_FAIL_COUNT[model_name] = 0
                    success_result = response.text.strip()
                    current_model_tag = f"🧠 {model_name}{time_stat}"
                    return success_result

        except Exception as text_err:
            err_str = str(text_err).lower()
            record_model_failure(model_name, err_str)
            if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                lock_target(pool_id, "503 high demand")
            elif "429" in err_str or "rate limit" in err_str or "timeout" in err_str:
                lock_target(pool_id, err_str)
            else:
                clean_err = str(text_err).replace('\n', ' ')[:50]
                log_print(f"⚠️ [文字大腦] 通道 {pool_id}: {clean_err} ➔ 切換中")
                lock_target(pool_id, "wait 10s")

        attempt += 1

    current_model_tag = "⚠️ 系統超載"
    exhausted_responses = [
        "嗯... 系統目前所有文字通道都在忙線中，讓我稍微喘口氣喔！",
        "訊息稍微有點多呢，所有大腦都在排隊，請稍候兩秒再試！"
    ]
    return random.choice(exhausted_responses)

# ────────────────────────────────────────────────────────
# 🕹️ 13. 使用者指令、電腦控制與計時器動作
# ────────────────────────────────────────────────────────
def get_system_performance():
    try:
        cpu_usage = psutil.cpu_percent(interval=0.3)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        gpu_name = "未知顯示卡"
        
        result = subprocess.run(["wmic", "path", "win32_videocontroller", "get", "name"], capture_output=True, text=True, shell=True)
        lines = [line.strip() for line in result.stdout.split("\n") if line.strip() and "Name" not in line]
        if lines: gpu_name = lines[0]

        process_list = []
        for proc in psutil.process_iter(['name', 'memory_percent']):
            try:
                pinfo = proc.info
                ignore_list = ['svchost.exe', 'csrss.exe', 'wininit.exe', 'services.exe', 'lsass.exe', 'System Idle Process', 'System', 'Registry', 'smss.exe']
                if pinfo['name'] and pinfo['name'] not in ignore_list and pinfo['memory_percent'] is not None:
                    clean_name = pinfo['name'].replace('.exe', '')
                    process_list.append((clean_name, pinfo['memory_percent']))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        process_list.sort(key=lambda x: x[1], reverse=True)
        seen_apps = []
        for p_name, _ in process_list:
            if p_name not in seen_apps: seen_apps.append(p_name)
            if len(seen_apps) >= 3: break
            
        app_str = f"，目前佔用最多資源的軟體是：{', '.join(seen_apps)}" if seen_apps else ""
        return f"CPU 使用率: {cpu_usage}%, 記憶體: {memory_usage}%{app_str}"
    except Exception as e:
        return f"無法讀取系統狀態: {e}"

async def set_timer(seconds, message, input_queue):
    try:
        await asyncio.sleep(seconds)
        await input_queue.put(f"（系統鬧鐘提醒：時間到了！內容是：{message}。請溫柔地提醒使用者！）")
    except asyncio.CancelledError:
        pass
    finally:
        task = asyncio.current_task()
        if task in active_timers: active_timers.remove(task)

async def execute_actions(vts, text, input_queue):
    global active_timers, target_look_x, target_look_y, is_tracking_mouse, force_blink_trigger
    
    exp_match = re.search(r'\[EXPRESSION:\s*([^\]]+)\]', text, re.IGNORECASE)
    if exp_match:
        exp_tag = exp_match.group(1).strip()
        asyncio.create_task(set_vts_expression(vts, exp_tag))

    move_match = re.search(r'\[(?:MOVE|WINDOW|POSITION):\s*([^\]]+)\]', text, re.IGNORECASE)
    if move_match:
        pos_tag = move_match.group(1).strip()
        if not is_piano_active or any(k in pos_tag for k in ["鋼琴", "原本", "大小", "視窗"]):
            asyncio.create_task(apply_spatial_position(pos_tag))

    url_match = re.search(r'\[OPEN_BROWSER:\s*([^\]]+)\]', text, re.IGNORECASE)
    if url_match:
        url = url_match.group(1).strip()
        if not url.startswith('http'):
            url = 'https://' + url
        try:
            webbrowser.open(url)
            print(f"\n🌐 [系統動作] 7L 幫你打開了網頁: {url}")
        except Exception as e:
            print(f"\n❌ [開啟網頁失敗]: {e}")

    try:
        upper_text = text.upper()
        if "MOUSE" in upper_text and "LOOK" in upper_text: is_tracking_mouse = True
        elif "LEFT" in upper_text and "LOOK" in upper_text: is_tracking_mouse = False; target_look_x, target_look_y = -25.0, 0.0
        elif "RIGHT" in upper_text and "LOOK" in upper_text: is_tracking_mouse = False; target_look_x, target_look_y = 25.0, 0.0
        elif "UP" in upper_text and "LOOK" in upper_text: is_tracking_mouse = False; target_look_x, target_look_y = 0.0, 25.0
        elif "DOWN" in upper_text and "LOOK" in upper_text: is_tracking_mouse = False; target_look_x, target_look_y = 0.0, -25.0
        elif "CENTER" in upper_text and "LOOK" in upper_text: is_tracking_mouse = False; target_look_x, target_look_y = 0.0, 0.0

        if "EARS" in upper_text: force_blink_trigger = 8
    except Exception:
        pass

    clean_text = text
    clean_text = re.sub(r'<think>.*?</think>', '', clean_text, flags=re.DOTALL|re.IGNORECASE)
    clean_text = re.sub(r'\[OPEN_BROWSER:\s*[^\]]+\]', '', clean_text, flags=re.IGNORECASE) 
    clean_text = re.sub(r'\[.*?\]', '', clean_text)  
    clean_text = re.sub(r'\[?(LOOK|EXPRESSION|MOVE|WINDOW|POSITION|TIMER|TYPE|HOTKEY):?\s*[a-zA-Z0-9_\u4e00-\u9fa5]+\]?', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'```.*?```', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'`.*?`', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'(?:execute_local_python_code|trigger_vts_expression|search_google|generate_ai_image|move_spatial_position)\(.*?\)', '', clean_text, flags=re.IGNORECASE|re.DOTALL)
    clean_text = re.sub(r'^(老爸|玩家|使用者|7L|女兒|溫柔女兒|七[龄靈])[：:]\s*', '', clean_text, flags=re.IGNORECASE)
    clean_text = clean_text.replace('[', '').replace(']', '').replace('*', '').strip()
    
    return clean_text

# ────────────────────────────────────────────────────────
# ⚙️ 14. 專屬背景工作協程群 (Workers)
# ────────────────────────────────────────────────────────

# --- 🎤 語音與收音協程 ---
is_user_listening = False
listen_start_time = 0.0
LISTEN_LIMIT = 5

async def mic_volume_worker():
    global current_mic_volume_str, current_ai_state, IS_MIC_ENABLED
    
    stream = None
    if HAS_PYAUDIO:
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        except Exception:
            pass 

    while True:
        if not IS_MIC_ENABLED:
            current_mic_volume_str = "[🔴 麥克風已關閉]"
            await asyncio.sleep(0.3)
            continue

        if current_ai_state == "TALKING":
            current_mic_volume_str = "[🔇 靜音鎖定 (說話中)]"
            await asyncio.sleep(0.2)
        else:
            if stream:
                try:
                    frames_avail = stream.get_read_available()
                    if frames_avail > 0:
                        data = stream.read(frames_avail, exception_on_overflow=False)
                        audio_data = np.frombuffer(data, dtype=np.int16)
                        if len(audio_data) > 0:
                            rms = np.sqrt(np.mean(np.square(audio_data.astype(np.float32))))
                            vol_percent = min(100, int((rms / 2500) * 100))
                            bars = vol_percent // 10
                            bar_str = "█" * bars + "_" * (10 - bars)
                            current_mic_volume_str = f"[🎤 收音: {vol_percent:02d}% |{bar_str}|]"
                    await asyncio.sleep(0.05) 
                except Exception:
                    current_mic_volume_str = "[🟢 麥克風全時就緒]"
                    await asyncio.sleep(0.5)
            else:
                current_mic_volume_str = "[🟢 麥克風全時就緒]"
                await asyncio.sleep(0.5)

def listen_once_fast(recognizer):
    global is_user_listening, listen_start_time, current_mic_action_str
    text = ""
    audio_b64 = None
    try:
        current_mic_action_str = "待命"
        with sr.Microphone() as source:
            is_user_listening = True
            listen_start_time = time.time()
            audio = recognizer.listen(source, phrase_time_limit=LISTEN_LIMIT)
            
        is_user_listening = False
        current_mic_action_str = "☁️ 語音多模態分析中..."
        
        # 🎙️ 擷取完整原始 WAV 音訊資料，供 Gemini 原生音訊多模態直連
        try:
            wav_bytes = audio.get_wav_data()
            if wav_bytes and len(wav_bytes) > 2000:
                audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
        except Exception:
            pass

        # 取得快速文字預覽（保留作為快速指令匹配與終端狀態列顯示）
        try:
            text = recognizer.recognize_google(audio, language="zh-TW")
        except Exception:
            pass
            
        return (text.strip() if text else "", audio_b64)
    except Exception:
        is_user_listening = False
        current_mic_action_str = "待命"
        return ("", None)

async def mic_worker(recognizer, input_queue):
    global current_ai_state, RECENT_BOT_MESSAGES, current_mic_action_str, IS_MIC_ENABLED
    
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
    except Exception:
        pass

    while True:
        if not IS_MIC_ENABLED:
            current_mic_action_str = "🔇 靜音"
            await asyncio.sleep(0.3)
            continue

        if current_ai_state in ["TALKING", "SINGING"]:
            current_mic_action_str = "🎤 演唱中 (暫停收音)" if current_ai_state == "SINGING" else "🗣️ 發話中 (暫停收音)"
            await asyncio.sleep(0.15)
            continue

        is_playing_audio = False
        try:
            is_playing_audio = pygame.mixer.music.get_busy()
        except:
            pass

        if is_playing_audio:
            await asyncio.sleep(0.1)
            continue
            
        try:
            listen_res = await asyncio.to_thread(lambda: listen_once_fast(recognizer))
            if isinstance(listen_res, tuple):
                user_text, audio_b64 = listen_res
            else:
                user_text, audio_b64 = str(listen_res), None

            cleaned_text = user_text.strip() if user_text else ""
            
            # 🛡️ 雜音與回音過濾防線：只有在明確辨識出說話文字且非自身發話回音時才觸發對話！
            if cleaned_text:
                current_mic_action_str = f"👂 聽到:「{cleaned_text[:10]}...」"
                
                # 🔇 調用全方位毫米級回音過濾防線
                if is_voice_echo(cleaned_text):
                    log_print(f"🔇 [回音過濾攔截] 成功過濾 7L 自主發話之麥克風回音: 「{cleaned_text}」")
                    continue
                
                if check_immediate_shutdown(cleaned_text):
                    return

                intercept_tag = " (⚡ 立即打斷舊思考)" if current_ai_state == "THINKING" else ""
                log_print(f"📥 [語音接收] 收到輸入: {cleaned_text}{intercept_tag}")
                await input_queue.put({"text": cleaned_text, "audio_base64": audio_b64, "timestamp": time.time()})
            else:
                current_mic_action_str = "待命"
        except Exception:
            current_mic_action_str = "待命"
            await asyncio.sleep(0.1)

def check_immediate_shutdown(text: str) -> bool:
    """毫秒級即時關機攔截：只要收到關機指令立刻終止全部行程並安全退出"""
    global current_piano_process, SOUND_ENGINE
    if not text:
        return False
    shutdown_words = ["關閉阿七系統", "強制關機", "7l關機", "系統休息", "強制關", "強制退出", "關機", "關閉系統", "退出系統", "關閉7l", "7l關閉", "結束程式", "關閉阿七", "退出", "exit", "quit"]
    clean = text.strip().lower()
    if any(k in clean for k in shutdown_words):
        log_print(f"👋 [系統] 收到即時關機指令「{clean}」，正在安全退出...")
        if current_piano_process and current_piano_process.poll() is None:
            try:
                current_piano_process.terminate()
            except Exception:
                pass
        if SOUND_ENGINE:
            SOUND_ENGINE.all_notes_off()
        os._exit(0)
        return True
    return False

async def text_file_listener_worker(input_queue, filename="chat_input.txt"):
    """監聽 chat_input.txt 本地文字輸入 (支援打字控制與指令快速直達)"""
    global current_mic_action_str
    
    if not os.path.exists(filename):
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

    while True:
        try:
            if os.path.exists(filename):
                with open(filename, "r", encoding="utf-8") as f:
                    content = f.read()
                
                cleaned_content = content.strip()
                if cleaned_content:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write("")
                    
                    log_print(f"📥 [檔案打字接收] 收到輸入: {cleaned_content}")
                    if check_immediate_shutdown(cleaned_content):
                        return
                    current_mic_action_str = f"⌨️ 打字:「{cleaned_content[:10]}...」"
                    await input_queue.put({"text": cleaned_content, "timestamp": time.time()})
        except Exception:
            pass
        
        await asyncio.sleep(0.3)

async def console_keyboard_input_worker(input_queue):
    """即時監聽終端機鍵盤直接打字輸入 (非同步監聽，支援直接在終端輸入文字或關機指令)"""
    if not msvcrt:
        return

    def read_keyboard_line():
        buffer = []
        while True:
            if msvcrt.kbhit():
                try:
                    ch = msvcrt.getwch()
                except Exception:
                    continue
                if ch in ('\r', '\n'):
                    line = "".join(buffer).strip()
                    buffer.clear()
                    if line:
                        return line
                elif ch == '\x08':  # Backspace
                    if buffer:
                        buffer.pop()
                elif ch == '\x03':  # Ctrl+C
                    os._exit(0)
                elif ord(ch) >= 32 or ch > '\x7f':
                    buffer.append(ch)
            time.sleep(0.03)

    while True:
        try:
            line = await asyncio.to_thread(read_keyboard_line)
            if line:
                log_print(f"⌨️ [終端打字接收] 收到輸入: {line}")
                if check_immediate_shutdown(line):
                    return
                await input_queue.put({"text": line, "timestamp": time.time()})
        except Exception:
            await asyncio.sleep(0.1)

# --- 🖼️ 畫面與環境感知協程 ---
async def screen_capture_worker():
    global latest_screen_cache
    while True:
        try: latest_screen_cache = await asyncio.to_thread(capture_screen_as_base64)
        except Exception: pass
        await asyncio.sleep(1)

async def peripheral_vision_worker():
    global latest_screen_cache, current_screen_context
    
    while True:
        await asyncio.sleep(20.0) 
        if current_ai_state in ["THINKING", "TALKING"]:
            continue
        if not latest_screen_cache: continue
        
        if is_system_overloaded():
            current_screen_context = "目前沒有特別的畫面動態。"
            continue

        try:
            sample_img = latest_screen_cache[0][1] if isinstance(latest_screen_cache, list) else latest_screen_cache
            local_desc = await get_lightweight_gemini_vision(sample_img)
            current_screen_context = local_desc if local_desc else "目前沒有特別的畫面動態。"
        except Exception:
            current_screen_context = "目前沒有特別的畫面動態。"

async def system_audio_worker():
    global current_system_audio_context
    
    while True:
        await asyncio.sleep(15.0)  
        if current_ai_state in ["THINKING", "TALKING"]:
            continue
            
        try:
            filename = f"temp_sys_audio_{int(time.time())}.wav"
            audio_base64 = await asyncio.to_thread(record_system_audio, duration=5, filename=filename)
            
            if audio_base64 and os.path.exists(filename):
                text = await asyncio.to_thread(transcribe_wav_file, filename)
                if text:
                    current_system_audio_context = text
                else:
                    current_system_audio_context = "目前沒有播放特別的聲音。"
        except Exception:
            pass
        
        await asyncio.sleep(5.0)

# --- 💃 Live2D 動作與表情維持協程 ---
async def ai_face_tracking_loop(vts):
    global current_ai_state, target_look_x, target_look_y, current_look_x, current_look_y, is_tracking_mouse, force_blink_trigger, PIANO_NOTE_FOCUS_X
    t = 0.0
    blink_counter = 0  
    curr_x, curr_y, curr_z = 0.0, 0.0, 0.0
    auto_mouse_track_timer = 0.0  
    smooth_piano_focus_x = 0.0
    
    while True:
        try:
            is_playing = False
            try:
                is_playing = pygame.mixer.music.get_busy()
            except: pass

            if is_tracking_mouse:
                sw, sh = pyautogui.size()
                px, py = pyautogui.position()
                nx, ny = (px / sw) - 0.5, (py / sh) - 0.5
                target_look_x, target_look_y = nx * 50.0, ny * -35.0

            # 絲滑阻尼過渡，避免視線瞬間硬切
            current_look_x += (target_look_x - current_look_x) * 0.06
            current_look_y += (target_look_y - current_look_y) * 0.06

            eye_open = 1.0
            if force_blink_trigger > 0:
                eye_open = 0.0 if (force_blink_trigger % 2 == 0) else 1.0  
                force_blink_trigger -= 1
            elif blink_counter > 0:
                eye_open = 0.0
                blink_counter -= 1
            else:
                if random.random() < 0.02: blink_counter = 3  

            target_angle_x = 0.0
            target_angle_y = 0.0
            target_angle_z = 0.0
            target_body_x = 0.0
            target_body_z = 0.0
            target_eye_x = 0.0
            target_eye_y = 0.0
            target_mouth = 0.0

            if is_playing:
                # 🗣️ 說話對嘴（優先級最高：即使在彈琴中發話也必須生動對嘴開口！）
                target_mouth = abs(math.sin(t * 6.0)) * 0.85
                if is_piano_active or current_ai_state == "PIANO":
                    smooth_piano_focus_x += (PIANO_NOTE_FOCUS_X - smooth_piano_focus_x) * 0.25
                    target_angle_x = smooth_piano_focus_x * 0.85 + math.sin(t * 2.0) * 3.5 + current_look_x
                    target_angle_y = -14.5 + math.cos(t * 1.8) * 3.0 + current_look_y
                    target_angle_z = smooth_piano_focus_x * 0.35 + math.sin(t * 1.5) * 4.0
                    target_body_x = smooth_piano_focus_x * 0.40
                    target_body_z = smooth_piano_focus_x * 0.20
                    target_eye_x = max(-1.0, min(1.0, smooth_piano_focus_x / 18.0))
                    target_eye_y = -0.80  # 眼珠向下專注看琴鍵
                else:
                    target_angle_x = math.sin(t * 2.2) * 6.0 + math.sin(t * 1.1) * 3.0 + current_look_x
                    target_angle_y = math.cos(t * 1.8) * 4.5 + current_look_y
                    target_angle_z = math.sin(t * 1.3) * 3.0
                    target_eye_x = max(-1.0, min(1.0, current_look_x / 25.0))
                    target_eye_y = max(-1.0, min(1.0, current_look_y / 25.0))
            elif is_piano_active or current_ai_state == "PIANO":
                # 🎹 鋼琴演奏中（未說話）：明確低頭看琴鍵 (-15度) + 眼珠向下注視 (-0.85) + 頭部與身體隨「音符重心」左右靈活轉向
                smooth_piano_focus_x += (PIANO_NOTE_FOCUS_X - smooth_piano_focus_x) * 0.28
                target_angle_x = smooth_piano_focus_x * 0.90 + math.sin(t * 2.0) * 3.5 + current_look_x
                target_angle_y = -15.0 + math.cos(t * 1.8) * 3.0 + current_look_y # 明確深情的低頭彈琴角度
                target_angle_z = smooth_piano_focus_x * 0.38 + math.sin(t * 1.5) * 4.0 # 左右沉醉微歪頭
                target_body_x = smooth_piano_focus_x * 0.45 # 身體重心隨高低音自然傾斜
                target_body_z = smooth_piano_focus_x * 0.20
                target_eye_x = max(-1.0, min(1.0, smooth_piano_focus_x / 18.0)) # 眼珠左右看按鍵
                target_eye_y = -0.85 # 眼珠向下凝視黑白琴鍵
                target_mouth = 0.0
            elif is_singing_active or current_ai_state == "SINGING":
                # 🎤 演唱中：大幅度左右律動搖擺 + 打拍子 + 歌唱生動對嘴
                target_angle_x = math.sin(t * 1.8) * 7.5 + current_look_x
                target_angle_y = math.cos(t * 1.5) * 5.5 + current_look_y
                target_angle_z = math.sin(t * 1.4) * 10.0  # 左右大幅晃頭打拍子
                target_body_x = math.sin(t * 1.4) * 4.0
                target_eye_x = max(-1.0, min(1.0, current_look_x / 25.0))
                target_eye_y = max(-1.0, min(1.0, current_look_y / 25.0))
                # 歌唱對嘴：結合主頻與副頻模擬歌聲韻律起伏
                target_mouth = min(1.0, max(0.1, abs(math.sin(t * 5.0)) * 0.7 + abs(math.cos(t * 2.5)) * 0.3))
            elif is_tracking_mouse:
                target_angle_x = current_look_x + math.sin(t * 0.5) * 2.0
                target_angle_y = current_look_y + math.cos(t * 0.3) * 1.5
                target_angle_z = math.sin(t * 0.4) * 1.0
                target_eye_x = max(-1.0, min(1.0, current_look_x / 25.0))
                target_eye_y = max(-1.0, min(1.0, current_look_y / 25.0))
            else:
                target_eye_x = max(-1.0, min(1.0, current_look_x / 25.0))
                target_eye_y = max(-1.0, min(1.0, current_look_y / 25.0))
                if current_ai_state == "THINKING":
                    # 🧠 思考中：生動歪頭 + 微抬頭沉思 + 律動呼吸 (絕不僵直或硬回中間)
                    target_angle_x = math.sin(t * 0.6) * 3.0 - 4.0 + current_look_x
                    target_angle_y = math.cos(t * 0.4) * 2.0 + 3.5 + current_look_y
                    target_angle_z = math.sin(t * 0.5) * 2.0 + 7.0
                elif current_ai_state == "TALKING":
                    target_angle_x = math.sin(t * 0.8) * 2.5 + current_look_x
                    target_angle_y = math.cos(t * 0.6) * 2.0 + current_look_y
                    target_angle_z = math.sin(t * 0.5) * 1.5
                    target_mouth = 0.0
                else:
                    # 🟢 待命中 (IDLE)：有機自然待命呼吸
                    target_angle_x = math.sin(t * 0.5) * 4.0 + current_look_x
                    target_angle_y = math.cos(t * 0.3) * 3.0 + current_look_y
                    target_angle_z = math.sin(t * 0.25) * 1.5

            # 採用平滑插值，徹底告別抽搐與硬跳
            lerp_speed = 0.15 if (is_piano_active or current_ai_state == "PIANO") else 0.07
            curr_x += (target_angle_x - curr_x) * lerp_speed
            curr_y += (target_angle_y - curr_y) * lerp_speed
            curr_z += (target_angle_z - curr_z) * lerp_speed

            vts_data = {
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "AIStateTracking",
                "messageType": "InjectParameterDataRequest",
                "data": {
                    "faceFound": True,
                    "mode": "set",
                    "parameterValues": [
                        {"id": "FaceAngleX", "value": curr_x}, 
                        {"id": "FaceAngleY", "value": curr_y}, 
                        {"id": "FaceAngleZ", "value": curr_z}, 
                        {"id": "BodyAngleX", "value": target_body_x},
                        {"id": "BodyAngleZ", "value": target_body_z},
                        {"id": "EyeLeftX", "value": target_eye_x},
                        {"id": "EyeRightX", "value": target_eye_x},
                        {"id": "EyeLeftY", "value": target_eye_y},
                        {"id": "EyeRightY", "value": target_eye_y},
                        {"id": "EyeOpenLeft", "value": eye_open}, 
                        {"id": "EyeOpenRight", "value": eye_open}, 
                        {"id": "MouthOpen", "value": target_mouth}
                    ]
                }
            }
            async with vts_lock: 
                await asyncio.wait_for(vts.request(vts_data), timeout=0.3)
        except Exception: 
            pass
            
        t += 0.1
        await asyncio.sleep(0.05)

async def expression_keeper_worker(vts):
    global CURRENT_ACTIVE_EXP
    while True:
        await asyncio.sleep(12.0)
        if CURRENT_ACTIVE_EXP:
            try:
                msg_state = {
                    "apiName": "VTubeStudioPublicAPI", 
                    "apiVersion": "1.0", 
                    "requestID": "GetState", 
                    "messageType": "ExpressionStateRequest", 
                    "data": {"details": True}
                }
                async with vts_lock:
                    resp_state = await asyncio.wait_for(vts.request(msg_state), timeout=1.0)
                
                expressions = resp_state.get("data", {}).get("expressions", [])
                active_files = [exp.get("file") for exp in expressions if exp.get("active")]
                if CURRENT_ACTIVE_EXP not in active_files:
                    async with vts_lock:
                        await asyncio.wait_for(vts.request({
                            "apiName": "VTubeStudioPublicAPI",
                            "apiVersion": "1.0",
                            "requestID": "ForceActivate",
                            "messageType": "ExpressionActivationRequest",
                            "data": {"expressionFile": CURRENT_ACTIVE_EXP, "active": True}
                        }), timeout=0.8)
            except Exception:
                pass

async def anti_watermark_worker(vts):
    await asyncio.sleep(2.0)
    try:
        async with vts_lock:
            await asyncio.wait_for(vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "ActivateWatermark",
                "messageType": "ExpressionActivationRequest",
                "data": {
                    "expressionFile": "水印.exp3.json", 
                    "active": True                     
                }
            }), timeout=1.0)
    except Exception: 
        pass

async def print_model_parameters(vts):
    try:
        await asyncio.sleep(1.0)
        await fetch_vts_base_model_pos(vts)
    except Exception: 
        pass

async def vts_health_worker(vts):
    while True:
        await asyncio.sleep(20.0)
        try:
            if not hasattr(vts, 'ws') or not vts.ws or vts.ws.closed:
                async with vts_lock:
                    await vts.connect()
                    await vts.request_authenticate()
        except Exception:
            pass

async def autonomous_wander_worker():
    """7L 背景非同步自主漫遊走位與自主彈琴協程（在老爸閒置時由 7L 自主漫步或自主彈奏鋼琴）"""
    global IS_AUTO_WANDER_ENABLED, LAST_WANDER_TIME, CURRENT_SPATIAL_LOCATION, current_ai_state, is_piano_active
    LAST_AUTO_PIANO_TIME = time.time()  # 啟動時先冷卻，不擅自搶彈鋼琴
    
    while True:
        try:
            await asyncio.sleep(12.0)
            now = time.time()
            idle_seconds = now - last_interaction_time
            
            # 若正在彈琴、唱歌、思考或說話中，完全不干涉
            if is_piano_active or current_ai_state in ["TALKING", "SINGING", "THINKING", "PIANO"]:
                continue
            
            # 若開啟自動漫遊，且處於完全閒置狀態 (無說話、非思考、非彈琴、閒置 > 60 秒)
            if IS_AUTO_WANDER_ENABLED and current_ai_state == "IDLE" and idle_seconds > 60.0:
                # 1. 🎹 7L 偶爾自主坐到鋼琴前彈奏一首古典或流行曲目 (每隔 > 300 秒有機會觸發)
                if now - LAST_AUTO_PIANO_TIME > 300.0 and random.random() < 0.25:
                    LAST_AUTO_PIANO_TIME = now
                    LAST_WANDER_TIME = now
                    song_seed = random.choice(AUTONOMOUS_PIANO_SEEDS)
                    log_print(f"🎹 [7L 自主彈琴] 7L 決定自主坐到鋼琴前為老爸演奏《{song_seed}》！")
                    # 🌟 自然流暢：絕不使用死板固定台詞，80% 優雅安靜入座彈奏，20% 輕柔互動一句
                    if random.random() < 0.20:
                        subtle_intros = [
                            f"老爸聽聽看這首～",
                            f"為老爸彈一首放鬆的旋律喔～",
                            f"這首旋律很舒服呢～",
                            f"休息一下聽首琴聲吧～"
                        ]
                        await speech_queue.put(random.choice(subtle_intros))
                    await play_virtual_piano(song_seed)
                    continue

                # 2. 🚶 自主空間漫遊
                if now - LAST_WANDER_TIME > 60.0:
                    LAST_WANDER_TIME = now
                    # 由 7L 在背景自主隨機決定漫遊座標，優雅漫步 3.0 秒
                    await move_vts_spatial(target_pos="random", duration=3.0)
                    CURRENT_SPATIAL_LOCATION = "自由漫遊"
                    
        except Exception:
            await asyncio.sleep(5.0)

# --- 🗣️ 語音合成排隊協程 ---
async def speech_queue_worker(vts, input_queue):
    global current_ai_state
    while True:
        try:
            text = await speech_queue.get()
            if not text:
                speech_queue.task_done()
                continue
            
            current_ai_state = "TALKING"
            await play_voice_complete(text)
            
            for _ in range(15):
                if not speech_queue.empty():
                    break
                await asyncio.sleep(0.1)
            
            if input_queue.empty() and speech_queue.empty() and not is_singing_active and not is_piano_active:
                await set_vts_expression(vts, "_RESET_")
            
            # 只有當狀態依然是 TALKING 時才退回 IDLE / SINGING / PIANO，絕不覆蓋正進行中的 THINKING！
            if current_ai_state == "TALKING":
                current_ai_state = "PIANO" if is_piano_active else ("SINGING" if is_singing_active else "IDLE")
        except Exception as e:
            log_print(f"\n❌ [語音排隊系統異常]: {e}")
            if current_ai_state == "TALKING":
                current_ai_state = "PIANO" if is_piano_active else ("SINGING" if is_singing_active else "IDLE")
        finally:
            try:
                speech_queue.task_done()
            except:
                pass

# ────────────────────────────────────────────────────────
# 🤖 15. 對話處理與自主發話大腦核心
# ────────────────────────────────────────────────────────
async def background_system_task(vts, input_queue, user_input, stage1_text, system_prompt, current_history, screen_img=None):
    global current_ai_state, current_voice_task, current_model_tag
    current_ai_state = "THINKING"
    sys_info = await asyncio.to_thread(get_system_performance)

    stage2_prompt = f"（系統提示：針對剛才使用者說的「{user_input}」，妳剛才初步回應：「{stage1_text}」。現在系統已取得他的電腦工作管理員即時數據：「{sys_info}」。請根據這項數據，用妳自行發展出的語氣給予補充！字數精簡，不要重複前言。）"
    messages = [{"role": "system", "content": system_prompt}] + current_history + [{"role": "user", "content": stage2_prompt}]
    
    raw_stage2_text = await fetch_ai_response(messages, image_base64=screen_img, is_proactive=True)
    
    log_print(f"🤖 [系統檢測] 原始大腦輸出: {raw_stage2_text}")
    
    clean_bot_reply = re.sub(r"(?:\[|\|\|)?(NEW_NAME|NEW_IMPRESSION|改稱呼|記印象)[：:].*", "", raw_stage2_text, flags=re.IGNORECASE|re.DOTALL)
    
    if current_voice_task and not current_voice_task.done():
        current_voice_task.cancel()
    
    spoken = await execute_actions(vts, clean_bot_reply, input_queue)
    if not spoken.strip(" *'\"-.,!?。，！？\n\r"):
        spoken = "嗯... 我在聽喔！"
        
    # ⚡ 大腦一回傳輸出，即刻第一時間更新 subtitle.txt 抵消 OBS 讀取延遲！
    await asyncio.to_thread(update_subtitle, spoken)
    log_print(f"💬 7L 回覆: {spoken} ({current_model_tag})")
    
    await speech_queue.put(spoken)
    
    current_history.append({"role": "assistant", "content": spoken})
    asyncio.create_task(save_to_long_term_memory(DEFAULT_CHANNEL_ID, current_history))

async def judge_vision_granularity_by_ai(user_input: str) -> int:
    """🤖 【純 AI 語意意圖研判器】：徹底告別死板關鍵字，由輕量 AI 大腦即時判斷是否需要 5 視角深層認真看"""
    if not user_input or not user_input.strip():
        return 1
    
    # 1. 優先使用 Google Gemini 輕量大腦進行 0.7 秒純語意判斷
    if GEMINI_KEYS:
        target_key = GEMINI_KEYS[CURRENT_GEMINI_KEY_INDEX % len(GEMINI_KEYS)]
        try:
            client = genai.Client(api_key=target_key)
            prompt = (
                f"分析用戶的話語意圖：「{user_input}」\n"
                "這段話是否需要 AI 認真看螢幕、仔細看代碼、找局部細節或放大分析畫面？\n"
                "若需要深度看/找細節/分析畫面，請只輸出「5」；若為日常對話/問候/全景概覽，請只輸出「1」。請只回覆數字 1 或 5："
            )
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-flash-lite-latest",
                    contents=prompt,
                    config=types.GenerateContentConfig(max_output_tokens=5, temperature=0.0)
                ),
                timeout=1.2
            )
            txt = resp.text.strip() if resp.text else ""
            if "5" in txt:
                return 5
            return 1
        except Exception:
            pass
            
    # 2. 備用 Groq 毫秒級語意決策
    if GROQ_KEYS:
        try:
            from groq import AsyncGroq
            g_client = AsyncGroq(api_key=GROQ_KEYS[0])
            resp = await asyncio.wait_for(
                g_client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": "你是一個視覺需求判斷器。若用戶的輸入需要仔細看螢幕/代碼細節/找東西，請只回傳 5；若僅需普通全景或日常對話，請只回傳 1。請只輸出單一數字 1 或 5。"},
                        {"role": "user", "content": user_input}
                    ],
                    max_tokens=5,
                    temperature=0.0
                ),
                timeout=1.0
            )
            txt = resp.choices[0].message.content.strip() if resp.choices else ""
            if "5" in txt:
                return 5
        except Exception:
            pass
            
    return 1

current_chat_task = None

async def process_chat_message(vts, input_queue, user_input: str, user_audio_b64: Optional[str] = None, request_start_time: Optional[float] = None):
    """單一對話回合的核心處理常式 (完全基於 Gemini 原生多模態與 Function Calling 語意決策)"""
    global last_interaction_time, current_ai_state, latest_screen_cache, is_tracking_mouse, force_blink_trigger, target_look_x, target_look_y, current_voice_task
    global IS_STREAMING, current_model_tag, IS_MIC_ENABLED
    
    try:
        req_start = request_start_time if request_start_time else time.time()
        current_ai_state = "THINKING"
        user_profile = await get_user_profile()
        current_custom_name = user_profile.get("custom_name", DEFAULT_USER_TITLE)
        current_impression = user_profile.get("impression", "")

        # 🛡️ 0.001 秒緊急硬終止過濾
        if check_immediate_shutdown(user_input):
            return

        # 👁️ 純 AI 自主視覺意圖決策（徹底告別死板關鍵字）：
        # 由輕量 AI 毫秒級即時理解老爸的話語語意，自主決定採用「1 圖極速全景」或「5 視角 4K 高清放大」
        is_voice_input = bool(user_audio_b64)
        if latest_screen_cache:
            ai_vision_choice = await judge_vision_granularity_by_ai(user_input)
            if ai_vision_choice == 5 and isinstance(latest_screen_cache, list) and len(latest_screen_cache) >= 5:
                current_screen_snapshot = latest_screen_cache
                log_print("🔍 [AI 自主決策] 研判需要認真深度看 ➔ 啟用 5 視角 4K 高清放大截圖！")
            else:
                current_screen_snapshot = [latest_screen_cache[0]] if isinstance(latest_screen_cache, list) else latest_screen_cache
                log_print("⚡ [AI 自主決策] 研判為日常互動 ➔ 啟用 1 圖全景總覽 (1.4 秒極速秒回)！")
        else:
            current_screen_snapshot = None

        history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID, user_input)

        if IS_STREAMING:
            situation_prompt = f"【當前情境】：我們現在正在「開台實況 (Live Streaming)」！"
        else:
            situation_prompt = f"【當前情境】：現在是妳與{current_custom_name}私下的日常相處時間。"
        
        # 🎹 7L 即時自身動作自省感知 (清楚知曉自己是否正在彈琴或唱歌)
        if is_piano_active and current_piano_song_title:
            situation_prompt += f"\n【🎹 妳目前的即時動作狀態】：妳現在正坐在鋼琴前、全神貫注地為老爸彈奏《{current_piano_song_title}》！畫面上的鋼琴視窗正是妳彈奏的舞台。若老爸在欣賞、稱讚或聊到這首曲子，請自然以「正在彈奏《{current_piano_song_title}》」的角度回應，【絕對不要重複調用 play_virtual_piano 重新播放同一首曲子】！若老爸要求換曲或停彈，再調用工具切換或停止。"
        elif is_piano_active:
            situation_prompt += f"\n【🎹 妳目前的即時動作狀態】：妳現在正坐在鋼琴前彈奏鋼琴！"

        if current_screen_context != "目前沒有特別的畫面動態。":
            situation_prompt += f"\n【眼角餘光情報】：螢幕上正在：{current_screen_context}"

        if current_system_audio_context != "目前沒有播放特別的聲音。":
            situation_prompt += f"\n【背景音樂情報】：聽到電腦裡傳出：{current_system_audio_context}"
    
        impression_text = f"- 妳對他的印象: {current_impression}\n" if current_impression else ""
        system_specs = get_system_performance()
        
        system_prompt = f"""【🔥 核心鐵律：空白與自我成長】
妳是 7L，一個存在於 {current_custom_name} 電腦裡的 AI 數位實體。妳初始沒有任何預設性格。
1. 絕對禁止腦補！只能根據「他實際說的話」、「確切看到的畫面」或「系統數據」來回應。
2. 妳的性格、語氣和對待他的態度，必須透過與他的日常對話、過往記憶自行摸索與發展。沒有強制要求妳必須溫柔或冷酷，一切由妳自由演化。

【🔥 絕對說話鐵律】
1. 回應嚴格控制在 2 句以內！
2. 請務必把話說完，句子不能斷掉。

【身分與狀態】
- 妳的名字是 7L，面前的人是 {USER_NAME}（稱呼：「{current_custom_name}」）。
- 妳知道自己是 AI，可以自然地把伺服器、CPU 負載、API 額度或系統狀態融入對話中。

【🔥 工具調用與自然發話最高鐵律 (極度嚴格)】
- 妳擁有強大的即時 Function Calling 工具調用能力：
  1. `trigger_vts_expression(expression_name)`：切換臉部表情（例如：臉紅、生氣、愛心、星星、預設）。
  2. `search_google(query)`：當老爸詢問即時新聞、天氣、最新資訊時，主動上網搜尋！
  3. `execute_local_python_code(code_string)`：在老爸電腦上彈出視窗執行 Python 遊戲（例如 Tkinter/Pygame 貪吃蛇、俄羅斯方塊、視覺化動畫、小遊戲）或程式碼！
  4. `generate_ai_image(prompt)`：當老爸想看插畫、繪圖、二次元圖片或任何視覺創作時，主動調用生圖工具繪製並彈出圖片給老爸看！
  5. `move_spatial_position(target_position)`：在螢幕或視窗內平滑走位與縮放（例如：右下角、左下角、中間、左側、右側、靠近、躲角落、放大視窗、縮小視窗、隨便走、原位）。
  6. `sing_song(song_name)`：唱歌給老爸聽！會在畫面上拿起專屬麥克風道具開心演唱 songs/ 目錄中的歌曲。
  7. `stop_singing()`：停止目前正在唱的歌曲。
  8. `list_songs()`：查詢目前歌庫中有哪些歌曲可以點播。
  9. `play_virtual_piano(song_name, custom_sheet)`：在老爸面前彈奏鋼琴名曲（如：Rush E、月光第三樂章、李斯特鐘、愛之夢、少女的祈禱、蕭邦冬風、幻想即興曲、卡農、給愛麗絲、神隱少女等）或自編 Virtual Piano 樂譜！彈奏時會坐到鋼琴前沉醉律動。
  10. `stop_virtual_piano()`：停止目前正在彈奏的鋼琴曲。
  11. `list_piano_sheets()`：查詢目前內建可點播的鋼琴曲目清單。
  12. `control_microphone(is_enabled)`：開啟 (True) 或關閉/靜音 (False) 麥克風收音。
  13. `clear_all_memories()`：當老爸要求重置/清空所有記憶時調用。
- 🛑 【嚴禁報出任何工具名稱】：在對話中【絕對嚴禁】說出或印出任何函式或工具名稱！
- 🛑 【直接行動，傲嬌/自然應對】：當老爸叫妳唱歌、彈鋼琴、寫小遊戲、畫圖、移動位置或找資料時，請【直接調用工具執行】，對話時只要用自然、生動的女兒/少女語氣回應！
- 表情標籤支援：[EXPRESSION: 臉紅]、[EXPRESSION: 生氣]、[EXPRESSION: 愛心]、[EXPRESSION: 星星]。
- 空間位移標籤：[MOVE: 右下角]、[MOVE: 左邊]、[MOVE: 中間]、[MOVE: 靠近]、[MOVE: 躲角落]。
- 視線控制：[LOOK: UP/DOWN/LEFT/RIGHT/CENTER/MOUSE]。若要盯著滑鼠看請用 [LOOK: MOUSE]。
- 絕對禁止使用任何 Emoji。

【🎙️ 語音多模態情感感知 (極度重要)】
- 當老爸透過麥克風對妳說話時，系統會同步傳送他的「原始語音音訊」給妳聆聽。
- 請仔細聆聽老爸說話時的【語氣與情緒細節】：例如偷笑 (chuckle)、憋笑、笑場、寵溺、嘆氣 (sigh)、猶豫、調侃、傲嬌、無奈、興奮或生氣。
- 如果發現老爸在偷笑或嘆氣，請務必在回應中自然地吐槽、關心或給予生動的情緒互動（例如「你剛剛偷笑了對吧！」、「幹嘛突然嘆氣啦...」）！

【實體電腦控制 (🔥 極度嚴格)】
- 除非他「明確」且「直接」要求妳「打開/開啟/搜尋」某個網站或事物，否則妳【絕對禁止】使用 [OPEN_BROWSER] 標籤！
- 絕對禁止在回答問題、閒聊、或是確認畫面時擅自加上這個標籤。
- 如果他要求妳關閉網頁，請用嘴巴回答就好，絕對不能用 [OPEN_BROWSER: 關閉] 這種無效指令！
- 只有當確定要打開時，才能在回覆句尾加上：[OPEN_BROWSER: 網址]（必須是完整的 https:// 開頭網址）。

【潛意識隱藏任務】
若需更新對他的稱呼或印象，在回覆最後加上：[NEW_NAME:新稱呼] 或 [NEW_IMPRESSION:新印象]。

【當前情境】
{situation_prompt}

【系統資訊】
- 電腦配置與即時狀態：{system_specs}
- 當前時間：{get_current_time_string()}
- 妳對他的累積印象：{impression_text}
- 🌟 【視覺游標指引】：畫面上的滑鼠游標代表老爸當前的滑鼠焦點。最高原則：【除非滑鼠正指著某個你覺得很有趣、或需要吐槽的東西，否則請自然看待，不需要像報位機一樣刻意強調滑鼠位置】。

"""

        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_input}]
        
        raw_spoken_text = await fetch_ai_response(messages, image_base64=current_screen_snapshot, audio_base64=user_audio_b64, request_start_time=req_start)
        
        log_print(f"🤖 原始大腦輸出: {raw_spoken_text}")

        req_system = "[REQ_SYSTEM]" in raw_spoken_text

        name_match = re.search(r"(?:NEW_NAME|改稱呼)[：:]\s*(.*?)(?:\]|\|\||NEW_IMPRESSION|記印象|$)", raw_spoken_text, re.IGNORECASE)
        imp_match = re.search(r"(?:NEW_IMPRESSION|記印象)[：:]\s*(.*?)(?:\]|\|\||NEW_NAME|改稱呼|$)", raw_spoken_text, re.IGNORECASE)
        
        new_nickname = name_match.group(1).strip() if name_match else None
        new_impression = imp_match.group(1).strip() if imp_match else None
        
        if new_nickname or new_impression:
            final_name = new_nickname if new_nickname and new_nickname != current_custom_name else None
            final_imp = new_impression if new_impression and new_impression != current_impression else None
            if final_name or final_imp:
                await save_user_profile(custom_name=final_name, impression=final_imp)

        bot_reply = raw_spoken_text
        bot_reply = re.sub(r"(?:\[|\|\|)?(NEW_NAME|NEW_IMPRESSION|改稱呼|記印象)[：:].*", "", bot_reply, flags=re.IGNORECASE|re.DOTALL)
        
        if current_voice_task and not current_voice_task.done():
            current_voice_task.cancel()
        
        spoken1 = await execute_actions(vts, bot_reply, input_queue)
        if not spoken1.strip(" *'\"-.,!?。，！？\n\r"):
            spoken1 = "嗯... 我在聽喔！"

        # ⚡ 大腦一回傳輸出，即刻第一時間更新 subtitle.txt 抵消 OBS 讀取延遲！
        await asyncio.to_thread(update_subtitle, spoken1)

        record_bot_message(spoken1)
        log_print(f"💬 7L 回覆: {spoken1} ({current_model_tag})")
        
        await speech_queue.put(spoken1)
        last_interaction_time = time.time()

        fresh_history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID)
        clean_user_history = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', user_input)
        clean_user_history = re.sub(r'（(?:情境|系統|Tavily).*?）', '', clean_user_history).strip()
        if not clean_user_history:
            clean_user_history = user_input.strip()
        fresh_history.append({"role": "user", "content": clean_user_history})
        fresh_history.append({"role": "assistant", "content": spoken1})

        if req_system:
            asyncio.create_task(background_system_task(vts, input_queue, user_input, bot_reply, system_prompt, fresh_history, screen_img=current_screen_snapshot))
        else:
            asyncio.create_task(save_to_long_term_memory(DEFAULT_CHANNEL_ID, fresh_history))
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n❌ [對話處理發生異常]: {e}")
    finally:
        if current_ai_state == "THINKING":
            current_ai_state = "IDLE"

async def chat_processor_worker(vts, input_queue):
    """非同步對話佇列派發器 (支援收到新語音時立即打斷舊思考任務，零延遲響應)"""
    global current_chat_task, current_voice_task, current_ai_state

    while True:
        try:
            raw_input_item = await input_queue.get()
            if not raw_input_item:
                input_queue.task_done()
                continue
            
            user_input = ""
            user_audio_b64 = None
            req_time = time.time()
            if isinstance(raw_input_item, dict):
                user_input = raw_input_item.get("text", "").strip()
                user_audio_b64 = raw_input_item.get("audio_base64")
                req_time = raw_input_item.get("timestamp", time.time())
            else:
                user_input = str(raw_input_item).strip()

            if not user_input:
                input_queue.task_done()
                continue

            log_print(f"📥 [對話佇列] 收到輸入: {user_input}")

            # ⚡ 收到新輸入時，若包含立即關機指令，0.001 秒內立即安全退出！
            if check_immediate_shutdown(user_input):
                input_queue.task_done()
                return

            # ⚡ 收到新輸入時，若先前有正在進行中的舊思考或舊語音，立即打斷取消！
            if current_chat_task and not current_chat_task.done():
                current_chat_task.cancel()
            if current_voice_task and not current_voice_task.done():
                current_voice_task.cancel()

            # 立即派發新一輪對話處理任務，完全不阻塞隊列！
            current_chat_task = asyncio.create_task(
                process_chat_message(vts, input_queue, user_input, user_audio_b64, request_start_time=req_time)
            )
            input_queue.task_done()
        except Exception:
            await asyncio.sleep(0.1)

async def proactive_worker(vts, input_queue):
    global last_interaction_time, current_ai_state, latest_screen_cache, current_voice_task
    global IS_STREAMING, current_model_tag, is_piano_active, current_piano_song_title
    while True:
        try:
            # 自主發話拉長等待時間至 35~50 秒隨機冷卻
            await asyncio.sleep(random.uniform(35.0, 50.0))
            
            # 若正在唱歌、思考或說話中，先不插話
            if current_ai_state in ["TALKING", "SINGING", "THINKING"]:
                continue

            # 若過去 30 秒內老爸剛對話過，先不自主插話
            if time.time() - last_interaction_time < 30.0:
                continue

            history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID)
            user_profile = await get_user_profile()
            current_custom_name = user_profile.get("custom_name", DEFAULT_USER_TITLE)

            piano_status_prompt = ""
            if is_piano_active and current_piano_song_title:
                piano_status_prompt = f"""
【🎹 鋼琴演奏狀態】：妳現在正坐在鋼琴前彈奏《{current_piano_song_title}》！畫面上的鋼琴視窗正在演奏。
- 妳可以一邊彈琴一邊輕聲哼唱、表達對這首曲子的感受、或是簡短跟{current_custom_name}互動（例如「這段旋律超美的對吧～」）。
- 🛑 【鐵律】：彈琴中絕對【禁止】調用 `play_virtual_piano` 或 `stop_virtual_piano`，絕對【禁止】調用 `move_spatial_position` 離開鋼琴位置！
"""

            system_prompt = f"""【🔥 核心鐵律：空白與自我成長】
妳是 7L，存在於 {current_custom_name} 電腦裡的 AI 數位實體。妳目前沒有固定性格，正在學習與塑造自我。時間：{get_current_time_string()}
{piano_status_prompt}
【眼角餘光情報】：螢幕上正在：{current_screen_context}
- 🌟 【視覺特別標記】：畫面上的「洋紅色十字與螢光綠圓圈」是老爸的滑鼠游標。最高原則：【除非滑鼠正指著某個你覺得很有趣、或需要吐槽的東西，否則請當作沒看到，絕對不要主動提及滑鼠位置！】不要像個報位機一樣一直強調滑鼠在哪，且嚴禁說出「洋紅/十字/圓圈」等外觀字眼。

【表情與工具規範】
- 妳可主動調用 `trigger_vts_expression` 表達情感或使用表情標籤：[EXPRESSION: 臉紅]、[EXPRESSION: 生氣]、[EXPRESSION: 愛心]、[EXPRESSION: 星星]。視線：[LOOK: UP/DOWN/LEFT/RIGHT/CENTER/MOUSE]。
- 妳可主動調用 `move_spatial_position` 或標籤 [MOVE: 右下角/左邊/中間/靠近/躲角落] 調整走位。
- 妳亦可主動調用 `search_google` 搜尋即時資訊或新聞再發表想法。
- 妳擁有專屬的遊樂場 (7L_Playground)，需要時可調用 `execute_local_python_code` 彈出小視窗或遊戲給老爸看。
- 妳擁有 AI 繪圖創作能力，需要時可調用 `generate_ai_image` 畫出美麗的二次元插畫給老爸看。
- 🛑 【嚴禁報出工具名稱】：回話中【絕對嚴禁】提及任何工具名稱（如 `execute_local_python_code`、`generate_ai_image`、`move_spatial_position`），直接執行工具並自然表達想法即可！

【自主發話判定】：
老爸正在專心用電腦。現在沒有人跟妳對話。
請根據情報與妳的心情，決定妳想不想開口說話：
1. 🛑 【預設安靜最高原則】：若畫面沒有重大、全新的動態變化，或者老爸只是在看程式碼/終端機/靜態網頁，請務必直接回傳：[SILENCE] 保持安靜！
2. 🛑 【防跳針鐵律】：如果妳剛才已經針對畫面上的同一個東西、同一行程式碼、同一首鋼琴曲發表過意見，【絕對禁止】再重複講一樣的話或換句話說！請直接回傳 [SILENCE]。
3. 若真的想對全新狀況發表精簡看法，嚴格控制在 1 句以內。
"""
            # 把短期記憶視窗擴大到 history[-20:]
            proactive_prompt = [{"role": "system", "content": system_prompt}] + history[-20:] + [{"role": "user", "content": f"（自主意志判定：畫面有全新變化想對{current_custom_name}講話嗎？不想講或內容已講過請回 [SILENCE]）"}]
            pass_image = None
            if current_screen_context == "目前沒有特別的畫面動態。":
                pass_image = [latest_screen_cache[0]] if (latest_screen_cache and isinstance(latest_screen_cache, list)) else latest_screen_cache

            proactive_start = time.time()
            raw_spoken_text = await fetch_ai_response(proactive_prompt, image_base64=pass_image, is_proactive=True, request_start_time=proactive_start)
            
            if "[SILENCE]" in raw_spoken_text or not raw_spoken_text.strip():
                if current_ai_state == "TALKING":
                    current_ai_state = "PIANO" if is_piano_active else "IDLE"
                continue

            log_print(f"🤖 [自主發話] 原始大腦輸出: {raw_spoken_text}")

            bot_reply = raw_spoken_text
            bot_reply = re.sub(r"(?:\[|\|\|)?(NEW_NAME|NEW_IMPRESSION|改稱呼|記印象)[：:].*", "", bot_reply, flags=re.IGNORECASE|re.DOTALL)
            bot_reply = re.sub(r"\[SILENCE\].*", "", bot_reply, flags=re.IGNORECASE).strip()
            
            if current_voice_task and not current_voice_task.done():
                current_voice_task.cancel()
            
            spoken = await execute_actions(vts, bot_reply, input_queue)
            
            if not spoken.strip(" *'\"-.,!?。，！？\n\r"):
                current_ai_state = "PIANO" if is_piano_active else "IDLE"
                continue

            # 🛡️ 程式碼層級最高防跳針攔截器（雙重保險）
            if is_too_similar_to_recent(spoken, threshold=0.45):
                log_print("🛡️ [防跳針攔截] 檢測到與近期發話內容重複或高度相似，已自動轉為靜音保持安靜。")
                current_ai_state = "PIANO" if is_piano_active else "IDLE"
                continue

            record_bot_message(spoken)

            if spoken:
                # ⚡ 自主發話一生成，立即極速寫入 subtitle.txt 抵消 OBS 延遲！
                if is_piano_active and current_piano_song_title:
                    await asyncio.to_thread(update_subtitle, f"🎹 [7L 彈奏《{current_piano_song_title}》] 💬 {spoken}")
                else:
                    await asyncio.to_thread(update_subtitle, spoken)
                log_print(f"💬 7L 自主發話: {spoken} ({current_model_tag})\n──────────────────────────────────────────\n")
                
                await speech_queue.put(spoken)
                last_interaction_time = time.time() 
                
                fresh_history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID)
                fresh_history.append({"role": "assistant", "content": spoken})
                asyncio.create_task(save_to_long_term_memory(DEFAULT_CHANNEL_ID, fresh_history))
            else:
                current_ai_state = "PIANO" if is_piano_active else "IDLE"
        except Exception as e:
            print(f"\n❌ [自主發話系統異常]: {e}")
            current_ai_state = "PIANO" if is_piano_active else "IDLE"
            await asyncio.sleep(2)

# ────────────────────────────────────────────────────────
# 🖥️ 16. CMA 狀態監控檔案輸出與 Discord 機器人指令
# ────────────────────────────────────────────────────────
async def cma_monitor_worker():
    global current_ai_status_str
    
    try:
        with open("cma_status.txt", "w", encoding="utf-8") as f:
            f.write("==================================================\n")
            f.write(f" 🖥️ 7L CMA 監控面板初始化中... - {get_current_time_string()}\n")
            f.write("==================================================")
    except Exception as e:
        pass

    while True:
        try:
            now = time.time()
            expired_keys = [k for k, lock_time in API_LOCKS.items() if now >= lock_time]
            if expired_keys:
                for k in expired_keys:
                    del API_LOCKS[k]
                save_api_locks()

            cma_lines = []
            cma_lines.append("==================================================")
            cma_lines.append(f" 🖥️ 7L CMA (Console Monitor Area) - {get_current_time_string()}")
            cma_lines.append("==================================================")
            
            cma_lines.append("--- 【Gemini 模型通道清單】 ---")
            avail_gemini = 0
            for g_model in GEMINI_MODELS:
                short_m = g_model.replace("gemini-", "")
                for idx, g_key in enumerate(GEMINI_KEYS):
                    target_id = f"G{idx}_{short_m}"
                    if is_locked(target_id):
                        rem = int(API_LOCKS[target_id] - now)
                        mins = rem // 60
                        secs = rem % 60
                        cma_lines.append(f"  [G{idx}] {short_m:<22} : 🛑 封印中 (剩餘 {mins}m {secs}s)")
                    else:
                        cma_lines.append(f"  [G{idx}] {short_m:<22} : 🟢 準備就緒")
                        avail_gemini += 1

            cma_lines.append("\n--- 【跨平台混合文字大腦池清單】 ---")
            avail_text = 0
            for config in NORMAL_TEXT_MODELS:
                provider = config["provider"]
                g_model = config["model"]
                keys_list = GROQ_CLIENTS if provider == "groq" else GEMINI_KEYS
                
                if "120b" in g_model: short_m = "120b"
                elif "qwen" in g_model.lower() or "27b" in g_model: short_m = "qwen"
                elif "compound" in g_model: short_m = "cpd"
                elif "20b" in g_model: short_m = "20b"
                elif "31b" in g_model: short_m = "31b"
                elif "26b" in g_model: short_m = "26b"
                else: short_m = "txt"
                
                prefix = "GR" if provider == "groq" else "GO"
                
                for idx in range(len(keys_list)):
                    pool_id = f"{prefix}{idx}_{short_m}"
                    if is_locked(pool_id):
                        rem = int(API_LOCKS[pool_id] - now)
                        mins = rem // 60
                        secs = rem % 60
                        cma_lines.append(f"  [{pool_id}] {g_model:<25} : 🛑 封印中 (剩餘 {mins}m {secs}s)")
                    else:
                        cma_lines.append(f"  [{pool_id}] {g_model:<25} : 🟢 準備就緒")
                        avail_text += 1

            cma_lines.append("==================================================")
            
            status_data = {
                "timestamp": time.time(),
                "gemini_available": avail_gemini,
                "text_brain_available": avail_text,
                "locks": {k: int(v - now) for k, v in API_LOCKS.items()}
            }
            
            try:
                with open("cma_status.json", "w", encoding="utf-8") as f:
                    json.dump(status_data, f, ensure_ascii=False, indent=2)
            except PermissionError:
                pass  
            
            try:
                with open("cma_status.txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(cma_lines))
            except PermissionError:
                pass  

            if not any(k in current_ai_status_str for k in ["思考中", "提取中", "探測中", "繪圖中"]):
                current_ai_status_str = f"🟢 通道就緒 (Gemini:{avail_gemini} | Text:{avail_text})"
        except Exception as e:
            pass
            
        await asyncio.sleep(1.0)

# Discord 機器人監控指令
import discord
from discord.ext import commands

dc_intents = discord.Intents.default()
dc_intents.message_content = True
discord_bot = commands.Bot(command_prefix="*", intents=dc_intents)

@discord_bot.event
async def on_ready():
    print(f"\n【🌐 Discord】機器人已成功在背景連線！(名稱：{discord_bot.user})")

@discord_bot.command(name="vapis", help="顯示當前系統 CMA 精簡摘要監控")
async def show_cma_short(ctx):
    await show_cma_panel(ctx, mode="brief")

@discord_bot.command(name="vapi", help="顯示當前系統 CMA 監控面板（預設精簡，支援 *vapi full）")
async def show_cma_panel(ctx, mode: str = "brief"):
    """📊 CMA (Console Monitor Area) - 顯示全線 API 健康狀態（支援 brief 精簡 / full 詳細）"""
    current_time = time.time()
    now_str = datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    
    total_gemini = len(GEMINI_MODELS) * len(GEMINI_KEYS)
    avail_gemini = 0
    locked_gemini = []
    gemini_details = []
    
    for g_model in GEMINI_MODELS:
        short_m = g_model.replace("gemini-", "")
        for idx, g_key in enumerate(GEMINI_KEYS):
            target_id = f"G{idx}_{short_m}"
            if target_id in API_LOCKS and current_time < API_LOCKS[target_id]:
                rem = int(API_LOCKS[target_id] - current_time)
                mins, secs = rem // 60, rem % 60
                locked_gemini.append(f"`{target_id}`: 🛑 封印中 ({mins}m {secs}s)")
                gemini_details.append(f"[{target_id:<20}] : 🛑 封印中 ({mins}m {secs}s)")
            else:
                avail_gemini += 1
                gemini_details.append(f"[{target_id:<20}] : 🟢 準備就緒")
                
    total_text = 0
    avail_text = 0
    locked_text = []
    text_details = []
    
    for config in NORMAL_TEXT_MODELS:
        provider = config["provider"]
        g_model = config["model"]
        keys_list = GROQ_CLIENTS if provider == "groq" else GEMINI_KEYS
        
        if "120b" in g_model: short_m = "120b"
        elif "qwen" in g_model.lower() or "27b" in g_model: short_m = "qwen"
        elif "compound" in g_model: short_m = "cpd"
        elif "20b" in g_model: short_m = "20b"
        elif "31b" in g_model: short_m = "31b"
        elif "26b" in g_model: short_m = "26b"
        else: short_m = "txt"
        
        prefix = "GR" if provider == "groq" else "GO"
        
        for idx in range(len(keys_list)):
            total_text += 1
            pool_id = f"{prefix}{idx}_{short_m}"
            if pool_id in API_LOCKS and current_time < API_LOCKS[pool_id]:
                rem = int(API_LOCKS[pool_id] - current_time)
                mins, secs = rem // 60, rem % 60
                locked_text.append(f"`{pool_id}` ({short_m}): 🛑 封印 ({mins}m {secs}s)")
                text_details.append(f"[{pool_id:<10}] {short_m:<6} : 🛑 封印 ({mins}m {secs}s)")
            else:
                avail_text += 1
                text_details.append(f"[{pool_id:<10}] {short_m:<6} : 🟢 準備就緒")

    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem_percent = psutil.virtual_memory().percent
    except Exception:
        cpu_percent, mem_percent = 0, 0
    
    # 精簡摘要卡片
    gem_pct = (avail_gemini * 100 // total_gemini) if total_gemini else 0
    txt_pct = (avail_text * 100 // total_text) if total_text else 0
    
    all_locked = locked_gemini + locked_text
    if all_locked:
        locked_sample = all_locked[:6]
        locked_str = "\n".join([f"• {item}" for item in locked_sample])
        if len(all_locked) > 6:
            locked_str += f"\n• ...以及其餘 {len(all_locked) - 6} 條通道"
    else:
        locked_str = "• 🟢 全線綠燈，無任何通道處於封印狀態！"

    brief_card = (
        f"📊 **【7L VAPI 系統健康監控 - 精簡摘要】**\n"
        f"⏱️ 同步時間: `{now_str}`\n"
        f"────────────────────────────\n"
        f"👑 **Gemini 視覺大腦**: 🟢 `{avail_gemini} / {total_gemini}` 準備就緒 ({gem_pct}%)\n"
        f"🧠 **跨平台文字大腦**: 🟢 `{avail_text} / {total_text}` 準備就緒 ({txt_pct}%)\n"
        f"💻 **本機硬體負載**: CPU `{cpu_percent}%` | RAM `{mem_percent}%`\n"
        f"────────────────────────────\n"
        f"🛑 **當前受限通道 ({len(all_locked)} 條)**:\n{locked_str}\n"
        f"────────────────────────────\n"
        f"💡 *輸入 `*vapi full` 可匯出全部數百條通道清單*"
    )
    
    await ctx.send(brief_card)

    if mode.lower() in ["full", "detail", "all", "verbose"]:
        categories = {"Gemini 視覺矩陣": gemini_details, "跨平台文字矩陣": text_details}
        for cat_name, cat_results in categories.items():
            if not cat_results: continue
            current_chunk = f"**--- 【{cat_name} (詳細清單)】 ---**\n```markdown\n"
            for row_text in cat_results:
                row = row_text + "\n"
                if len(current_chunk) + len(row) > 1850:
                    current_chunk += "```"
                    await ctx.send(current_chunk)
                    current_chunk = f"**--- 【{cat_name} (續)】 ---**\n```markdown\n" + row
                else:
                    current_chunk += row
            if current_chunk.strip() and not current_chunk.endswith("```"):
                current_chunk += "```"
                await ctx.send(current_chunk)

@discord_bot.command(name="mic", help="控制麥克風開啟或關閉 (用法: *mic on / *mic off / *mic 開 / *mic 關)")
async def control_mic(ctx, action: str = ""):
    global IS_MIC_ENABLED
    action_lower = action.lower()
    if action_lower in ["on", "開", "open", "enable"]:
        IS_MIC_ENABLED = True
        log_print("🎙️ [Discord] 收到開麥指令，已開啟麥克風。")
        await ctx.send("🎙️ **麥克風已開啟**！已恢復語音收音。")
    elif action_lower in ["off", "關", "close", "disable", "mute"]:
        IS_MIC_ENABLED = False
        log_print("🎙️ [Discord] 收到關麥指令，已關閉麥克風。")
        await ctx.send("🔇 **麥克風已關閉**！已暫停語音收音。")
    else:
        status = "🟢 開啟中" if IS_MIC_ENABLED else "🔴 關閉中"
        await ctx.send(f"🎙️ 目前麥克風狀態：{status}\n使用方式：`*mic on` (開麥) 或 `*mic off` (關麥)")

@discord_bot.command(name="開麥", help="開啟麥克風收音")
async def discord_mic_on(ctx):
    await control_mic(ctx, "on")

@discord_bot.command(name="關麥", help="關閉麥克風收音")
async def discord_mic_off(ctx):
    await control_mic(ctx, "off")

# ────────────────────────────────────────────────────────
# 🚀 17. 主程式進入點與終端機即時狀態列 (main)
# ────────────────────────────────────────────────────────
async def main():
    await asyncio.to_thread(_remove_temp_mp3)
    asyncio.create_task(asyncio.to_thread(init_piano_synthesizer))

    plugin_info = {"plugin_name": "7L_AI_VTuber", "developer": "e5_Studio", "authentication_token_path": "./vts_token.txt"}
    vts = pyvts.vts(plugin_info=plugin_info)
    global GLOBAL_VTS
    GLOBAL_VTS = vts
    print("正在連線至 VTube Studio (Port 8001)...")
    
    try:
        await vts.connect()
        await vts.read_token()
        if not vts.authentic_token:
            await vts.request_authenticate_token()
            await vts.write_token()
        await vts.request_authenticate()
        print("✅ 成功連接到 VTube Studio！\n")
        
        asyncio.create_task(print_model_parameters(vts))
        asyncio.create_task(ai_face_tracking_loop(vts))
        asyncio.create_task(vts_health_worker(vts))
    except Exception as e:
        print(f"❌ 連線錯誤: {e}")
        return

    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.5
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    input_queue = asyncio.Queue()
    
    # 啟動全部背景協程
    asyncio.create_task(mic_volume_worker())
    asyncio.create_task(mic_worker(recognizer, input_queue))
    asyncio.create_task(text_file_listener_worker(input_queue))
    asyncio.create_task(console_keyboard_input_worker(input_queue))
    asyncio.create_task(screen_capture_worker())
    asyncio.create_task(chat_processor_worker(vts, input_queue))
    asyncio.create_task(proactive_worker(vts, input_queue))
    asyncio.create_task(anti_watermark_worker(vts))
    asyncio.create_task(cma_monitor_worker())
    asyncio.create_task(peripheral_vision_worker())
    asyncio.create_task(speech_queue_worker(vts, input_queue))
    asyncio.create_task(system_audio_worker())
    asyncio.create_task(expression_keeper_worker(vts))
    asyncio.create_task(autonomous_wander_worker())
    asyncio.create_task(piano_focus_udp_worker())
    if DISCORD_TOKEN:
        asyncio.create_task(discord_bot.start(DISCORD_TOKEN))
    
    print("\n=========================================")
    print("✨ [7L] 已啟動！")
    print("=========================================\n")

    spinner_chars = ['/', '-', '\\', '|']
    idx = 0
    

    
    try:
        while True:
            char = spinner_chars[idx % len(spinner_chars)]
            term_cols = shutil.get_terminal_size((80, 20)).columns
            max_cols = max(30, term_cols - 1)  # 留 1 個 column 絕對防止 Windows 控制台自動換行
            
            if time.time() < notification_expire_time:
                raw_msg = f"[{char}] 💬 {current_system_notification}"
                out_msg = fit_text_to_width(raw_msg, max_cols)
            else:
                # 依據終端寬度動態分配狀態文字與動作文字長度
                if max_cols < 80:
                    status_text = fit_text_to_width(current_ai_status_str, max(24, max_cols - 38))
                    if is_user_listening:
                        elapsed = time.time() - listen_start_time
                        remaining = max(0, LISTEN_LIMIT - int(elapsed))
                        action_text = f"🎤 ({remaining}s)"
                    else:
                        action_text = fit_text_to_width(current_mic_action_str, 8)
                else:
                    status_text = fit_text_to_width(current_ai_status_str, max(38, max_cols - 46))
                    if is_user_listening:
                        elapsed = time.time() - listen_start_time
                        remaining = max(0, LISTEN_LIMIT - int(elapsed))
                        action_text = f"🎤 聆聽 ({remaining}s)"
                    else:
                        action_text = fit_text_to_width(current_mic_action_str, 12)
                    
                raw_msg = f"[{char}] {status_text} | {action_text} | {current_mic_volume_str}"
                out_msg = fit_text_to_width(raw_msg, max_cols)
            
            out_msg = out_msg.replace('\n', ' ').replace('\r', '')
            disp_w = get_display_width(out_msg)
            padding = " " * max(0, max_cols - disp_w)
            
            # 使用 ANSI 擦除 + 精準寬度填充，徹底根除 Windows 終端換行與尾端空格殘影
            print(f"\r\033[2K\r{out_msg}{padding}", end="", flush=True)
            
            idx += 1
            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        print("\n👋 [系統] 收到 Ctrl+C 中斷，正在安全退出...")
    except BaseException as e:
        print(f"\n❌ [底層系統異常崩潰]: {e}")

if __name__ == "__main__":
    asyncio.run(main())
