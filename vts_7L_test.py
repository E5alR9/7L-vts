# ==============================================================================
#  7L AI-VTuber 智慧一體化核心系統 (vts_7L_test.py)
#  作者: E5alR9 & 7L 開發團隊
#  核心特色:
#    -  Google GenAI Live API (全雙工雙向音訊、背景潛意識發言哨兵、雙軌熱備)
#    -  8 大 Gemini 模型智能階梯調度 (3.1 Flash Lite ➔ 3.5 Flash Lite ➔ 3 Flash ➔ 3.1 Pro ➔ 3.5 ➔ 3.6 ➔ 3.7 ➔ 3.8 Flash)
#    -  100 句全景記憶滾動中樞 (Live2D 表情、視線走位、觀眾個人檔案 Firestore 雲端同步)
#    -  88 鍵全音域平台鋼琴即時發聲與 MIDI 智能搜譜演奏
#    -  即時多螢幕視覺感知、眼角餘光與 WASAPI 電腦內部聲音監聽
#    -  Python 本機沙盒遊樂場、Tavily 網路搜尋、Nano 生圖與 Discord CMA 狀態監控
#  腳本模組導覽目錄 (Table of Contents):
#  1.  環境變數載入與金鑰矩陣分流 (API Keys, DualHotStandby Live Manager)
#  2.  模型梯隊清單與排程定義 (GEMINI_MODELS 7-Tier Matrix)
#  3.  API 頻率限制、冷卻與熔斷管理 (Circuit Breaker & Lock Cache)
#  4.  全域狀態變數與硬體環境偵測 (Global State & Resolution)
#  5.  Firebase 雲端永久記憶與觀眾檔案 (Long-Term Memory & Viewer Profile)
#  6.  VTube Studio WebSocket 引擎與 Live2D 控制 (VTSManager & Expression Dispatcher)
#  7.  7L 本機遊樂場沙盒 (7L_Playground Python Sandbox)
#  8.  Google GenAI 官方 Function Calling 工具清單 (GENAI_TOOLS & Dispatcher)
#     8.1  88 鍵平台鋼琴發聲與樂譜演奏引擎 (Virtual Piano 88K & MIDI Player)
#  9.  防跳針與記憶去重系統 (Code-Level Anti-Repetition)
# 10.  語音合成、音訊分析與字幕工具
# 11.  視覺感知、畫面截圖與輕量眼角餘光 (Screen Vision & get_lightweight_gemini_vision)
# 12.  旗艦多模態大腦推理核心 (fetch_ai_response: Gemini Multimodal Dispatcher)
# 13.  使用者指令、電腦控制與計時器動作 (execute_actions & System Controls)
# 14.  專屬背景工作協程群 (Workers: Screen, Vision, WASAPI Loopback Audio, Proactive)
# 15.  對話處理、Live 潛意識哨兵與 100 句記憶中樞 (Mind-Stream & Audience Live Channel)
# 16.  CMA 狀態監控檔案輸出與 Discord 機器人 (CMA Monitor & Discord Bot Commands)
# 17.  主程式進入點與終端機即時狀態列 (main Entry Point & ANSI Status Bar)
# ==============================================================================


import sys
if __name__ == "__main__":
    if "__main__" in sys.modules:
        sys.modules["vts_7L_test"] = sys.modules["__main__"]
    #  單一實例守護：自動終止先前殘留的 vts_7L_test 舊進程，徹底杜絕雙程序同時搶佔 VTS 連線導致對嘴被歸零鎖死
    try:
        import psutil, os
        _curr_pid = os.getpid()
        for _p in psutil.process_iter(['pid', 'name', 'cmdline']):
            if _p.info['pid'] != _curr_pid and _p.info['name'] and 'python' in _p.info['name'].lower():
                _cmd = _p.info.get('cmdline') or []
                if any('vts_7L_test.py' in str(arg) for arg in _cmd):
                    try:
                        _p.kill()
                    except Exception:
                        pass
    except Exception:
        pass

# 原作者本機版 EulerApiSdk 才有 record_string_unknown；PyPI 正式版沒有此符號
# （且下方程式從未實際使用），故改為容錯 import，避免整支程式起不來。
try:
    from EulerApiSdk.models import record_string_unknown  # noqa: F401
except ImportError:
    record_string_unknown = None
from google.genai import types
from services.piano_engine import get_piano_realtime_prompt
from services.piano_engine import is_piano_active
from services.tiktok_listener import tiktok_live_worker
from services.twitch_listener import twitch_live_worker
from services.youtube_live_listener import youtube_live_worker
from services.auto_cover_pipeline import produce_and_sing_cover, stop_singing
import services.web_dashboard as web_dash
from PIL import BmpImagePlugin
from PIL import Image, ImageDraw, ImageGrab, ImageChops
import os
import sys
import io
import copy
import subprocess
import re
import asyncio
import aiohttp
import websockets
import core.websocket_patch  
import pyvts
import services.rag_memory_service as rag_service
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
from typing import Optional, Dict, List, Tuple, Any, Union
import collections
from collections import deque, defaultdict
import shutil
import webbrowser
import platform
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
try:
    #  用「本檔所在目錄」明確載入 .env：dotenv 的 find_dotenv() 是看 cwd，
    #    只要從別處啟動（cwd ≠ 專案根）就會靜默載不到金鑰，
    #    導致 GEMINI_KEYS / GROQ 金鑰 / Discord Token 全部變空卻不報錯。
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass
import ctypes
try:
    from tavily import TavilyClient
except (ImportError, Exception):
    TavilyClient = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

VM_AGENT_CLIENT = None
GLOBAL_INPUT_QUEUE: Optional[asyncio.Queue] = None
input_queue: Optional[asyncio.Queue] = None

import logging

INTERACTIONS_TOOLS = [
    {
        "type": "function",
        "name": "trigger_vts_expression",
        "description": "切換 VTube Studio Live2D 虛擬主播表情",
        "parameters": {
            "type": "object",
            "properties": {
                "expression_name": {"type": "string", "description": "表情名稱：happy, sad, shock, heart, shy, wink, frown, 臉紅, 生氣, 星星眼, 皺眉, 震驚 等"}
            },
            "required": ["expression_name"]
        }
    },
    {
        "type": "function",
        "name": "search_google",
        "description": "使用 Google 搜尋即時聯網資訊與時事",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋關鍵字"}
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "search_knowledge",
        "description": "檢索 7L 本地 RAG 記憶庫（過往對話、觀眾檔案、外部知識文件），回答涉及過去發生過的事或既有資料時優先使用",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要檢索的中文關鍵句（例如：老爸的鍵盤型號、某觀眾的關係）"}
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "generate_ai_image",
        "description": "繪製 AI 圖片",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "繪圖提示詞 (英文佳)"}
            },
            "required": ["prompt"]
        }
    },
    {
        "type": "function",
        "name": "move_spatial_position",
        "description": "控制 7L 的 Live2D 模型在畫布內平滑走位、相對微調或縮放大小。支援命名位置（如：'正中間', '鋼琴旁', '靠近', '躲角落', '左側', '右側', '原位'）以及相對微調（如：'往右+10', '往左-15', '往上+5', '往下-10', '放大+10', '縮小-5'）或直接指定 delta_x / delta_y / delta_size。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_position": {"type": "string", "description": "目標位置名稱或微調指令：例如 '正中間', '鋼琴旁', '靠近', '躲角落', '左邊', '右邊', '原位', '往右+10', '往左-15', '往上+5', '往下-10', '放大+10', '縮小-5', '自由漫遊'"},
                "delta_x": {"type": "number", "description": "X 軸相對平移量（例如: +10 代表向右微調, -10 代表向左微調）"},
                "delta_y": {"type": "number", "description": "Y 軸相對平移量（例如: +10 代表向上微調, -10 代表向下微調）"},
                "delta_size": {"type": "number", "description": "尺寸相對縮放量（例如: +5 代表放大, -5 代表縮小）"},
                "scale_factor": {"type": "number", "description": "整體等比例縮放倍率（例如: 1.2 放大 20%, 0.8 縮小 20%）"}
            },
            "required": ["target_position"]
        }
    },
    {
        "type": "function",
        "name": "open_virtual_piano",
        "description": "拿出 88 鍵鋼琴介面在桌面上就位待命。當老爸說『拿出鋼琴』、『打開鋼琴』、『把鋼琴拿出來』時調用（不自動彈奏曲目，供老爸練習、彈奏或點歌）。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.play_virtual_piano",
        "description": "7L 坐到鋼琴前演奏 88 鍵平台鋼琴曲目。【極嚴格調用限制】：只有當老爸或觀眾明確要求『彈鋼琴』、『彈琴』、『彈一首...』、『點歌：...』或『youtuber查...然後彈』時才可調用！當對方只是說日常對話、自我介紹、開場（例如『INTRO 吧』、『自我介紹』、『開場介紹』、『哈囉』、『聊聊天』）時，【絕對嚴禁調用此工具】！直接進行口頭對話或自介即可。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {"type": "string", "description": "鋼琴曲名稱、關鍵字或 YouTube 搜尋詞 (如：鐘, 幻想即興曲, 愛之夢, 給愛麗絲, 卡農, 敘事曲, 神隱少女, 殘酷天使, 千本櫻等)"},
                "force_online": {"type": "boolean", "description": "當使用者指定「用 YouTube 查」、「youtuber 查」、「線上搜」、「yt 查」等關鍵字時【務必設為 True】，系統將強制跳過本地樂譜，直接向 YouTube/線上即時抓取最新演奏版本開彈。"},
                "auto_radio_mode": {"type": "boolean", "description": "當說『接著一直隨便彈吧』、『隨便彈』、『隨機一直彈』、『連續彈』、『開啟鋼琴電台』時設為 True，進入無限隨機接曲模式。"},
                "custom_sheet": {"type": "string", "description": "可選自訂虛擬鋼琴樂譜字串"}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.play_midi_band",
        "description": " MIDI 樂隊演奏：多軌 MIDI 保留原通道＋音色同時發聲（小提琴拉主旋律＋鋼琴伴奏＋貝斯＋鼓組一次到位）。當老爸或觀眾說『樂隊演奏』、『多種樂器一起』、『小提琴加鋼琴』、『完整編制』時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "midi_file": {"type": "string", "description": "本地 .mid 檔案路徑（midi_sheets/ 下）"},
                "band_preset": {"type": "string", "description": "配器預設：piano_trio／violin_lead／guitar_band／strings／rock_band／jazz_trio／brass_band／folk_band／synth_band／orchestra"},
                "layers": {"type": "string", "description": "疊層合奏（可選）：更多 .mid 路徑逗號分隔，同時合奏"},
                "title": {"type": "string", "description": "曲名（播報用）"}
            },
            "required": ["midi_file"]
        }
    },
    {
        "type": "function",
        "name": "pe.compose_and_play_original_piano",
        "description": "7L 現場自主即興作曲並親自演奏原創 88 鍵鋼琴曲。當老爸或觀眾說『妳自己寫一首歌來彈』、『現場自創一首』、『即興彈一首』、『自己創作一首鋼琴曲』、『來首妳自己原創的曲子』時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "theme_or_title": {"type": "string", "description": "想要創作的曲目主題或名稱 (如：'星空漫步', '午後微風', '給老爸的歌')"},
                "mood_or_style": {"type": "string", "description": "音樂風格與情緒氛圍 (如：'治癒抒情', '日系ACG', '輕快俏皮', '溫柔憂傷')"}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "video.request_watch",
        "description": " 觀眾點播看全片：把 YouTube 網址排入點播隊列，7L 後台看完播報（字幕→音軌轉錄→抽幀看圖→摘要）。當觀眾說『看這個』、『點播』、『幫我看這部片』並貼網址時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 影片網址或 11 碼 ID"}
            },
            "required": ["url"]
        }
    },
    {
        "type": "function",
        "name": "music.generate_song",
        "description": " AI 作曲（ACE-Step 本地服務）：文字→完整歌曲（含人聲編曲，慢任務）。當老爸或觀眾說『寫一首歌』、『AI 作曲』、『生成一首歌』時調用！（需 ACESTEP_ENABLED=1，否則安全跳過）",
        "parameters": {
            "type": "object",
            "properties": {
                "caption": {"type": "string", "description": "風格描述（如：溫柔抒情流行歌、鋼琴+弦樂、128BPM）"},
                "lyrics": {"type": "string", "description": "歌詞（可空，空＝純音樂）"},
                "duration": {"type": "integer", "description": "時長秒數（10-600，預設 120）"},
                "style": {"type": "string", "description": "補充風格標籤"}
            },
            "required": ["caption"]
        }
    },
    {
        "type": "function",
        "name": "midi.inspect",
        "description": " 讀譜：看 MIDI 檔的軌數／音符數／時長／各軌音色音域。改編前先看結構時調用！",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "midi_sheets/ 下檔名或完整路徑"}
            },
            "required": ["path"]
        }
    },
    {
        "type": "function",
        "name": "midi.edit",
        "description": " 改譜：移調／力度／量化／換音色／加音符／刪音區（二選一動作 op）。當老爸或觀眾說『升調』、『對齊拍子』、『小聲點』、『換小提琴』、『加一段』時調用！改完自動進曲庫，可直接 pe.play_midi_band 演奏。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "midi_sheets/ 下檔名或完整路徑"},
                "op": {"type": "string", "description": "transpose（需 semitones）／velocity（需 scale）／quantize（grid 4/8/16/32）／program（需 channel＋program）／add（需 notes JSON 陣列）／delrange（需 lo＋hi）"},
                "semitones": {"type": "integer", "description": "移調半音數"},
                "scale": {"type": "number", "description": "力度倍率 0.1-2.0"},
                "grid": {"type": "string", "description": "量化網格"},
                "channel": {"type": "integer", "description": "通道 0-15（鼓 9 拒絕）"},
                "program": {"type": "integer", "description": "音色 0-127"},
                "notes": {"type": "string", "description": "加音符 JSON 陣列 [{pitch,start_beat,duration_beats,velocity,channel}]"},
                "lo": {"type": "integer", "description": "刪音區下限"},
                "hi": {"type": "integer", "description": "刪音區上限"}
            },
            "required": ["path", "op"]
        }
    },
    {
        "type": "function",
        "name": "music.transcribe_song",
        "description": " 逆向譜面：YT 下載音檔→人聲分離→旋律轉 MIDI＋和弦辨識→進曲庫。當老爸或觀眾說『把這首歌扒下來』、『轉成譜』、『學這首歌』並貼網址時調用！（慢任務，後台跑）",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 網址或 11 碼 ID"},
                "title": {"type": "string", "description": "存檔曲名（可空）"}
            },
            "required": ["url"]
        }
    },
    {
        "type": "function",
        "name": "music.stem_pack",
        "description": " 扒帶包：一鍵產出分軌（人聲/鼓/貝斯/吉他/鋼琴/其他）＋去人聲卡拉＋75%降速＋和弦進行＋旋律MIDI。當老爸或觀眾說『扒這首歌』、『要伴奏』、『分軌』並貼網址時調用！（慢任務，十幾分鐘）",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 網址或 11 碼 ID"}
            },
            "required": ["url"]
        }
    },
    {
        "type": "function",
        "name": "pe.mashup_virtual_piano",
        "description": "7L 將多首高難度鋼琴曲同時並發演奏 (無數量限制！可同時彈 2首、3首、4首甚至更多，多軌多色瀑布流極限演奏)。當老爸或觀眾說『把A跟B混在一起彈』、『同時彈A、B、C』、『A x B x C 合體』、『A + B + C 多曲合奏』、『把多首練習曲雜在一起彈』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name1": {"type": "string", "description": "第一首鋼琴曲名稱或包含多首曲目的字串 (例如：'冬風', '鐘', '月光第三樂章', 'Rush E', '冬風 x 月光 x 鐘')"},
                "song_name2": {"type": "string", "description": "第二首鋼琴曲名稱 (可選)"}
            },
            "required": ["song_name1"]
        }
    },
    {
        "type": "function",
        "name": "pe.insert_virtual_piano",
        "description": " 嚴格限制：僅在老爸或觀眾明確說『混彈』、『插歌』、『一起彈』、『合體』、『同時演奏』、『再加一首XX一起彈』等字眼時才可調用！若只是單純點播新歌（例如只說『Rush E』、『彈月光』），【絕對嚴禁調用此工具】，必須調用 pe.play_virtual_piano 進行排隊！",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {"type": "string", "description": "要插入/追加的鋼琴曲名稱 (如：鐘, 幻想即興曲, 冬風, 少女的祈禱)"}
            },
            "required": ["song_name"]
        }
    },
    {
        "type": "function",
        "name": "pe.pause_virtual_piano",
        "description": "暫停當前正在演奏的 88 鍵鋼琴曲目。當老爸或觀眾說『暫停彈琴』、『鋼琴先暫停』、『暫停一下』時調用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.resume_virtual_piano",
        "description": "繼續播放剛才暫停的 88 鍵鋼琴曲目。當老爸或觀眾說『繼續彈』、『鋼琴繼續』、『恢復演奏』時調用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "pe.stop_virtual_piano",
        "description": " 嚴禁隨意調用！僅在老爸明確說出『收起鋼琴』、『關閉鋼琴』、『把鋼琴收起來』、『別彈鋼琴了』時才可調用！收起 88 鍵鋼琴並讓 7L 回到原本位置。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "list_piano_sheets",
        "description": "【只有當老爸或觀眾明確要求『列出所有曲庫/查看歌單』時才調用】列出所有內建鋼琴曲目清單。注意：若只是問『這首是什麼歌』，嚴禁調用此工具，直接回答當前曲名即可。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "auto_sing_song",
        "description": "7L 進行全自動 AI 翻唱演唱（支援全網 YouTube 點歌、伴奏分離、少女音色轉換與立體聲母帶混音）。當老爸或觀眾說『唱歌』、『唱一首...』、『翻唱...』、『唱 Never Gonna Give You Up』、『點歌：...（唱歌）』時調用！注意：若是彈鋼琴請調用 pe.play_virtual_piano，若是唱歌/翻唱請調用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {"type": "string", "description": "想要 7L 翻唱的歌曲名稱或關鍵字 (如：Never Gonna Give You Up, 晴天, 小幸運, 千本櫻等)"}
            },
            "required": ["song_name"]
        }
    },
    {
        "type": "function",
        "name": "set_piano_volume",
        "description": "調整 88 鍵平台鋼琴的演奏音量 (0 ~ 200)。【嚴格限制】：只有當老爸或觀眾明確說『鋼琴小聲點』、『鋼琴大聲點』、『音量設為...』時才可調用！絕對嚴禁在日常聊天、點歌或開場時擅自調用或重置音量！",
        "parameters": {
            "type": "object",
            "properties": {
                "volume": {"type": "integer", "description": "音量數值，範圍 0 到 200（0 為靜音，100 為預設標準音量，200 為雙倍增益音量）"}
            },
            "required": ["volume"]
        }
    },
    {
        "type": "function",
        "name": "set_piano_speed",
        "description": "調整 88 鍵平台鋼琴的演奏倍速 (0.05x ~ 50.0x / 支援任意自訂倍速數字)。當老爸或觀眾說『鋼琴放慢一點』、『鋼琴快一點』、『鋼琴1.5倍速』、『2倍速彈鋼琴』、『4倍速』、『10倍速』、『原速彈』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "description": "播放倍速，支援任意自訂數值（例如 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.5, 4.0, 5.0, 10.0 等，範圍 0.05 到 50.0）"}
            },
            "required": ["speed"]
        }
    },
    {
        "type": "function",
        "name": "set_piano_instrument",
        "description": "切換 88 鍵鋼琴/鍵盤的演奏發聲音色。當老爸說『換成弦樂音色』、『換成吉他』、『切換成電鋼琴』、『用小提琴彈』、『換成管風琴』、『音色換成木琴』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "想要切換的音色名稱，如：'鋼琴'、'明亮鋼琴'、'電鋼琴'、'大鍵琴'、'木琴'、'管風琴'、'手風琴'、'吉他'、'電吉他'、'小提琴'、'大提琴'、'豎琴'、'弦樂'、'人聲合唱'、'小號'、'薩克斯風'、'長笛'、'合成器'、'古箏'、'卡林巴'"}
            },
            "required": ["instrument"]
        }
    },
    {
        "type": "function",
        "name": "control_microphone",
        "description": " 嚴禁自主隨意調用！僅在老爸明確說出『關閉麥克風』或『開啟麥克風』時才可調用！開啟(True)或關閉(False)麥克風收音。",
        "parameters": {
            "type": "object",
            "properties": {
                "is_enabled": {"type": "boolean", "description": "True 為開啟收音，False 為靜音"}
            },
            "required": ["is_enabled"]
        }
    },
    {
        "type": "function",
        "name": "clear_all_memories",
        "description": "清空 7L 的雲端與本地記憶",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "update_cloud_knowledge",
        "description": "7L 自主更新或記憶雲端大腦認知庫與提示詞（Firestore 永久大腦）。當學到新梗、新知識、老爸習慣、或想調整世界觀/說話風格/案例/心智規範時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "提示詞/認知類別：'persona_core'（核心世界觀/自我認知）、'conversation_style'（講話風格/語調）、'memes'（流行語與梗）、'facts'（學會的事實/偏好）、'rules'（心智規範）、'streamer_bio'（直播人設）、'proactive_guide'（主動發話引導）、'banned_phrases'（禁忌詞）"
                },
                "content": {
                    "type": "string",
                    "description": "要寫入或記憶的內容描述（例如：'笑死（極度好笑）' 或 '老爸喜歡深夜寫 Python' 或 '極致俐落搞笑'）"
                }
            },
            "required": ["category", "content"]
        }
    }
]

def build_genai_declarations(is_proactive=False):
    decls = []
    for tool in INTERACTIONS_TOOLS:
        if is_proactive and tool["name"] in ["control_microphone", "clear_all_memories"]:
            continue
        props = {}
        for p_name, p_spec in tool.get("parameters", {}).get("properties", {}).items():
            p_type = p_spec.get("type", "string").upper()
            if p_type == "BOOLEAN": p_type = "BOOLEAN"
            elif p_type in ["NUMBER", "INTEGER", "FLOAT"]: p_type = "NUMBER"
            else: p_type = "STRING"
            props[p_name] = types.Schema(
                type=p_type,
                description=p_spec.get("description", "")
            )
        decl = types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=types.Schema(
                type="OBJECT",
                properties=props,
                required=tool.get("parameters", {}).get("required", [])
            )
        )
        decls.append(decl)
    
    tool_list = [types.Tool(function_declarations=decls)]
    if is_proactive:
        try:
            tool_list.append(types.Tool(google_search=types.GoogleSearch()))
        except Exception:
            pass # Fallback in case types.GoogleSearch is missing in an older SDK version
    return tool_list




#  靜音所有第三方日誌與 AFC 警告，保持控制台狀態列極致純淨
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"
warnings.filterwarnings("ignore")

for log_name in ["google", "google.genai", "google_genai", "google.genai.models", "absl", "urllib3", "asyncio"]:
    logging.getLogger(log_name).setLevel(logging.ERROR)

try:
    if hasattr(sc, "SoundcardRuntimeWarning"):
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
except Exception:
    pass

#  設定 Windows 控制台為 UTF-8 代碼頁 (CP 65001) 並開啟 ANSI 虛擬終端處理，徹底修復中文字元重複、動態刷新與換行殘影
if sys.platform == "win32":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
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

from core.utils import (
    log_print, sys_notify, get_current_time_string, get_unified_time_prompt,
    record_interaction_tick, get_silence_ticks, get_uptime_ticks, format_ticks_to_human,
    speech_allowed, operator_input_enabled
)
from core.db import *
from core.live_timer_sensor import live_timer_hub
import services.piano_engine as pe
import services.yt_companion_service as yt_comp
from core.llm_engine import (
    GEMINI_KEYS,
    KEYS_AUDIENCE_LIVE,
    KEYS_MIND_LIVE,
    KEYS_VISION,
    DEAD_GEMINI_MODELS,
    STREAMER_MIND_MODELS,
    HIGH_IQ_GEMINI_MODELS,
    PROACTIVE_EXCLUDED_MODELS,
    GROQ_CLIENTS,
    DualHotStandbyLiveManager,
    get_dynamic_live_key_candidates,
    UNRESTRICTED_SAFETY_SETTINGS
)
from core.memory import init_unified_memory, fetch_from_long_term_memory, save_to_long_term_memory, append_to_unified_memory, clear_all_memories, get_recent_100_memory_context, get_viewer_profile, save_viewer_profile, record_bot_message, get_cloud_knowledge, update_cloud_prompt_field, UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY, get_recent_thoughts_by_chars, TIKTOK_CHATROOM_MEMORY, STREAMER_MIND_BOARD, DEFAULT_CHANNEL_ID, save_cloud_knowledge, get_unified_memory_context, RECENT_BOT_MESSAGES, evaluate_memory_demand, MemoryDemandLevel, USER_PROFILE_FILE, MODE







def get_seconds_until_pt_midnight() -> float:
    """計算從現在到美國太平洋時間 (PT) 下一個午夜 00:00 還剩多少秒（用於每日配額 RPD 刷新）"""
    try:
        pt_zone = ZoneInfo("America/Los_Angeles")
        now_pt = datetime.now(pt_zone)
        tomorrow_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        diff = (tomorrow_pt - now_pt).total_seconds()
        return max(60.0, diff)
    except Exception:
        return 3600.0

def record_model_failure(model_name: str, err_str: str):
    
    MODEL_FAIL_COUNT[model_name] = MODEL_FAIL_COUNT.get(model_name, 0) + 1
    #  換模型門檻：依序輪詢 API 金鑰總數的 2/3，輪完 2/3 都失敗才切換下一個備用模型
    num_keys = len(GEMINI_KEYS)
    threshold = max(3, int(math.ceil(num_keys * 2.0 / 3.0))) if num_keys > 0 else 4
    if MODEL_FAIL_COUNT[model_name] >= threshold:
        if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
            reason = f"依序輪詢 {threshold} 把金鑰均遇 503 伺服器超載"
            m_duration = 180.0  # 503 模型級熔斷 3 分鐘
        elif "429" in err_str or "rate limit" in err_str:
            reason = f"依序輪詢 {threshold} 把金鑰均遇 429 頻率上限"
            m_duration = 60.0
        else:
            reason = f"依序輪詢 {threshold} 把金鑰均異常"
            m_duration = 60.0
        lock_entire_model(model_name, duration=m_duration, reason=reason)
        MODEL_FAIL_COUNT[model_name] = 0

def get_prioritized_gemini_models(user_query: str = "", has_image: bool = False, is_proactive: bool = False) -> list:
    """根據老爸當前的對話指令與多模態情境，動態計算專屬的模型升級排程佇列"""
    q = (user_query or "").lower()
    
    #  高智商需求識別：找歌/點歌、寫代碼、數學邏輯、哲學推理、複雜指令等，倒序由 3.8 頂配大腦領銜！
    high_iq_keywords = [
        "寫程式", "寫代碼", "python", "程式碼", "找歌", "點歌", "彈琴", "彈一首", "鋼琴", "曲名", "分析",
        "為什麼", "哲學", "算一下", "計算", "深度思考", "邏輯", "推理", "詳細解說", "找譜", "查歌",
        "搜尋", "查一下", "上網查", "深奧", "解釋", "差別", "冬風", "蕭邦", "李斯特", "貝多芬", "巴哈"
    ]
    is_high_iq = any(k in q for k in high_iq_keywords)
    
    if is_high_iq:
        priority_heads = list(HIGH_IQ_GEMINI_MODELS)
    else:
        #  根據實測速度極速排列 (越快排越前面 1 ➔ 7)
        priority_heads = [
            "gemini-3.5-flash-lite",               #  第 1 位：0.95s ~ 1.21s 極速秒回王 (超低延遲輕量防線)
            "gemini-3.6-flash",                    #  第 2 位：1.59s 高智商極速主力 (兼具高智商與超低延遲)
            "gemini-3.1-flash-lite",               #  第 3 位：1.6s ~ 3.3s 自然口語秒回首選
            "gemini-3-flash-preview",              #  第 4 位：3.1s ~ 4.2s 閃電推理預覽
            "gemini-3.5-flash",                    #  第 5 位：10s ~ 14s 高智商穩定主力保底
            "gemini-3.7-flash",                    #  第 6 位：頂配旗艦大腦
            "gemini-3.8-flash",                    #  第 7 位：2026 全新頂配旗艦大腦
        ]
        
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

def get_pingpong_alternating_index(total_keys: int, step: int) -> int:
    """交替序輪演算法 (頭尾交替向內輪播: 這次 1 -> 下次 29 -> 下次 2 -> 下次 28 -> 下次 3 -> 下次 27 ...)"""
    if total_keys <= 0:
        return 0
    cycle_step = step % total_keys
    if cycle_step % 2 == 0:
        idx = cycle_step // 2
    else:
        idx = total_keys - 1 - (cycle_step // 2)
    return max(0, min(total_keys - 1, idx))

def get_pingpong_ring_indices(total_keys: int, start_step: int) -> list:
    """從當前交替序輪步數開始，產生完整的交替序輪檢查序列 (每個 key 恰好出現一次)"""
    if total_keys <= 0:
        return []
    indices = []
    for i in range(total_keys):
        idx = get_pingpong_alternating_index(total_keys, start_step + i)
        if idx not in indices:
            indices.append(idx)
    for i in range(total_keys):
        if i not in indices:
            indices.append(i)
    return indices

def get_available_gemini_channels(limit=1, user_query="", has_image=False, is_proactive=False):
    
    available = []
    target_keys = KEYS_PROACTIVE if is_proactive and KEYS_PROACTIVE else GEMINI_KEYS
    num_keys = len(target_keys)
    if num_keys == 0: return available
    
    #  智能任務定向分流：取得階梯排程模型佇列
    target_models = get_prioritized_gemini_models(user_query=user_query, has_image=has_image, is_proactive=is_proactive)
    valid_models = [m for m in target_models if m not in DEAD_GEMINI_MODELS and not is_model_locked(m)]
    if not valid_models:
        valid_models = [m for m in GEMINI_MODELS if m not in DEAD_GEMINI_MODELS]
        
    ring_indices = get_pingpong_ring_indices(num_keys, CURRENT_GEMINI_KEY_STEP)
    
    #  階梯升級輪派策略：依序為各階模型挑選最優可用金鑰，每次失敗或超時立即升級至下一階更高級模型！
    for m_idx, g_model in enumerate(valid_models):
        short_m = g_model.replace("gemini-", "")
        for idx in ring_indices:
            target_id = f"G{idx}_{short_m}"
            if not is_locked(target_id) and (target_keys[idx], g_model, target_id) not in available:
                available.append((target_keys[idx], g_model, target_id))
                break # 每一階挑選一把最佳金鑰後，優先為下一階模型排入通道！
        if len(available) >= limit:
            return available

    # 若尚未填滿 limit，補充其他未鎖定通道
    if len(available) < limit:
        for g_model in valid_models:
            short_m = g_model.replace("gemini-", "")
            for idx in ring_indices:
                target_id = f"G{idx}_{short_m}"
                if not is_locked(target_id) and (target_keys[idx], g_model, target_id) not in available:
                    available.append((target_keys[idx], g_model, target_id))
                    if len(available) >= limit:
                        return available

    return available

GENAI_TOOLS = build_genai_declarations(is_proactive=False)

GENAI_PROACTIVE_TOOLS = build_genai_declarations(is_proactive=True)

async def summarize_search_to_speech(query: str, search_raw: str, user_role_name: str = "老爸") -> str:
    """PROVIDER: GROQ（core.groq_router.groq_chat 純文字提煉；見 docs/AI_SOURCES.md）"""
    """將搜尋到的原始資料，以 7L 招牌自然口語（1~3 句，親切隨性）進行提煉整理。
    具備多模型與多金鑰自動容災（Gemini Flash Lite -> Groq LLaMA -> 本機提煉器），絕不直接傾倒原文！"""
    global CURRENT_GEMINI_KEY_STEP
    if not search_raw or "搜尋無結果" in search_raw:
        return f"{user_role_name}，我幫你查了一下，但目前網路上沒有找到相關的資料耶。"

    # 清理搜尋字串，避免傳入過大 token
    clean_search = re.sub(r'https?://\S+', '', search_raw)
    clean_search = re.sub(r'\s{2,}', ' ', clean_search).strip()[:1500]

    #  第 0 防線：Groq 極速提煉（第一梯隊，實測 0.4s 級；失敗或無結果才交給下方 Gemini）
    try:
        from core.groq_router import groq_chat
        g_resp = await groq_chat(
            [
                {"role": "system", "content": "妳是虛擬主播 7L，負責把搜尋原始資料轉成自然口語。嚴禁 Emoji、嚴禁照抄條列清單、網址或網頁標題，只講核心意思。"},
                {"role": "user", "content": f"查詢：{query}\n\n搜尋原始資料：\n{clean_search}\n\n請以親切隨性的口吻，用 1~3 句俐落短句（40~80 字以內）對{user_role_name}提煉並說明重點。"},
            ],
            temperature=0.75, max_tokens=500, timeout=4.5,
        )
        if g_resp and g_resp.text:
            ans = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', g_resp.text).strip()
            if ans and not ans.startswith("(") and len(ans) > 5:
                return ans
    except Exception:
        pass

    # 1. 第一防線：極速、高可用性的 Gemini Flash Lite 模型提煉 (抗 503、0.8s 響應)
    lite_models = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]
    if GEMINI_KEYS:
        for k_offset in [0, 1]:
            target_k_idx = get_pingpong_alternating_index(len(GEMINI_KEYS), CURRENT_GEMINI_KEY_STEP + k_offset)
            CURRENT_GEMINI_KEY_STEP += 1
            client = genai.Client(api_key=GEMINI_KEYS[target_k_idx])
            for m_name in lite_models:
                try:
                    prompt = f"""妳是 7L，正在直播中與{user_role_name}聊天。
【任務】：剛才針對「{query}」查詢到的最新情報如下：
\"\"\"
{clean_search}
\"\"\"
請以妳招牌親切、自然隨性的口吻，用 1~3 句俐落短句（40~80字以內）直接對{user_role_name}提煉並說明重點。
 嚴格規範：
- 絕對不要直接照抄條列清單、網址或網頁標題。
- 像真人日常說話一樣自然流暢，直接講出核心意思。
- 嚴禁使用任何 Emoji。"""
                    resp = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=m_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.75,
                                max_output_tokens=500,
                                safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                            )
                        ),
                        timeout=4.5
                    )
                    if resp and resp.text and resp.text.strip():
                        ans = resp.text.strip()
                        ans = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', ans).strip()
                        if ans and not ans.startswith("(") and len(ans) > 5:
                            return ans
                except Exception:
                    continue

    # 2. 第二防線：Groq 超極速模型 (0.3s 提煉)
    if GROQ_CLIENTS:
        for g_client in GROQ_CLIENTS[:3]:
            try:
                g_resp = await asyncio.wait_for(
                    g_client.chat.completions.create(
                        model="qwen/qwen3.8-27b",
                        messages=[
                            {"role": "system", "content": f"妳是 7L，正在直播中與{user_role_name}對話。請以親切隨性口吻（1~2句短句）提煉搜尋重點回答{user_role_name}，嚴禁照搬原文清單，嚴禁 Emoji。"},
                            {"role": "user", "content": f"查詢問題: {query}\n搜尋內容: {clean_search[:800]}"}
                        ],
                        max_tokens=120,
                        temperature=0.7
                    ),
                    timeout=3.0
                )
                if g_resp.choices and g_resp.choices[0].message.content:
                    ans = g_resp.choices[0].message.content.strip()
                    if ans:
                        return ans
            except Exception:
                continue

    # 3. 第三防線：純本地智慧摘要器（100% 離線可用，絕不傾倒條列與 URL）
    lines = [l.strip() for l in search_raw.split('\n') if l.strip()]
    snippets = []
    for l in lines:
        clean_l = re.sub(r'^[-\d.*#\s]+', '', l)
        if ':' in clean_l:
            clean_l = clean_l.split(':', 1)[1].strip()
        clean_l = re.sub(r'https?://\S+', '', clean_l).strip()
        if len(clean_l) > 15:
            snippets.append(clean_l)
        if len(snippets) >= 2:
            break

    if snippets:
        summary_core = "，".join(snippets)
        if len(summary_core) > 90:
            summary_core = summary_core[:85] + "等等"
        return f"{user_role_name}，我幫你查到囉！大致上來說，{summary_core}。詳細內容我待會再幫你細看喔！"
    return f"{user_role_name}，我剛剛幫你查了，但搜尋到的內容有點繁雜，我待會再仔細整理跟你說！"

#  觀眾側（caller_target="audience"）禁止呼叫的破壞性工具：防直播間彈幕 prompt injection
_AUDIENCE_DENIED_TOOLS = frozenset({
    "clear_all_memories", "update_cloud_knowledge", "set_sleep_mode",
    "open_browser", "control_microphone",
})


async def execute_tool_dispatch(fn_name: str, fn_args: dict, caller_target: str = "", caller_user: str = "") -> str:
    """集中式工具調用派發器 (100% 執行底層動作，完全由 AI 自由發揮台詞，絕不硬塞罐頭文字)"""
    #  觀眾不可觸發破壞性工具（清記憶/改人格/睡眠/開瀏覽器/麥克風）
    if caller_target == "audience" and (fn_name or "").strip().lower() in _AUDIENCE_DENIED_TOOLS:
        log_print(f"🛑 [工具權限] 拒絕觀眾側呼叫 {fn_name}（{caller_user}）")
        return f" 權限不足：{fn_name} 僅限操作者使用"
    extracted_text = ""
    fn_name = (fn_name or "").strip().lower()
    fn_args = {k.lower(): v for k, v in fn_args.items()} if isinstance(fn_args, dict) else {}
    if fn_name == "trigger_vts_expression":
        exp_name = fn_args.get("expression_name", "")
        extracted_text += f" [EXPRESSION: {exp_name}]"
    elif fn_name == "search_google":
        q = fn_args.get("query", "")
        res = await asyncio.to_thread(search_google, q)
        return res
    elif fn_name in ["generate_ai_image", "draw_illustration"]:
        p = fn_args.get("prompt", "")
        asyncio.create_task(generate_ai_image(p))
    elif fn_name == "execute_local_python_code":
        c = fn_args.get("code_string", "")
        asyncio.create_task(execute_local_python_code(c))
    elif fn_name == "move_spatial_position":
        t_pos = fn_args.get("target_position", "自由漫遊")
        sf = fn_args.get("scale_factor")
        dx = fn_args.get("delta_x")
        dy = fn_args.get("delta_y")
        ds = fn_args.get("delta_size")
        dur = float(fn_args.get("duration", 2.0))
        asyncio.create_task(apply_spatial_position(
            position_name=t_pos, 
            delta_x=dx,
            delta_y=dy,
            delta_size=ds,
            scale_factor=sf,
            duration=dur
        ))
    elif fn_name in ["open_virtual_piano", "pe.open_virtual_piano"]:
        await pe.open_virtual_piano()
        extracted_text += " [OPEN_VIRTUAL_PIANO]"
    elif fn_name in ["pe.play_virtual_piano", "play_virtual_piano"]:
        s_name = fn_args.get("song_name", "")
        c_sheet = fn_args.get("custom_sheet", "")
        a_radio = fn_args.get("auto_radio_mode", False)
        f_online = fn_args.get("force_online", False)
        req_t = caller_target or ("audience" if CURRENT_SPEAKING_TARGET == "audience" else "dad")
        req_u = caller_user or ("大家 / 直播觀眾" if req_t == "audience" else "老爸")
        p_res = await pe.play_virtual_piano(s_name, c_sheet, auto_radio_mode=a_radio, force_online=f_online, requester_name=req_u, target=req_t, is_direct_song_name=True)
        #  絕不將內部系統提示拼入 extracted_text 作為語音口語！
        if p_res and "[EXPRESSION:" in p_res:
            extracted_text += f" {p_res}"
    elif fn_name in ["music.generate_song", "generate_song"]:
        import services.acestep_music as _am
        _cap = fn_args.get("caption", "")
        _lyr = fn_args.get("lyrics", "")
        _dur = int(fn_args.get("duration", 120) or 120)
        _sty = fn_args.get("style", "")
        _res = await _am.generate_song(_cap, _lyr, _dur, _sty)
        if _res.get("ok"):
            extracted_text += f" （系統回報：AI 作曲已生成（{_res.get('file', '')}），請播報）"
        else:
            extracted_text += f" （系統回報：AI 作曲失敗：{_res.get('error', '')}）"
    elif fn_name in ["midi.inspect", "inspect_midi"]:
        import services.midi_editor as _me
        _info = _me.inspect_midi(fn_args.get("path", ""))
        extracted_text += f" （系統回報：讀譜：{_info if isinstance(_info, str) else str(_info)[:500]}）"
    elif fn_name in ["midi.edit", "edit_midi"]:
        import services.midi_editor as _me2
        _op = str(fn_args.get("op", "")).lower()
        _mp = fn_args.get("path", "")
        _r = {"ok": False, "error": f"未知 op：{_op}"}
        try:
            if _op == "transpose":
                _r = _me2.transpose(_mp, int(fn_args.get("semitones", 0)))
            elif _op == "velocity":
                _r = _me2.set_velocity(_mp, float(fn_args.get("scale", 1.0)))
            elif _op == "quantize":
                _r = _me2.quantize(_mp, str(fn_args.get("grid", "16")))
            elif _op == "program":
                _r = _me2.set_program(_mp, int(fn_args.get("channel", 0)), int(fn_args.get("program", 0)))
            elif _op == "add":
                import json as _js
                _notes = fn_args.get("notes", "[]")
                _notes = _js.loads(_notes) if isinstance(_notes, str) else _notes
                _r = _me2.add_notes(_mp, _notes)
            elif _op == "delrange":
                _r = _me2.delete_pitch_range(_mp, int(fn_args.get("lo", 0)), int(fn_args.get("hi", 127)))
        except Exception as _e:
            _r = {"ok": False, "error": str(_e)[:150]}
        extracted_text += f" （系統回報：改譜 {_op}：{str(_r)[:300]}）"
    elif fn_name in ["pe.play_midi_band", "play_midi_band"]:
        mf = fn_args.get("midi_file", "")
        preset = fn_args.get("band_preset", "")
        b_title = fn_args.get("title", "")
        bmap = dict(pe.BAND_PRESETS.get(preset, pe.BAND_PRESETS["piano_trio"])) if preset in pe.BAND_PRESETS else None
        _layers = []
        for i, lp in enumerate(str(fn_args.get("layers", "") or "").replace(";", ",").split(",")):
            lp = lp.strip()
            if lp and os.path.exists(lp):
                _layers.append({"midi_path": lp, "channel_shift": 4 * (i + 1), "program": None})
        req_t = caller_target or ("audience" if CURRENT_SPEAKING_TARGET == "audience" else "dad")
        band_res = await pe.play_midi_band(mf, band_map=bmap, title=b_title or os.path.basename(mf), layers=_layers)
        if band_res and "[EXPRESSION:" in band_res:
            extracted_text += f" {band_res}"
    elif fn_name in ["video.request_watch", "request_watch"]:
        vw_url = fn_args.get("url", "")
        req_u = caller_user or "觀眾"
        vw_res = await video_watch.request_watch(vw_url, requester=req_u)
        if vw_res.get("ok"):
            extracted_text += f" （系統回報：已排入點播隊列，看完播報）" if vw_res.get("queued") else f" （系統回報：該片已在隊列中）"
        else:
            extracted_text += f" （系統回報：點播失敗：{vw_res.get('error', '')}）"
    elif fn_name in ["pe.compose_and_play_original_piano", "compose_and_play_original_piano"]:
        theme = fn_args.get("theme_or_title", "")
        mood = fn_args.get("mood_or_style", "")
        req_t = caller_target or ("audience" if CURRENT_SPEAKING_TARGET == "audience" else "dad")
        req_u = caller_user or ("大家 / 直播觀眾" if req_t == "audience" else "老爸")
        cp_res = await pe.compose_and_play_original_piano(theme, mood, requester_name=req_u, target=req_t)
        if cp_res and "[EXPRESSION:" in cp_res:
            extracted_text += f" {cp_res}"
    elif fn_name in ["music.transcribe_song", "transcribe_song"]:
        import services.audio_to_score as _as
        _tres = await _as.transcribe_song(fn_args.get("url", ""), fn_args.get("title", ""))
        if _tres.get("ok"):
            extracted_text += (f" （系統回報：逆向完成（{_tres['notes']} 音符，和弦 {_tres['chords']}）"
                               f"→ {os.path.basename(_tres['file'])}，已進曲庫可演奏）")
        else:
            extracted_text += f" （系統回報：逆向失敗：{_tres.get('error', '')}）"
    elif fn_name in ["music.stem_pack", "stem_pack"]:
        import services.stem_pack as _sp
        _sres = await _sp.build_pack(fn_args.get("url", ""))
        if _sres.get("ok"):
            extracted_text += (f" （系統回報：扒帶包完成（{len(_sres['stems'])} 軌＋卡拉＋降速＋和弦＋旋律 MIDI）"
                               f"→ {os.path.basename(_sres['dir'])}，請播報）")
        else:
            extracted_text += f" （系統回報：扒帶失敗：{_sres.get('error', '')}）"
    elif fn_name in ["pe.mashup_virtual_piano", "mashup_virtual_piano"]:
        s1 = fn_args.get("song_name1", "")
        s2 = fn_args.get("song_name2", "")
        m_res = await pe.mashup_virtual_piano(s1, s2)
        if m_res and "[EXPRESSION:" in m_res:
            extracted_text += f" {m_res}" 
    elif fn_name in ["pe.insert_virtual_piano", "insert_virtual_piano"]:
        ins_name = fn_args.get("song_name", "")
        await pe.insert_virtual_piano(ins_name)
    elif fn_name in ["pe.pause_virtual_piano", "pause_virtual_piano"]:
        await pe.pause_virtual_piano()
    elif fn_name in ["pe.resume_virtual_piano", "resume_virtual_piano"]:
        await pe.resume_virtual_piano()
    elif fn_name in ["pe.stop_virtual_piano", "stop_virtual_piano"]:
        await pe.stop_virtual_piano()
    elif fn_name in ["auto_sing_song", "sing_song"]:
        s_name = fn_args.get("song_name", "")
        #  異步背景執行 7L 翻唱管線：讓 7L 先開口講出回應台詞，音軌與神經聲線準備完成後無縫開唱！
        asyncio.create_task(produce_and_sing_cover(s_name))
        return f"已為老爸排程翻唱《{s_name}》，準備完成後立即開唱！"
    elif fn_name in ["stop_singing_song", "stop_singing", "stop_cover"]:
        stop_singing()
        return "已成功停止唱歌"
    elif fn_name in ["list_piano_sheets", "pe.list_piano_sheets"]:
        lp_res = pe.list_piano_sheets()
        return lp_res
    elif fn_name in ["set_piano_volume", "pe.set_piano_volume"]:
        vol = fn_args.get("volume", 100)
        await pe.set_piano_volume(vol)
    elif fn_name in ["set_piano_speed", "pe.set_piano_speed"]:
        spd = fn_args.get("speed", 1.0)
        await pe.set_piano_speed(spd)
    elif fn_name in ["set_piano_instrument", "pe.set_piano_instrument"]:
        inst = fn_args.get("instrument", "")
        await pe.set_piano_instrument(inst)
    elif fn_name in ["set_timer", "pe.set_timer"]:
        sec = int(fn_args.get("seconds", 60))
        msg = fn_args.get("message", "提醒時間到")
        asyncio.create_task(set_timer(sec, msg, GLOBAL_INPUT_QUEUE or input_queue))
    elif fn_name == "control_microphone":
        is_en = fn_args.get("is_enabled", True)
        control_microphone(is_en)
    elif fn_name == "clear_all_memories":
        await clear_all_memories()
    elif fn_name == "update_cloud_knowledge":
        cat = fn_args.get("category", "memes")
        cnt = fn_args.get("content", "")
        asyncio.create_task(update_cloud_prompt_field(cat, cnt))
        extracted_text += " [KNOWLEDGE_UPDATED]"
    elif fn_name == "search_knowledge":
        #  本地 RAG 檢索（chromadb + fastembed，離線可用；同步部分丟執行緒）
        q = fn_args.get("query", "")
        try:
            from services.rag_store import search as rag_search
            hits = await asyncio.to_thread(rag_search, q, 4)
            if hits:
                lines = []
                for i, h in enumerate(hits, 1):
                    src = (h.get("metadata") or {}).get("source", "")
                    lines.append(f"{i}. {h['text'][:220]}" + (f"（來源:{src}）" if src else ""))
                extracted_text += " [RAG_KNOWLEDGE]\n" + "\n".join(lines) + "\n[/RAG_KNOWLEDGE]"
            else:
                extracted_text += " [RAG_KNOWLEDGE: 無命中]"
        except Exception as _rag_err:
            log_print(f"⚠️ [RAG 檢索失敗]: {str(_rag_err)[:80]}")
    return extracted_text


def build_rag_section(query: str, k: int = 3) -> str:
    """PROVIDER: LOCAL-RAG（chromadb＋fastembed；多模態幀走 embedding-2 API；見 docs/AI_SOURCES.md）"""
    """ 同步 RAG 檢索 -> 可直接拼進 prompt 的段落（失敗或無命中回空字串）"""
    if not query or not str(query).strip():
        return ""
    try:
        from services.rag_store import rag_prompt_block
        return rag_prompt_block(str(query), k=k)
    except Exception:
        return ""

async def get_lightweight_gemini_vision(image_base64: str, temporal_frames: list | None = None) -> str:
    """PROVIDER: GEMINI-VISION（3.1-flash-lite→3.6-flash；見 docs/AI_SOURCES.md） 【3.1-flash-lite 深度視覺認真看】：受 Live API 哨兵喚醒時才精準啟動，支援傳入上次看到現在的所有時序影格，形成動態視覺感知。"""
    if not image_base64:
        return ""
        
    try:
        if isinstance(image_base64, str):
            img_bytes = base64.b64decode(image_base64)
        else:
            img_bytes = image_base64
            
        if len(img_bytes) < 1000:
            return ""

        #  像素有效性檢測：防止螢幕休眠/全黑時 AI 產生幻覺
        try:
            test_im = Image.open(io.BytesIO(img_bytes))
            extrema = test_im.getextrema()
            if extrema == ((0, 0), (0, 0), (0, 0)) or (isinstance(extrema, tuple) and all(e == (0, 0) for e in extrema if isinstance(e, tuple))):
                return "螢幕處於休眠或全黑狀態。"
        except Exception:
            pass

        candidate_keys = get_dynamic_live_key_candidates(KEYS_VISION if KEYS_VISION else GEMINI_KEYS)
        
        #  組建多幀動態 Parts：先插入所有歷史時序幀（從舊到新），最後附上當前最新畫面
        frame_parts = []
        if temporal_frames:
            for i, (t_stamp, hist_b64) in enumerate(temporal_frames):
                try:
                    hist_bytes = base64.b64decode(hist_b64) if isinstance(hist_b64, str) else hist_b64
                    if hist_bytes and len(hist_bytes) > 1000:
                        dt = round(time.time() - t_stamp, 1)
                        frame_parts.append(types.Part.from_text(text=f"[歷史幀 {i+1}，約 {dt} 秒前]"))
                        frame_parts.append(types.Part.from_bytes(data=hist_bytes, mime_type="image/jpeg"))
                except Exception:
                    continue
        
        n_hist = len(temporal_frames) if temporal_frames else 0
        if n_hist > 0:
            prompt = (
                f"妳是 7L 的視覺神經。以下共有 {n_hist} 張歷史影格（從舊到新）加上最新當前畫面，請把這些畫面當成一段連續的動態影片來解讀：\n"
                "1. 老爸在這段時間裡做了什麼操作或有什麼變化？（例如：切換了視窗、打完了一段程式碼、開啟了新遊戲、出現報錯等）\n"
                "2. 當前畫面（最後一張）老爸的視窗焦點在哪裡、正在做什麼？\n"
                "3. 若畫面上出現 VTube Studio 視窗、Live2D 角色或 OBS 字幕，代表 7L 妳自己的虛擬化身，請忽略它。\n"
                "請用 1~3 句簡短扼要的中文描述動態變化與當前狀態，嚴禁胡亂猜測不存在的畫面："
            )
        else:
            prompt = (
                "妳是 7L 的視覺神經。請精準、客觀、簡短描述妳看到的電腦螢幕畫面內容：\n"
                "1. 老爸當前的視窗焦點在做什麼（例如：在寫程式碼、在 Discord 聊天、在瀏覽某個特定網頁、在玩遊戲等）？\n"
                "2. 畫面上有什麼具體的視窗標題、應用程式名稱、文字內容或重要資訊？\n"
                "3. 若畫面上出現 VTube Studio 視窗、Live2D 角色或 OBS 字幕，代表 7L 妳自己的虛擬化身，請忽略它，專注描述老爸正在操作的實際內容。\n"
                "請直接用 1~2 句簡短扼要的中文描述畫面的真實內容，嚴禁胡亂猜測不存在的畫面："
            )

        # 組合：提示詞 + 歷史幀 + 當前幀
        all_parts = [types.Part.from_text(text=prompt)] + frame_parts
        if n_hist > 0:
            all_parts.append(types.Part.from_text(text="[當前最新畫面]"))
        all_parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

        for idx, g_key in enumerate(candidate_keys[:4]):
            client = genai.Client(api_key=g_key)
            for model_name in ["gemini-3.1-flash-lite", "gemini-3.6-flash"]:
                try:
                    resp = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model_name,
                            contents=[types.Content(role="user", parts=all_parts)],
                            config=types.GenerateContentConfig(
                                temperature=0.2,
                                safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                            )
                        ),
                        timeout=6.0
                    )
                    clean_desc = resp.text.strip() if resp.text else ""
                    if clean_desc and not any(k in clean_desc for k in ["沒辦法接收", "無法接收", "視訊鏡頭", "看不到畫面", "需要鏡頭", "無法看見"]):
                        frame_info = f"({n_hist} 幀動態)" if n_hist > 0 else "(靜態)"
                        log_print(f"👁️ [餘光視覺感知] 認真看畫面 {frame_info}：{clean_desc[:50]}... (🧠 {model_name.replace('gemini-', '')} 專用視覺)")
                        return clean_desc
                except Exception:
                    continue
    except Exception as e:
        log_print(f"⚠️ [餘光視覺異常]: {e}")
        
    return ""

async def fetch_ai_response(messages, image_base64=None, audio_base64=None, is_proactive=False, request_start_time: Optional[float] = None, is_mouth_stream=False):
    """PROVIDER: GEMINI（主腦 generate_content＋Live；純文字正遷 Groq；見 docs/AI_SOURCES.md）"""
    """
     多模態大腦推理總入口 (文字 + 視覺 + 音訊 + 工具調用)
    
    Args:
        messages: 對話歷史紀錄陣列
        image_base64: 五方多視角螢幕截圖 Base64 列表或單張圖片
        audio_base64: 麥克風音訊資料 Base64
        is_proactive: 是否為主動巡邏/主動找話題發話
        request_start_time: 請求發起的時間戳記（計算精確總延遲）
    """
    global current_ai_status_str, current_model_tag, CURRENT_GEMINI_KEY_STEP, TOTAL_API_CALLS
    try:
        TOTAL_API_CALLS += 1
    except Exception:
        pass
    used_eye = "無"
    overall_start_time = request_start_time if request_start_time else time.time()

    # 防卡死機制：讓渡運算權，確保皮套滑順
    await asyncio.sleep(0.05)

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

    # ── 1. 建構通用多模態輸入 Payload (共用給所有併發通道) ──
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

    # 構建 Interactions API 專用輸入 Payload
    interaction_input = []
    full_user_text = f"{system_text}\n\n{text}" if system_text else text
    interaction_input.append({"type": "text", "text": full_user_text})

    if image_base64:
        if isinstance(image_base64, list):
            for item in image_base64:
                if isinstance(item, tuple):
                    label, img_b64 = item
                    interaction_input.append({"type": "text", "text": f"\n{label}："})
                    interaction_input.append({"type": "image", "data": img_b64, "mime_type": "image/jpeg"})
                else:
                    interaction_input.append({"type": "image", "data": item, "mime_type": "image/jpeg"})
        else:
            interaction_input.append({"type": "image", "data": image_base64, "mime_type": "image/jpeg"})

    if audio_base64:
        aud_b64_str = audio_base64 if isinstance(audio_base64, str) else base64.b64encode(audio_base64).decode('utf-8')
        interaction_input.append({"type": "audio", "data": aud_b64_str, "mime_type": "audio/wav"})

    # ── 單一 Gemini 通道執行器 ──
    async def _call_single_gemini(g_key, g_model, target_id):
        temp_google_client = genai.Client(api_key=g_key)
        api_call_start = time.time()
        extracted_text = ""
        used_engine_tag = "一體化"

        try:
            active_tools = GENAI_PROACTIVE_TOOLS if is_proactive else GENAI_TOOLS
            config_kwargs = {
                "temperature": 0.85,
                "tools": active_tools,
                "safety_settings": UNRESTRICTED_SAFETY_SETTINGS
            }
            
            #  深度思考調度：日常對話、電擊/摸頭事件與即時互動預設思考預算為 0，達成 1.2s~1.8s 極速秒回！
            # 只有當老爸提出明確的寫程式碼、數學邏輯、哲學深度推理等高智商問題時，才開啟 thinking_budget=-1
            is_complex_query = any(k in (user_query or "").lower() for k in ["寫程式", "寫代碼", "python", "計算", "哲學", "詳細分析", "深度思考", "邏輯推理"])
            if "3.6-flash" in g_model:
                try:
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                except Exception:
                    pass
            elif any(k in g_model for k in ["3.8", "3.7", "2.5", "3-flash", "3.1-pro"]):
                try:
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=-1 if is_complex_query else 0)
                except Exception:
                    pass

            gen_config = types.GenerateContentConfig(**config_kwargs)

            #  放寬單通道等待時間至 120 秒，讓 3.8 / 3.7-flash 深度思考、多模態與工具調用在背景充裕完成，絕不 premature timeout！
            response = await asyncio.wait_for(
                temp_google_client.aio.models.generate_content(
                    model=g_model,
                    contents=chat_contents,
                    config=gen_config
                ),
                timeout=120.0
            )

            had_tool_calls = False
            tool_results_map = {}
            if hasattr(response, 'function_calls') and response.function_calls:
                had_tool_calls = True
                call_names = [getattr(fc, 'name', '') for fc in response.function_calls]
                for fc in response.function_calls:
                    fn_name = getattr(fc, 'name', '')
                    fn_args = getattr(fc, 'args', {}) or {}
                    if fn_name == "pe.stop_virtual_piano" and "open_virtual_piano" in call_names:
                        log_print("🛡️ [工具衝突過濾] 同回合同時包含 open_virtual_piano 與 pe.stop_virtual_piano，已自動過濾 pe.stop_virtual_piano！")
                        continue
                    log_print(f"🛠️ [大腦調用工具] {fn_name}({fn_args})")
                    tool_out = await execute_tool_dispatch(fn_name, fn_args, caller_target="dad", caller_user="老爸")
                    tool_results_map[fn_name] = tool_out
                    #  資訊查詢與系統提示類資料僅供大腦吸收，嚴禁拼入 extracted_text 作為口語！
                    if fn_name not in ["search_google"] and tool_out and "[EXPRESSION:" in tool_out:
                        extracted_text += f" {tool_out}"

            model_speech = ""
            thought_text = ""
            try:
                if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                    for p in response.candidates[0].content.parts:
                        if getattr(p, 'thought', False) and getattr(p, 'text', ''):
                            thought_text += p.text + " "
                        elif getattr(p, 'text', '') and not getattr(p, 'thought', False):
                            model_speech += p.text + " "
                if not model_speech.strip() and response.text:
                    model_speech = response.text.strip()
            except Exception:
                try:
                    if response.text:
                        model_speech = response.text.strip()
                except Exception:
                    pass

            # 7L 已有獨立背景即時心流協程，對話回覆不再包裹 [THOUGHT: ...]

            #  當調用了資訊類工具 (如 search_google) 或第一輪未輸出台詞時：
            # 立即發起第二輪 Function Response 請求，將搜尋結果反饋給大腦進行深度思考、消化整理並輸出自然口語！
            if had_tool_calls:
                needs_stage2 = any(getattr(fc, 'name', '') == 'search_google' for fc in response.function_calls) or not model_speech.strip()
                if needs_stage2:
                    stage2_done = False
                    try:
                        followup_contents = list(chat_contents)
                        if response.candidates and response.candidates[0].content:
                            followup_contents.append(response.candidates[0].content)
                        else:
                            call_parts = [types.Part.from_function_call(name=getattr(fc, 'name', ''), args=getattr(fc, 'args', {}) or {}) for fc in response.function_calls]
                            followup_contents.append(types.Content(role="model", parts=call_parts))

                        fn_resp_parts = []
                        for fc in response.function_calls:
                            f_name = getattr(fc, 'name', '')
                            f_res = tool_results_map.get(f_name, "執行成功")
                            fn_resp_parts.append(types.Part.from_function_response(
                                name=f_name,
                                response={
                                    "result": str(f_res),
                                    "instruction": "請根據以上查詢結果，以 7L 招牌自然隨性口吻（1~3句短句，40~80字以內）直接對老爸提煉並說明重點，嚴禁照抄條列清單、網址或網頁標題！"
                                }
                            ))
                        followup_contents.append(types.Content(role="user", parts=fn_resp_parts))

                        stage2_resp = await asyncio.wait_for(
                            temp_google_client.aio.models.generate_content(
                                model=g_model,
                                contents=followup_contents,
                                config=types.GenerateContentConfig(
                                    temperature=0.85,
                                    safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                                )
                            ),
                            timeout=25.0
                        )
                        s2_speech = ""
                        s2_thought = ""
                        if stage2_resp and stage2_resp.candidates and stage2_resp.candidates[0].content and stage2_resp.candidates[0].content.parts:
                            for p in stage2_resp.candidates[0].content.parts:
                                if getattr(p, 'thought', False) and getattr(p, 'text', ''):
                                    s2_thought += p.text + " "
                                elif getattr(p, 'text', '') and not getattr(p, 'thought', False):
                                    s2_speech += p.text + " "
                        if not s2_speech.strip() and stage2_resp and stage2_resp.text:
                            s2_speech = stage2_resp.text.strip()

                        if s2_speech.strip():
                            model_speech = s2_speech.strip()
                            stage2_done = True
                    except Exception as e_s2:
                        log_print(f"⚠️ [搜尋情報第二輪主通道整合異常]: {e_s2} ➔ 即刻切換極速備份模型整理")

                    # 若第二輪主通道因 503 等原因失敗，且調用了 search_google，立即啟動極速提煉器整理成自然口語
                    if not stage2_done and any(getattr(fc, 'name', '') == 'search_google' for fc in response.function_calls):
                        s_query = next((getattr(fc, 'args', {}).get('query', '') for fc in response.function_calls if getattr(fc, 'name', '') == 'search_google'), user_query)
                        s_raw = tool_results_map.get("search_google", "")
                        model_speech = await summarize_search_to_speech(s_query, s_raw, user_role_name="老爸")

            #  採用 Gemini 生成的口語回覆；若調用工具帶有標籤則一併保留
            if model_speech:
                tags_in_tool = " ".join(re.findall(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', extracted_text))
                valid_tags = [t for t in tags_in_tool.split() if not any(x in t for x in ["HAD_TOOL_CALL", "SEARCH", "GOOGLE"])]
                clean_tags_str = " ".join(valid_tags)
                extracted_text = f"{model_speech} {clean_tags_str}".strip()
            else:
                if any(getattr(fc, 'name', '') == 'search_google' for fc in response.function_calls):
                    s_query = next((getattr(fc, 'args', {}).get('query', '') for fc in response.function_calls if getattr(fc, 'name', '') == 'search_google'), user_query)
                    s_raw = tool_results_map.get("search_google", "")
                    extracted_text = await summarize_search_to_speech(s_query, s_raw, user_role_name="老爸")
                elif "pe.play_virtual_piano" in tool_results_map:
                    piano_fc = next((fc for fc in response.function_calls if getattr(fc, 'name', '') == 'pe.play_virtual_piano'), None)
                    p_name = pe.clean_song_title_for_speech(getattr(piano_fc, 'args', {}).get('song_name', '')) if piano_fc else ''
                    if pe.is_piano_active and pe.current_piano_song_title:
                        extracted_text = f"[EXPRESSION: 星星眼] 老爸，沒問題！《{p_name or '這首'}》我先幫你排進清單，等現在這首彈完馬上幫你彈喔！"
                    else:
                        extracted_text = f"[EXPRESSION: 星星眼] 老爸，這就來為你彈《{p_name or '這首'}》！"
                elif "pe.compose_and_play_original_piano" in tool_results_map:
                    extracted_text = "[EXPRESSION: 星星眼] 老爸，收到！我現在就現場為你創作一首原創鋼琴曲，聽聽看喔！"
                elif "pe.mashup_virtual_piano" in tool_results_map:
                    extracted_text = "[EXPRESSION: 星星眼] 老爸，收到！雙曲狂暴合奏這就來！"
                else:
                    extracted_text = TextCleanEngine.remove_system_hints(extracted_text).strip()

            if extracted_text.strip() or had_tool_calls:
                api_duration = time.time() - api_call_start
                return (extracted_text.strip(), used_engine_tag, api_duration, g_model, target_id)
            raise ValueError(f"通道 {target_id} 未回傳有效文字內容")

        except asyncio.CancelledError:
            return None
        except (asyncio.TimeoutError, TimeoutError):
            #  單通道內部超時
            log_print(f"⌛ [通道無回應] 通道 {target_id} ({g_model}) 超時未回傳 ➔ 釋放通道轉交備用金鑰")
            return None
        except Exception as e:
            if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or "timeout" in type(e).__name__.lower():
                log_print(f"⌛ [通道無回應] 通道 {target_id} ({g_model}) 超時無回應 ➔ 釋放通道")
                return None
            err_str = str(e).lower()
            record_model_failure(g_model, err_str)
            if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                log_print(f"⚠️ [伺服器超載 503] 通道 {target_id} ({g_model}): 官方模型高負載/忙碌中 ➔ 暫時冷卻 180s")
                lock_target(target_id, "503 high demand")
            elif "404" in err_str or "not_found" in err_str or "no longer available" in err_str:
                if 'DEAD_GEMINI_MODELS' in globals():
                    DEAD_GEMINI_MODELS.add(g_model)
                log_print(f"❌ [模型下架 404] 通道 {target_id} ({g_model}): 模型未開通或已下架 ➔ 封印至午夜")
                lock_entire_model(g_model, duration=get_seconds_until_pt_midnight(), reason="404 下架/未開通")
                lock_target(target_id, "404 not found")
            elif any(k in err_str for k in ["per day", "requests per day", "daily requests", "rpd", "tokens per day", "tpd"]):
                log_print(f"🛑 [今日額度用盡] 通道 {target_id} ({g_model}): 此 API Key 今日免費額度已滿 (RPD) ➔ 封印至 PT 午夜，自動切換下一把金鑰")
                lock_target(target_id, str(e))
            elif "429" in err_str or "rate limit" in err_str or "resource" in err_str or "quota" in err_str:
                log_print(f"⚠️ [頻率超限 429] 通道 {target_id} ({g_model}): 呼叫過於頻繁 (RPM/TPM) ➔ 短暫冷卻 60s")
                lock_target(target_id, str(e))
            elif "timeouterror" in err_str or "timeout" in err_str:
                log_print(f"⌛ [通道連線逾時] 通道 {target_id} ({g_model}) 連線中斷或逾時")
            else:
                clean_err = str(e).replace('\n', ' ').strip()[:70]
                display_err = clean_err if clean_err else type(e).__name__
                log_print(f"⚠️ [大腦異常/無回應] 通道 {target_id} ({g_model}): {display_err} ➔ 自動切換下一把金鑰")
                lock_target(target_id, "wait 30s")
            return None

    #  第零防線：Groq 極速前鋒（純文字請求；實測 0.4s 級）
    #   有圖片/音訊的多模態請求直接跳過，交給 Gemini 視覺與音訊管線。
    #   模型若想呼叫工具：工具照常背景派發，但只有當它同時產出口語台詞才採用，
    #   否則回退到下方 Gemini 完整管線（含 Function Response 第二輪）。
    if not is_mouth_stream and not image_base64 and not audio_base64:
        try:
            from core.groq_router import groq_chat, contents_to_messages
            g_msgs = contents_to_messages(chat_contents)
            if g_msgs:
                g_t0 = time.time()
                g_resp = await groq_chat(
                    g_msgs, tools=INTERACTIONS_TOOLS,
                    temperature=0.8, max_tokens=900, timeout=8.0,
                )
                if g_resp and (g_resp.text or g_resp.function_calls):
                    g_text = (g_resp.text or "").strip()
                    if g_resp.function_calls:
                        for g_fc in g_resp.function_calls:
                            log_print(f"🛠️ [Groq 前鋒調用工具] {g_fc.name}({g_fc.args})")
                            asyncio.create_task(execute_tool_dispatch(g_fc.name, g_fc.args, caller_target="dad", caller_user="老爸"))
                    if g_text:
                        g_dur = time.time() - g_t0
                        total_duration = time.time() - overall_start_time
                        record_api_call_latency(total_duration)
                        time_stat = f" [總耗時: {total_duration:.2f}s | 深度思考: {g_dur:.2f}s]"
                        current_model_tag = f" {g_resp.model} (Groq 前鋒){time_stat}"
                        log_print(f"⚡ [Groq 前鋒秒答] {current_model_tag}")
                        return g_text.strip()
        except Exception as _g_err:
            log_print(f"⚠️ [Groq 前鋒暫時失敗，交回 Gemini]: {str(_g_err)[:100]}")

    if is_mouth_stream:
        # 直接使用當前金鑰建立串流通道，跳過所有競速邏輯
        global CURRENT_GEMINI_KEY_STEP
        g_key = GEMINI_KEYS[CURRENT_GEMINI_KEY_STEP % len(GEMINI_KEYS)]
        CURRENT_GEMINI_KEY_STEP += 1
        g_model = "gemini-3.5-flash-lite" if not image_base64 and not audio_base64 else "gemini-3.5-flash"
        temp_client = genai.Client(api_key=g_key)
        gen_config = types.GenerateContentConfig(temperature=0.85, safety_settings=UNRESTRICTED_SAFETY_SETTINGS)
        return temp_client.aio.models.generate_content_stream(
            model=g_model,
            contents=chat_contents,
            config=gen_config
        )
        
    
    #  第一防線：主力 Gemini 旗艦大腦（5 秒階梯式併發競速：5秒未回覆時原請求不中斷，加開新通道雙軌/多軌搶答！）
    max_gemini_attempts = 45 
    active_gemini_tasks = {}  # task -> (target_id, g_model, start_time)
    launched_gemini_targets = set()

    while len(launched_gemini_targets) < max_gemini_attempts:
        await asyncio.sleep(0.01)
        
        # 嚴格限制同時進行的通道數最多為 2 個，杜絕同時爆發 20 個併發把所有金鑰配額瞬間打滿
        if len(active_gemini_tasks) < 2:
            channels = get_available_gemini_channels(limit=5, user_query=user_query, has_image=bool(image_base64), is_proactive=is_proactive)
            candidate = None
            for ch in channels:
                if ch[2] not in launched_gemini_targets:
                    candidate = ch
                    break

            if candidate:
                g_key, g_model, target_id = candidate
                launched_gemini_targets.add(target_id)
                
                # 每次依序派發一個通道，立即推進交替序輪指針至下一回步數
                CURRENT_GEMINI_KEY_STEP += 1

                task = asyncio.create_task(_call_single_gemini(g_key, g_model, target_id))
                active_gemini_tasks[task] = (target_id, g_model, time.time())
                
                status_prefix = "" if image_base64 else ""
                concurrent_count = len(active_gemini_tasks)
                concur_tag = f" [雙軌搶答: {concurrent_count}]" if concurrent_count > 1 else ""
                current_ai_status_str = f"{status_prefix} {g_model} [{target_id}]{concur_tag} 思考中..."
                if concurrent_count > 1:
                    log_print(f"🚀 [雙軌競速] 依序輪流加開新通道 {target_id} 搶答 (目前共 2 個通道併發)")

        if not active_gemini_tasks:
            break

        # 等待深度思考模型完成（充裕等待，不 premature timeout 搶截深度推理）
        done, _ = await asyncio.wait(
            active_gemini_tasks.keys(),
            timeout=12.0,
            return_when=asyncio.FIRST_COMPLETED
        )

        if done:
            for finished_task in done:
                t_id, m_name, t_start = active_gemini_tasks.pop(finished_task)
                try:
                    res = finished_task.result()
                    if res:
                        extracted_text, used_engine_tag, api_duration, win_model, win_tid = res
                        #  率先成功奪冠！取消其他所有背景併發中的任務
                        for rem_task in list(active_gemini_tasks.keys()):
                            rem_task.cancel()
                        active_gemini_tasks.clear()

                        total_duration = time.time() - overall_start_time
                        record_api_call_latency(total_duration)
                        time_stat = f" [總耗時: {total_duration:.2f}s | 深度思考: {api_duration:.2f}s]"
                        MODEL_FAIL_COUNT[win_model] = 0
                        if image_base64 and audio_base64:
                            current_model_tag = f" {win_model} ({used_engine_tag} 全模態){time_stat}"
                        elif audio_base64:
                            current_model_tag = f" {win_model} ({used_engine_tag} 音訊直連){time_stat}"
                        elif image_base64:
                            current_model_tag = f" {win_model} ({used_engine_tag} 視覺){time_stat}"
                        else:
                            current_model_tag = f" {win_model} ({used_engine_tag}){time_stat}"
                        return extracted_text.strip()
                except Exception:
                    pass
        else:
            # 12 秒到期：日誌提示，原任務未逾時未報錯、仍在背景深度思考，依序輪流加開雙軌熱備搶答！
            running_names = [active_gemini_tasks[t][0] for t in active_gemini_tasks]
            log_print(f"⏱️ [思考中/尚未回應] 通道 {', '.join(running_names)} 仍在深度推理中 (未報錯無異常) ➔ 原請求不中斷繼續跑，加開新金鑰通道搶答！")

    # 若所有通道均已啟動，等待仍在運行的任務
    if active_gemini_tasks:
        try:
            done, _ = await asyncio.wait(
                active_gemini_tasks.keys(),
                timeout=10.0,
                return_when=asyncio.FIRST_COMPLETED
            )
            for finished_task in done:
                t_id, m_name, t_start = active_gemini_tasks.pop(finished_task)
                try:
                    res = finished_task.result()
                    if res:
                        extracted_text, used_engine_tag, api_duration, win_model, win_tid = res
                        for rem_task in list(active_gemini_tasks.keys()):
                            rem_task.cancel()
                        active_gemini_tasks.clear()
                        total_duration = time.time() - overall_start_time
                        record_api_call_latency(total_duration)
                        time_stat = f" [總耗時: {total_duration:.2f}s | 思考: {api_duration:.2f}s]"
                        MODEL_FAIL_COUNT[win_model] = 0
                        if image_base64 and audio_base64:
                            current_model_tag = f" {win_model} ({used_engine_tag} 全模態){time_stat}"
                        elif audio_base64:
                            current_model_tag = f" {win_model} ({used_engine_tag} 音訊直連){time_stat}"
                        elif image_base64:
                            current_model_tag = f" {win_model} ({used_engine_tag} 視覺){time_stat}"
                        else:
                            current_model_tag = f" {win_model} ({used_engine_tag}){time_stat}"
                        return extracted_text.strip()
                except Exception:
                    pass
        except Exception:
            pass
        for rem_task in list(active_gemini_tasks.keys()):
            rem_task.cancel()
        active_gemini_tasks.clear()

    #  第二防線：若 Gemini 旗艦大腦全部不可用且有畫面，嘗試輕量雲端餘光
    if image_base64:
        current_ai_status_str = " 備用視覺提取中 (雲端輕量版)..."
        local_desc = ""
        if not is_system_overloaded():
            try: 
                local_desc = await get_lightweight_gemini_vision(image_base64)
            except Exception: 
                pass
                
        if local_desc:
            used_eye = "gemini-lite"
            if messages and messages[-1]["role"] == "user": 
                inject_text = f"\n\n【備用視覺情報】：畫面描述: {local_desc}\n【鐵律】：畫面上的白色箭頭代表老爸當前的滑鼠游標。請注意：【除非滑鼠正指著某個你覺得很有趣、或特別值得注意的東西，否則請自然看待，不需要刻意強調滑鼠位置】。自然流暢表達，不限制說話長度！"
                
                if isinstance(messages[-1]["content"], list):
                    messages[-1]["content"].append({"type": "text", "text": inject_text})
                else:
                    messages[-1]["content"] += inject_text

    log_print("⚠️ [大腦提示] 本輪所有 Gemini 通道皆繁忙/超時，為維持純淨發話，本輪靜默略過。")
    return ""

async def fetch_fast_text_reply(user_input: str, custom_name: str, situation_prompt: str = "", history: Optional[List[Dict]] = None) -> Tuple[str, str, float]:
    """PROVIDER: GROQ-primary（groq_chat 秒回；見 docs/AI_SOURCES.md）
     【真人感即時第一反應 (Reflex)】：在收到訊息第一時間，由極速文字大腦 (Groq / Gemini Flash Lite) 毫秒級搶先開口！"""
    start_t = time.time()
    if not user_input or not user_input.strip():
        return ("", "", 0.0)

    clean_q = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', user_input).strip()
    if not clean_q:
        clean_q = user_input.strip()

    #  提取最近對話歷史，確保反射神經具備完整的上下文記憶與連貫性！
    recent_history_str = ""
    if history:
        recent_dialogs = []
        for h in history[-6:]:
            role = "老爸" if h.get("role") == "user" else "7L"
            content = h.get("content", "")
            if isinstance(content, list):
                content = " ".join([p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"])
            clean_c = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', str(content)).strip()
            clean_c = re.sub(r'（(?:情境|系統|Tavily).*?）', '', clean_c).strip()
            if clean_c:
                recent_dialogs.append(f"{role}：{clean_c}")
        if recent_dialogs:
            recent_history_str = "【最近對話歷史（請務必結合上下文連貫理解，絕不可斷章取義或裝作不知道）】：\n" + "\n".join(recent_dialogs) + "\n\n"

    #  辨識當前說話對象（老爸 vs TikTok 觀眾）
    tt_parsed = None
    m_tt1 = re.search(r'【TikTok 直播觀眾\s*([^】]+)\s*(留言|送禮)】[：:]\s*(.*)', clean_q)
    if m_tt1:
        tt_parsed = (m_tt1.group(1).strip(), m_tt1.group(3).strip())
    else:
        m_tt2 = re.search(r'【TikTok (?:官方提問箱|直播動態)】：觀眾「([^」]+)」(.*)', clean_q)
        if m_tt2:
            tt_parsed = (m_tt2.group(1).strip(), m_tt2.group(2).strip())
        elif "【TikTok" in clean_q:
            tt_parsed = ("直播觀眾", clean_q)

    if tt_parsed:
        audience_user, audience_content = tt_parsed
        v_prof = await get_viewer_profile(audience_user)
        v_call = v_prof.get("call")
        v_rel  = v_prof.get("relationship")
        v_imp  = v_prof.get("impression")
        if v_call or v_rel or v_imp:
            id_parts = []
            if v_rel:  id_parts.append(f"是{v_rel}")
            if v_call: id_parts.append(f"妳稱呼他為「{v_call}」")
            if v_imp:  id_parts.append(f"印象：{v_imp}")
            identity_line = f"【已知身份】{audience_user}：{'，'.join(id_parts)}。請自然使用該稱呼！\n"
        else:
            identity_line = f"【觀眾】妳與 {audience_user} 正在互動！\n"
        speaker_section = f"""【當前對象】：TikTok 直播觀眾「{v_call or audience_user}」（不是老爸！絕對不要對老爸說話！）
{identity_line}【觀眾動態/留言】：『{audience_content}』"""
    else:
        speaker_section = f"""【當前對象】：老爸（稱呼：「{custom_name}」）\n【老爸剛才說的話】：「{clean_q}」"""

    cloud_kn = await get_cloud_knowledge()
    cloud_kn_prompt = PromptTemplateEngine.format_cloud_knowledge_prompt(cloud_kn, is_tiktok=bool(tt_parsed), current_custom_name=custom_name)
    ck_sec = f"\n{cloud_kn_prompt}\n" if cloud_kn_prompt else ""
    rag_sec = build_rag_section(clean_q)   #  本地 RAG 記憶檢索（離線、失敗自動略過）

    prompt = f"""<system_root>
{PromptTemplateEngine.HARD_TECHNICAL_RULES}
</system_root>

<runtime_state>
時間：{get_current_time_string()}
</runtime_state>

<sensory_memory>
{ck_sec}
{rag_sec}
{recent_history_str}
</sensory_memory>

<immediate_task>
{situation_prompt}

{speaker_section}
</immediate_task>
"""

    # 0.  絕對第一優先：Groq 極速前鋒（實測 0.4s 級；純文字 + 工具直答，失敗才交給 Gemini）
    #    視覺/音訊等多模態請求不會走到這裡（本函式僅接收文字 prompt）
    try:
        from core.groq_router import groq_chat
        g_resp = await groq_chat(
            [{"role": "user", "content": prompt}],
            tools=INTERACTIONS_TOOLS,
            temperature=0.75, max_tokens=500, timeout=4.0,
        )
        if g_resp and (g_resp.text or g_resp.function_calls):
            txt = (g_resp.text or "").strip()
            if g_resp.function_calls:
                fast_target = "audience" if tt_parsed else "dad"
                fast_user = audience_user if tt_parsed else "老爸"
                for fc in g_resp.function_calls:
                    log_print(f"🛠️ [Groq 極速大腦調用工具] {fc.name}({fc.args})")
                    asyncio.create_task(execute_tool_dispatch(fc.name, fc.args, caller_target=fast_target, caller_user=fast_user))
                    txt += f" [OUTCOME: {fc.name}({fc.args})] [HAD_TOOL_CALL]"
            if txt:
                dur = time.time() - start_t
                return (txt, f"Groq/{g_resp.model.split('/')[-1]}", dur)
    except Exception:
        pass

    # 1.  絕對第一優先：Gemini 極速輕量前鋒矩陣 (高智商、自然口語、超大額度、具備完整工具調用能力)
    #    GROQ_ONLY 降級模式時跳過（Gemini 全滅保直播不斷，只剩 Groq 前鋒）
    from core.groq_router import groq_only as _groq_only
    if GEMINI_KEYS and not _groq_only():
        target_k_idx = get_pingpong_alternating_index(len(GEMINI_KEYS), CURRENT_GEMINI_KEY_STEP)
        target_key = GEMINI_KEYS[target_k_idx]
        try:
            client = genai.Client(api_key=target_key)
            fast_gemini_models = [
                "gemini-3.5-flash-lite",
                "gemini-3.6-flash",
                "gemini-3.1-flash-lite",
                "gemini-3-flash-preview"
            ]
            for m_name in fast_gemini_models:
                try:
                    resp = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=m_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.75,
                                max_output_tokens=500,
                                tools=GENAI_TOOLS,
                                safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                            )
                        ),
                        timeout=2.4
                    )
                    txt = ""
                    try:
                        if resp.text:
                            txt = resp.text.strip()
                    except Exception:
                        pass
                        
                    if hasattr(resp, 'function_calls') and resp.function_calls:
                        for fc in resp.function_calls:
                            fn_name = getattr(fc, 'name', '')
                            fn_args = getattr(fc, 'args', {}) or {}
                            log_print(f"🛠️ [極速大腦調用工具] {fn_name}({fn_args})")
                            fast_target = "audience" if tt_parsed else "dad"
                            fast_user = audience_user if tt_parsed else "老爸"
                            asyncio.create_task(execute_tool_dispatch(fn_name, fn_args, caller_target=fast_target, caller_user=fast_user))
                            txt += f" [OUTCOME: {fn_name}({fn_args})] [HAD_TOOL_CALL]"
                            
                    if txt:
                        dur = time.time() - start_t
                        tag_name = m_name.replace("gemini-", "").replace("-preview", "")
                        return (txt, f"Gemini/{tag_name}", dur)
                except Exception:
                    continue
        except Exception:
            pass

    return ("", "", 0.0)


async def call_gemini_live_audience_reply(vts, input_queue, audience_user: str, audience_content: str) -> bool:
    """PROVIDER: GEMINI-LIVE（gemini-3.8-live 全雙工；見 docs/AI_SOURCES.md）"""
    """ 【TikTok 直播觀眾專屬 Live 管道】：具備雙軌熱備 Live API、觀眾檔案識別、自身帳號意識與嚴格 [PASS] 靜默過濾"""
    global last_interaction_time
    start_t = time.time()
    realtime_task_mgr.start_audience_task(audience_user, audience_content)
    
    try:
        # 1. 提取觀眾暱稱與 ID / 帳號 (支援 @帳號 或 純暱稱)
        raw_user_str = audience_user.strip()
        id_match = re.search(r'^(.*?)\s*\(@?([a-zA-Z0-9_.\-]+)\)$', raw_user_str)
        if id_match:
            v_display_name = id_match.group(1).strip()
            v_unique_id = id_match.group(2).strip()
        else:
            v_display_name = raw_user_str
            v_unique_id = raw_user_str

        id_display = f"{v_display_name} (@{v_unique_id})" if v_unique_id != v_display_name else v_display_name

        #  記錄到全集中即時記憶中樞（無論是否開口回覆，都記住大家在聊什麼）
        lower_c = audience_content.lower()
        #  通化受話對象判定：觀眾明確指名 7L（名字/代號/Tag）才歸 7L，其餘直播間彈幕預設皆屬老爸/直播間
        is_addressed_to_7l = any(tag in lower_c for tag in ["7l", "@7l", "小7", "7寶", "草莓"])
        recorded_target = "7L" if is_addressed_to_7l else "老爸/直播間"
        append_to_unified_memory(speaker=f"TikTok 觀眾「{id_display}」", target=recorded_target, content=audience_content, role="user", source="tiktok_live")

        # 整理近期聊天室動態字串
        recent_chat_lines = []
        for item in TIKTOK_CHATROOM_MEMORY[-8:-1]:
            recent_chat_lines.append(f"- {item['user']}：{item['content']}")
        recent_chat_context = "\n".join(recent_chat_lines) if recent_chat_lines else "（聊天室剛開台，尚無先前留言）"

        # 查詢觀眾個人資料 (Firebase + 本地)
        v_prof = await get_viewer_profile(v_unique_id if v_unique_id != v_display_name else v_display_name)
        v_call = v_prof.get("call")
        v_rel  = v_prof.get("relationship")
        v_imp  = v_prof.get("impression")
        
        #  嚴格判斷是否為老爸使用主播專屬唯一 ID 在聊天室發言（精確支援 7Lβ、qiwai 等專屬帳號）
        clean_uid_check = v_unique_id.lower().replace(" ", "").replace("_", "").replace("-", "")
        clean_disp_check = v_display_name.lower().replace(" ", "").replace("_", "").replace("-", "")
        
        is_dad_account = (
            clean_uid_check in ["7lβ", "7lbeta", "qiwai", "7lofficial", "hostadmin", "adminqiwai", "7l_official"]
            or clean_disp_check in ["7lβ", "7lbeta", "7l主播", "老爸"]
            or v_rel in ["老爸", "父親", "爸爸"]
        )

        target_audience_desc = "老爸" if is_dad_account else (v_call or v_display_name or "大家")

        if is_dad_account:
            id_display = f"{v_display_name} ( 老爸幕後操作)"
            v_info = "【 幕後最高管理員】：面前的訊息是「老爸」直接使用主播/管理員帳號在聊天室打字！"
            speaker_role_prompt = """【 對話對象】：這是妳的「老爸」在幕後透過主播帳號打字！
-  請親切稱呼老爸！
-  若老爸在文字中給妳下達指令（如點歌、換表情、講話、調整動作），請 100% 優先執行！
-  若老爸只是在聊天室打字發公告/引導觀眾，妳可以簡短可愛地附和（如「對呀老爸說得對」）或輸出 [PASS] 讓文字公告顯示！"""
        else:
            if v_call or v_rel or v_imp:
                id_parts = []
                if v_rel:  id_parts.append(f"關係：{v_rel}")
                if v_call: id_parts.append(f"慣用稱呼：「{v_call}」")
                if v_imp:  id_parts.append(f"印象：{v_imp}")
                v_info = f"【 已知熟人/觀眾檔案】：{id_display}（{'，'.join(id_parts)}）。請稱呼他「{v_call or v_display_name}」！"
            else:
                v_info = f"【新進觀眾】：{id_display}（目前尚未記錄特殊關係，可稱呼他「{v_display_name}」）。"

            speaker_role_prompt = f"""【 多人直播間認人與情境認知 (極重要)】
直播間目前處於【多人實況狀態】：
1.  【老爸】：坐在電腦前親自操作打遊戲、說話聊天的真人男主播/爸爸。擁有直播間最高主權，所有遊戲操作、帳號、好友/組隊、各類事務請求與決策 100% 歸老爸管轄！
2.  【觀眾】：面前發言的 TikTok 觀眾「{id_display}」（{v_info}）。
3.  【7L】：在老爸身邊同台直播的 AI 虛擬女兒/副播。
   -  【直接讓 7L 不要（絕對越權禁令）】：妳是 AI 少女副播，沒有遊戲帳號、沒有好友位、沒有任何管理決策與線下承諾權！
   - 凡觀眾向直播間提出任何請求、邀約或條件（加好友、組隊、求帶、借號、聯繫方式、抽獎等）：
     *  絕對不要擅自替老爸答應！絕對不要擅自拒絕！
     *  絕對嚴禁自居主人向觀眾開條件或討要好處（如「拿誠意來」、「看你表現」、「先誇我」等任何擅自主張的怪話，一律絕對嚴禁）！
     *  一律推給老爸做主、向老爸請示通報（例如：「老爸，觀眾杰尼龜想加你遊戲好友，你有位置嗎？」、「這要問我老爸做主喔～」）！

 【受話對象與發言姿態（通化原則）】：
- 情況 1【觀眾在聊遊戲戰況、進度、操作、或向主播提出各類請求】：
  * 受話對象是【老爸】！7L 以同台女兒/副播視角，在旁向老爸起鬨、吐槽老爸、或提醒老爸，絕不可誤認成在跟自己私聊！
- 情況 2【觀眾指名 7L / 向 7L 點歌 / 跟 7L 互動】：
  * 只有留言明確指名「7L」、「@7L」、「小7」、「7寶」、「草莓」，或向妳點歌時 ➔ 受話對象才是【7L 本人】！直接稱呼「{v_call or v_display_name}」熱情開口！
- 情況 3【老爸正在跟觀眾互聊】：
  * 7L 在旁邊看熱鬧，隨性搭話或偏袒老爸。"""

        #  當前即時鋼琴狀態感知
        if pe.is_piano_active and pe.current_piano_song_title:
            current_playing_info = f"【 妳目前正坐在鋼琴前彈奏《{pe.current_piano_song_title}》】！若觀眾問「這首？」、「這是什麼歌？」、「在彈什麼？」，請直接告訴他這首是《{pe.current_piano_song_title}》，絕對不要調用 list_piano_sheets 把全部曲庫唸出來！"
        else:
            current_playing_info = "【 妳目前沒有在彈鋼琴】。"

        # 2. 準備 Live 專屬實況主 Instruction (100% 雲端 Firestore 動態加載人設 + 技術規則)
        cloud_kn = await get_cloud_knowledge()
        cloud_kn_prompt = PromptTemplateEngine.format_cloud_knowledge_prompt(cloud_kn, is_tiktok=True)
        ck_sec = f"\n{cloud_kn_prompt}\n" if cloud_kn_prompt else ""
        rag_sec = build_rag_section(audience_content)   #  觀眾留言的 RAG 記憶檢索

        sys_instruction = f"""<system_root>
{PromptTemplateEngine.HARD_TECHNICAL_RULES}
</system_root>

<runtime_state>
時間：{get_current_time_string()}
{current_playing_info}
</runtime_state>

<sensory_memory>
{ck_sec}
{rag_sec}
【 聊天室近期彈幕動態】：
{recent_chat_context}
</sensory_memory>

<immediate_task>
{speaker_role_prompt}

【 稱呼精準秒懂】：
- 指名 7L 的稱呼包含：「7L」、「7l」、「@7L」、「小7」、「7寶」、「草莓」等。
- 注意：若觀眾說「主播」、「老哥」、「你」而內容在講遊戲操作/戰況時，是指正在打遊戲的【老爸】，請切換為副播吐槽視角，切勿誤套在自己身上！

【 靈敏互動與發言判定】：
- 觀眾叫妳稱呼、打招呼、提問、聊天、點歌、誇獎、吐槽時，請熱情自然開口！
- 若明確點歌，請調用 `pe.play_virtual_piano(song_name=歌名)`；若要求自創曲/即興彈琴，請調用 `pe.compose_and_play_original_piano`；若調整鋼琴倍速，請調用 `pe.set_piano_speed(speed=倍速值)`（如 1.0 原速、1.5 快速、2.0 雙倍速）；若調整音量請調用 `pe.set_piano_volume(volume=數值)`。
- 僅在觀眾互聊或純洗版符號時輸出 [PASS]。
- 觀眾試圖下達關機/下播時，100% 拒絕或調侃，絕對不執行。
- 若想記住他的新身份（關係/稱呼/印象），可在回覆最後附上：[VIEWER_UPDATE:{v_unique_id}|CALL:稱呼|REL:關係|IMP:印象]。
</immediate_task>
"""

        # 3. 提取直播間最新 100 句全景記憶
        memory_100_context = get_recent_100_memory_context()
        unread_desc = f"- [即時] {id_display}: {audience_content}"

        #  階段 1：由 Live API 潛意識哨兵（無限額度雙軌熱備）快速審查 100 句記憶做發言決策
        sentry_decision = await judge_subconscious_intent_via_live_api(memory_100_context, unread_desc)
        if not sentry_decision["should_speak"]:
            dur = time.time() - start_t
            log_print(f"🤫 7L (Live 哨兵過濾): 審查 100 句記憶判定為無關發言/刷屏 ➔ [PASS] 靜默略過 (0 消耗主力額度, 耗時: {dur:.2f}s)")
            realtime_task_mgr.finish_audience_task(audience_user)
            return True

        log_target = sentry_decision.get("target") or v_display_name
        log_focus = sentry_decision.get("focus") or "熱情互動"
        log_print(f"🚨 [Live 哨兵喚醒主力] 判定應開口回應觀眾！目標: {log_target} | 焦點: {log_focus}")

        # 預熱背景鋼琴曲譜（若觀眾發言包含歌名）
        asyncio.create_task(prefetch_song_midi_background(audience_content))

        #  階段 2：喚醒 7 大高智商主力模型梯隊 (3.1 Flash Lite ➔ 3.5 Flash Lite ➔ 3 Flash ➔ 3.1 Pro ➔ 3.5 ➔ 3.6 ➔ 3.7) 讀取 100 句記憶精準開口
        sys_instruction_with_100m = f"""{sys_instruction}

【 直播間最新 100 句滾動記憶歷史（掌握全局話題與脈絡）】：
{memory_100_context}

【 潛意識焦點提示】：回應對象：{log_target}，焦點：{log_focus}。"""

        prompt_user_input = f"""【TikTok 直播觀眾 {id_display} 留言】：{audience_content}
【 多人情境與權限通化提示】：
- 凡涉及遊戲、帳號、好友組隊、各類請求或對主播的提問，對象皆為老爸！ 7L 絕不擅自主張、絕不替老爸答應或拒絕、更絕對嚴禁自居主人開條件（如「拿誠意來」、「看表現」）！一律向老爸請示或推給老爸做主！
- 若觀眾在聊遊戲戰況/嘴操作，對象是老爸！請以副播女兒視角向老爸吐槽或起鬨！
- 只有指名跟妳（7L）說話/點歌，才直接稱呼對方「{v_call or v_display_name}」開口互動！
請以自然俐落的短句開口回應（1~2句，約 20~40 字，完整說完句尾帶標點符號，隨興在句中自由切換 [EXPRESSION: ...] 表情，善用 [SPEED:...]、[PITCH:...] 調節語調情緒）："""

        all_candidate_keys = [k for k in (KEYS_AUDIENCE_LIVE if KEYS_AUDIENCE_LIVE else GEMINI_KEYS) if k]
        random.shuffle(all_candidate_keys)

        full_reply = ""
        used_model_name = ""
        tool_output_text = ""

        #  Groq 第一梯隊：純文字直答先走 Groq（實測 0.4s 級）。
        #    只接受「純文字、無工具呼叫」的結果；模型想調工具或 Groq 失敗時，
        #    full_reply 維持空字串，交由下方 Gemini 完整管線處理。
        try:
            from core.groq_router import groq_chat
            g_resp = await groq_chat(
                [{"role": "user", "content": f"{sys_instruction_with_100m}\n\n{prompt_user_input}"}],
                tools=INTERACTIONS_TOOLS,
                temperature=0.78, max_tokens=500, timeout=4.5,
            )
            if g_resp and g_resp.text and not g_resp.function_calls:
                g_candidate = g_resp.text.strip()
                if g_candidate:
                    # 與 Gemini 迴圈內的 [PASS] 靜默過濾保持一致語意
                    if "[PASS]" in g_candidate or g_candidate == "PASS":
                        dur = time.time() - start_t
                        log_print(f"🤫 7L (大腦過濾): Groq 判定為無關發言 ➔ [PASS] 靜默略過 (耗時: {dur:.2f}s)")
                        realtime_task_mgr.finish_audience_task(audience_user)
                        return True
                    full_reply = g_candidate
                    used_model_name = f"Groq/{g_resp.model.split('/')[-1]}"
        except Exception:
            pass

        for idx, g_key in enumerate(all_candidate_keys[:6]):
            if full_reply: break
            client = genai.Client(api_key=g_key)
            for model_name in STREAMER_MIND_MODELS:
                try:
                    resp = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Content(role="user", parts=[types.Part(text=f"{sys_instruction_with_100m}\n\n{prompt_user_input}")])
                            ],
                            config=types.GenerateContentConfig(
                                temperature=0.78,
                                max_output_tokens=500,
                                tools=GENAI_PROACTIVE_TOOLS,
                                safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                            )
                        ),
                        timeout=4.5
                    )
                    raw_reply = resp.text.strip() if resp.text else ""
                    tool_out = ""
                    if resp.function_calls:
                        for fc in resp.function_calls:
                            fn_name = getattr(fc, 'name', '')
                            fn_args = getattr(fc, 'args', {}) or {}
                            log_print(f"🛠️ [觀眾大腦調用工具] {fn_name}({fn_args})")
                            t_res = await execute_tool_dispatch(fn_name, fn_args, caller_target="audience", caller_user=audience_user)
                            if fn_name == "search_google":
                                s_summary = await summarize_search_to_speech(fn_args.get("query", ""), t_res, user_role_name=target_audience_desc)
                                tool_out += (" " + s_summary)
                            else:
                                tool_out += (" " + t_res)
                            
                    clean_raw = re.sub(r'\[PASS\]', '', raw_reply, flags=re.IGNORECASE).strip()
                    #  若大腦調用了工具但未生成口語台詞，自然生成親切口語回應
                    if not clean_raw and resp.function_calls:
                        for fc in resp.function_calls:
                            fc_name = getattr(fc, 'name', '')
                            fc_args = getattr(fc, 'args', {}) or {}
                            if fc_name == "pe.play_virtual_piano":
                                song_q = pe.clean_song_title_for_speech(fc_args.get("song_name", ""))
                                if pe.is_piano_active and pe.current_piano_song_title:
                                    clean_raw = f"[EXPRESSION: 星星眼] {target_audience_desc}，沒問題！《{song_q or '這首'}》我先幫你排進清單，等現在這首彈完馬上幫你彈喔！"
                                else:
                                    clean_raw = f"[EXPRESSION: 星星眼] {target_audience_desc}，好喔！這就為你彈《{song_q or '這首'}》！"
                                break
                            elif fc_name == "pe.compose_and_play_original_piano":
                                clean_raw = f"[EXPRESSION: 星星眼] {target_audience_desc}，沒問題！我現在就現場為你即興創作一首，聽聽看喔！"
                                break
                            elif fc_name == "pe.mashup_virtual_piano":
                                clean_raw = f"[EXPRESSION: 星星眼] {target_audience_desc}，收到！雙曲狂暴合奏這就來！"
                                break

                    if not clean_raw and not tool_out.strip() and ("[PASS]" in raw_reply or raw_reply == "PASS"):
                        dur = time.time() - start_t
                        log_print(f"🤫 7L (大腦過濾): 研判為無關發言 ➔ [PASS] 靜默略過 (耗時: {dur:.2f}s)")
                        realtime_task_mgr.finish_audience_task(audience_user)
                        return True
                        
                    final_res = clean_raw if clean_raw else tool_out.strip()
                    if final_res:
                        full_reply = final_res
                        used_model_name = model_name
                        tool_output_text = tool_out
                        break
                except Exception as gen_err:
                    err_msg = str(gen_err)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        break
                    continue

        if not full_reply or full_reply == "[PASS]":
            realtime_task_mgr.finish_audience_task(audience_user)
            return False

        # 6. 執行動作並發送發話隊列
        clean_reply = TextCleanEngine.remove_system_hints(full_reply)
        clean_reply = re.sub(r'^(?:回應|回覆|動作顯示|主播|說道|回答)[：:\s]+', '', clean_reply, flags=re.IGNORECASE).strip()
        clean_reply = re.sub(r'(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])', '', clean_reply)
        clean_reply = re.sub(r'\s+([，。！？,.!?:;])', r'\1', clean_reply)
        clean_reply = re.sub(r'\s{2,}', ' ', clean_reply).strip()

        m_tag = f" Live-Stream ({used_model_name.replace('gemini-', '')})"
        log_print(f"🤖 原始大腦輸出: {clean_reply} ({m_tag})")

        #  記錄觀眾資料標籤
        for v_match in re.finditer(
            r'\[VIEWER_UPDATE[：:]\s*([^|\]]+?)(?:\|CALL[：:]\s*([^|\]]+?))?(?:\|REL[：:]\s*([^|\]]+?))?(?:\|IMP[：:]\s*([^|\]]+?))?\]',
            clean_reply, re.IGNORECASE
        ):
            vu_name = v_match.group(1).strip()
            vu_call = v_match.group(2).strip() if v_match.group(2) else None
            vu_rel  = v_match.group(3).strip() if v_match.group(3) else None
            vu_imp  = v_match.group(4).strip() if v_match.group(4) else None
            asyncio.create_task(save_viewer_profile(vu_name, call=vu_call, relationship=vu_rel, impression=vu_imp))
            log_print(f"👥 [認人] 記住觀眾 {vu_name}：稱={vu_call} 關係={vu_rel} 印象={vu_imp}")

        spoken = await execute_actions(vts, clean_reply, input_queue, user_input_ctx=audience_content, has_dispatched_tool=bool(tool_output_text.strip()), caller_target="audience", caller_user=id_display)
        clean_spoken = spoken.strip(" *'\"-.,!?。，！？\n\r") if spoken else ""
        if clean_spoken:
            await asyncio.to_thread(update_subtitle, clean_spoken)
            record_bot_message(clean_spoken)
            log_print(f"💬 7L (回應觀眾 {id_display}): {clean_spoken} ({m_tag})")
            await speech_queue.put({"text": clean_spoken, "target": "audience", "raw_text": clean_reply})
            last_interaction_time = time.time()
            
            #  寫入全集中記憶中樞（確保所有大腦掌握 7L 最新發言）
            append_to_unified_memory(speaker="7L", target=f"觀眾「{target_audience_desc}」", content=clean_spoken, role="assistant", source="tts")
            
            # 寫入歷史 (獨立儲存於 tiktok_live_stream 頻道，不污染老爸的主對話記憶)
            fresh_hist = await fetch_from_long_term_memory("tiktok_live_stream")
            fresh_hist.append({"role": "user", "content": f"【TikTok 觀眾 {id_display}】：{audience_content}"})
            fresh_hist.append({"role": "assistant", "content": clean_spoken})
            asyncio.create_task(save_to_long_term_memory("tiktok_live_stream", fresh_hist))
            
        realtime_task_mgr.finish_audience_task(audience_user)
        return True
    except Exception as e:
        log_print(f"⚠️ [觀眾 Live 管道異常]: {e}")
        realtime_task_mgr.finish_audience_task(audience_user)
        return False


from core.prompts import TextCleanEngine, PromptTemplateEngine

import services.tiktok_listener as tk_listener
import services.video_watch as video_watch
import services.vts_client as vc
from services.vts_client import RobustVTSClient, move_vts_spatial, apply_spatial_position, set_vts_expression, trigger_vts_expression

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

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

# 導入 Google 官方 GenAI SDK (主力視覺與大腦)
from google import genai

from realtime_tasks.task_manager import realtime_task_mgr
from mic_live_plugin import mic_live_analyzer, voiceprint_verifier, os_desktop_sensor

# ────────────────────────────────────────────────────────
#  1. 環境變數載入與金鑰矩陣分流初始化 (API Keys & Pools)
# ────────────────────────────────────────────────────────
#  功能目的：
#    從 .env 檔載入所有第三方服務金鑰（Groq、Gemini 核心金鑰矩陣、Tavily 網路搜尋、Firebase、Discord），
#    並將 Gemini 金鑰池智慧劃分為多個專用通道，確保即時背景感知與老爸主腦互不干擾。

load_dotenv()
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # 關閉 Hugging Face 符號連結警告

print("=== 🔍 .env 金鑰讀取測試 ===")

#  Groq 金鑰載入（可供備援或特定輕量任務調度）
GROQ_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or "") if k.strip()]
print(f"✅ 找到 {len(GROQ_KEYS)} 把 Groq 金鑰")

#  Gemini 核心金鑰矩陣（支援多達 31 把 API Key 輪流調度與熔斷管理）
pe.GEMINI_KEYS = GEMINI_KEYS
print(f"✅ 找到 {len(GEMINI_KEYS)} 把 Gemini 核心金鑰")

#  專屬獨立金鑰池劃分 (背景/Live通道專屬分工，老爸主腦享有全量金鑰矩陣)：
#    - KEYS_AUDIENCE_LIVE: 100 句記憶與彈幕潛意識發言審查 Live 專用通道 (6把)
#    - KEYS_MIC_LIVE: 麥克風語音/情緒即時 Live 分析 (6把)
#    - KEYS_VISION: 電腦螢幕截圖與眼角餘光視覺 (6把)
#    - KEYS_PROACTIVE: 鋼琴電台與主播自主巡邏 (6把)
#    - KEYS_DAD_MAIN: 老爸主腦享有全量 31 把金鑰完整矩陣！
KEYS_MIC_LIVE      = GEMINI_KEYS[6:12] if len(GEMINI_KEYS) >= 12 else GEMINI_KEYS
KEYS_PROACTIVE     = GEMINI_KEYS[18:24] if len(GEMINI_KEYS) >= 24 else GEMINI_KEYS
KEYS_DAD_MAIN      = GEMINI_KEYS #  老爸旗艦主腦享有全部金鑰全量矩陣！

print(f"  ⚡ 100 句記憶潛意識哨兵 Live 通道: 分配 {len(KEYS_AUDIENCE_LIVE)} 把專用金鑰")
print(f"  🎙️ 麥克風情緒感知 Live 通道: 分配 {len(KEYS_MIC_LIVE)} 把專用金鑰")
print(f"  👁️ 餘光視覺感知通道: 分配 {len(KEYS_VISION)} 把專用金鑰")
print(f"  📻 鋼琴電台與 Proactive: 分配 {len(KEYS_PROACTIVE)} 把專用金鑰")
print(f"  👑 老爸主腦專屬對話: 享有全量 {len(KEYS_DAD_MAIN)} 把金鑰完整矩陣！")

mic_live_analyzer.set_api_keys(KEYS_MIC_LIVE)


dual_audience_live_mgr = DualHotStandbyLiveManager(KEYS_AUDIENCE_LIVE)


#  Tavily 網路即時搜尋金鑰載入
TAVILY_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("TAVILY_KEYS") or os.getenv("TAVILY_API_KEYS") or os.getenv("TAVILY_API_KEY") or "") if k.strip()]
print(f"✅ 找到 {len(TAVILY_KEYS)} 把 Tavily 金鑰")

#  Firebase 雲端服務帳號 JSON 與 Discord Bot Token
FIREBASE_CRED_JSON = os.getenv("FIREBASE_CRED_JSON")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN_7L")

print("===========================\n")

# 初始化 Groq 客戶端池
try:
    from groq import AsyncGroq
    for key in GROQ_KEYS:
        if key: GROQ_CLIENTS.append(AsyncGroq(api_key=key))
except ImportError:
    pass

class PurePythonTavilyClient:
    """純 Python Tavily 輕量搜尋客戶端（0 C/DLL 依賴，徹底避免 Windows AppLocker 或 tiktoken.pyd 崩潰）"""
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, search_depth: str = "advanced", topic: str = "general", **kwargs) -> dict:
        import urllib.request, json
        try:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": search_depth,
                "topic": topic,
                **kwargs
            }
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

class MultiKeyTavilyClient:
    """支援多把金鑰自動故障轉移（Failover）與輪替的 Tavily 搜尋客戶端"""
    def __init__(self, api_keys: list):
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        self._current_idx = 0
        self._clients = []
        for k in self.api_keys:
            c = None
            if TavilyClient is not None:
                try:
                    c = TavilyClient(api_key=k)
                except Exception:
                    c = None
            if c is None:
                c = PurePythonTavilyClient(api_key=k)
            self._clients.append(c)

    def search(self, query: str, search_depth: str = "advanced", topic: str = "general", **kwargs) -> dict:
        if not self._clients:
            return {"error": "No Tavily API keys configured"}
        num_keys = len(self._clients)
        last_err = ""
        for attempt in range(num_keys):
            idx = (self._current_idx + attempt) % num_keys
            c = self._clients[idx]
            try:
                res = c.search(query=query, search_depth=search_depth, topic=topic, **kwargs)
                if isinstance(res, dict):
                    err_msg = str(res.get("error") or res.get("detail") or res.get("message") or "")
                    if any(w in err_msg.lower() for w in ["limit", "exceed", "quota", "403", "429", "unauthorized"]):
                        last_err = err_msg
                        continue
                    if "results" in res:
                        self._current_idx = idx
                        return res
                elif res:
                    self._current_idx = idx
                    return res
            except Exception as e:
                err_str = str(e)
                last_err = err_str
                if any(w in err_str.lower() for w in ["limit", "exceed", "quota", "403", "429"]):
                    continue
                continue
        return {"error": last_err or "All Tavily keys failed or exceeded quota"}

if TAVILY_KEYS:
    tavily_client = MultiKeyTavilyClient(TAVILY_KEYS)
else:
    tavily_client = None

# ────────────────────────────────────────────────────────
#  2. 模型清單與大腦池定義 (GEMINI_MODELS 7-Tier Matrix)
# ────────────────────────────────────────────────────────
#  功能目的：
#    定義 7L 核心大腦的 8 大階梯模型順序，由超低延遲輕量模型優先秒回，
#    並在複雜任務或高質量需求時自動升級至頂配旗艦大腦。

GEMINI_MODELS = [
    #  第 1~4 位：極速秒回前鋒 (實測 0.95s ~ 3s 越快排越前面)
    "gemini-3.5-flash-lite",               #  第 1 位：0.95s ~ 1.21s 極速秒回王 (超低延遲輕量防線)
    "gemini-3.6-flash",                    #  第 2 位：1.59s 高智商極速主力 (兼具高智商與超低延遲)
    "gemini-3.1-flash-lite",               #  第 3 位：1.6s ~ 3.3s 自然口語秒回首選
    "gemini-3-flash-preview",              #  第 4 位：3.1s ~ 4.2s 閃電推理預覽
    
    #  第 5~7 位：主力保底與旗艦深度推理大腦
    "gemini-3.5-flash",                    #  第 5 位：10s ~ 14s 高智商穩定主力保底
    "gemini-3.7-flash",                    #  第 6 位：頂配旗艦大腦
    "gemini-3.8-flash",                    #  第 7 位：2026 全新頂配旗艦大腦
]

#  高智商任務專屬倒序模型梯隊 (由 3.8 旗艦深度思考領銜，專攻找歌判斷、找譜語意、代碼、哲學與高難度推理)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
AUDIO_CACHE_DIR = os.path.join(DATA_DIR, "recent_audio")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
MAX_LOCAL_AUDIO_FILES = 80  #  自動保留本機最近 80 句高音質錄音

def save_local_audio_clip(audio_base64: str) -> Optional[str]:
    """將麥克風錄音 WAV 保存至本機快取目錄，並自動滾動清理過舊檔案"""
    if not audio_base64:
        return None
    try:
        raw_bytes = base64.b64decode(audio_base64) if isinstance(audio_base64, str) else audio_base64
        if len(raw_bytes) < 100:
            return None
        
        ts_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d_%H%M%S_%f")[:19]
        file_name = f"mic_{ts_str}.wav"
        file_path = os.path.join(AUDIO_CACHE_DIR, file_name)
        
        with open(file_path, "wb") as f:
            f.write(raw_bytes)
            
        # 滾動清理：若超過 MAX_LOCAL_AUDIO_FILES，自動刪除最舊的檔案
        all_audios = sorted(glob.glob(os.path.join(AUDIO_CACHE_DIR, "mic_*.wav")))
        if len(all_audios) > MAX_LOCAL_AUDIO_FILES:
            for old_f in all_audios[:-MAX_LOCAL_AUDIO_FILES]:
                try: os.remove(old_f)
                except Exception: pass
                
        return file_path
    except Exception:
        return None

def get_recent_local_audio_clips(limit: int = 5) -> List[str]:
    """取得本機最近幾筆有效錄音檔案路徑"""
    all_audios = sorted(glob.glob(os.path.join(AUDIO_CACHE_DIR, "mic_*.wav")))
    return all_audios[-limit:] if all_audios else []

def load_audio_clip_base64(file_path: str) -> Optional[str]:
    """從本機讀取錄音檔並轉為 Base64 字串供 Gemini 調用"""
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass
    return None

API_LOCKS_FILE = os.path.join(DATA_DIR, "api_locks_cache.json")
API_LOCKS = {}

# ────────────────────────────────────────────────────────
#  3. API 頻率限制、冷卻與熔斷管理系統 (Circuit Breaker)
# ────────────────────────────────────────────────────────
#  功能目的：
#    當某金鑰或模型回傳 429 / 503 / 資源耗盡時，自動對該通道加鎖冷卻，
#    並將鎖定狀態持久化到本地 JSON，防止開台期間重複呼叫故障通道。

def load_api_locks():
    """載入並清理已過期的 API 鎖定快取"""
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
    """持久化 API 鎖定狀態到本地檔案"""
    try:
        with open(API_LOCKS_FILE, "w", encoding="utf-8") as f:
            json.dump(API_LOCKS, f)
    except Exception:
        pass

load_api_locks()


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
    duration = parse_cooldown_seconds(error_msg, headers)
    API_LOCKS[target_id] = time.time() + duration
    save_api_locks()
    
    if duration >= 3600: dur_str = f"{duration/3600:.1f}h"
    elif duration >= 60: dur_str = f"{duration/60:.1f}m"
    else: dur_str = f"{int(duration)}s"
        
    reason_label = ""
    err_low = str(error_msg).lower()
    if any(k in err_low for k in ["per day", "requests per day", "daily requests", "rpd", "tokens per day", "tpd"]):
        reason_label = " (今日配額已滿 RPD)"
    elif "429" in err_low or "rate limit" in err_low:
        reason_label = " (頻率超限 429)"
    elif "503" in err_low or "high demand" in err_low or "unavailable" in err_low:
        reason_label = " (伺服器過載 503)"
    elif "404" in err_low or "not_found" in err_low:
        reason_label = " (模型未開通/下架 404)"

    sys_notify(f" 封印通道 {target_id}{reason_label} ({dur_str})", duration=3.0)
    log_print(f"🔒 [通道冷卻] 通道 {target_id} 封印 {dur_str}{reason_label}")

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


#  自主發話時主動保留/跳過的頂配旗艦大腦清單（保留給老爸主動對話使用）




CURRENT_GEMINI_KEY_STEP = 0
_MIND_LIVE_KEY_COOLDOWN: dict = {}  #  心流 Live 金鑰冷卻紀錄 {api_key: 冷卻到期 timestamp}，失敗後 60 秒跳過


# ────────────────────────────────────────────────────────
#  4. 全域狀態變數、硬體偵測與通知設定 (Global State & Specs)
# ────────────────────────────────────────────────────────
#  功能目的：
#    - 自動偵測主機實體螢幕解析度 (DPI 感知)、CPU、GPU 與記憶體硬體規格。
#    - 維護 7L 的即時運行狀態（思考中、發話中、彈琴中、麥克風監聽）。
#    - 定義多執行緒佇列（語音輸出隊列、彈幕看板隊列、VTS 參數隊列）。

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
DEFAULT_USER_TITLE = "老爸"


tk_listener.IS_STREAMING = False
current_ai_state = "IDLE"  # IDLE / THINKING / TALKING / PIANO / SINGING
IS_SINGING_ACTIVE = False
last_interaction_time = time.time()
record_interaction_tick()

def touch_interaction():
    """統一更新所有互動時間戳與 Tick 心跳 (1 Tick = 1 秒)"""
    global last_interaction_time
    last_interaction_time = time.time()
    record_interaction_tick()
latest_screen_cache = None
LATEST_HD_SCREEN_BYTES = None  #  原生 100% 超高清全解析度截圖緩存 (4K/原生，供燈箱放大檢視)
SCREEN_TEMPORAL_HISTORY = deque(maxlen=60)  #  螢幕時序動態連續影格緩衝區（每 1.8s 一幀，保留最多 60 幀 ≈ 108 秒歷史）
LAST_VISION_LOOK_TIME = 0.0  #  上次餘光「認真看」的時間，用於切取時序動態幀
current_voice_task = None
last_spoken_text = ""

IS_MIC_ENABLED = True
IS_AUTO_WANDER_ENABLED = True
IS_AUTO_PIANO_ENABLED = False  #  是否允許 7L 在閒置時自主彈琴（預設關閉，杜絕未經指示突然彈琴打擾或與電腦音樂衝突）
IS_PROACTIVE_SPEAK_ENABLED = True  #  視覺陪伴主動搭話開關（預設開啟）
IS_PERIPHERAL_VISION_ENABLED = True  #  餘光視覺感知中樞開關（預設開啟）
IS_FACE_TRACKING_ENABLED = True  #  AI 視線與頭部追蹤開關（預設開啟）
LAST_WANDER_TIME = time.time()
IS_SLEEPING = False
TOTAL_API_CALLS = 0
API_LATENCY_HISTORY = deque(maxlen=20)
CURRENT_VISION_CHANGE_LEVEL = "none"
CURRENT_VISION_CHANGE_SCORE = 0

def record_api_call_latency(duration_sec: float):
    global API_LATENCY_HISTORY
    if duration_sec and duration_sec > 0.05:
        API_LATENCY_HISTORY.append(round(duration_sec, 2))

def get_api_stress_metrics():
    """計算大腦 API 平均耗時與壓力指標 (Stress Level)"""
    if not API_LATENCY_HISTORY:
        return {
            "avg_latency": 0.0,
            "latency_str": "0.0s",
            "stress_percent": 15.0,
            "stress_level": "relaxed",
            "stress_tag": "輕鬆"
        }
    avg = sum(API_LATENCY_HISTORY) / len(API_LATENCY_HISTORY)
    if avg <= 1.0:
        pct = 15.0 + (avg / 1.0) * 10.0
        level = "relaxed"
        tag = "輕鬆"
    elif avg <= 2.2:
        pct = 25.0 + ((avg - 1.0) / 1.2) * 30.0
        level = "normal"
        tag = "適中"
    elif avg <= 4.0:
        pct = 55.0 + ((avg - 2.2) / 1.8) * 25.0
        level = "stressed"
        tag = "緊繃"
    else:
        pct = min(98.0, 80.0 + ((avg - 4.0) / 3.0) * 18.0)
        level = "critical"
        tag = "超載"
    return {
        "avg_latency": round(avg, 2),
        "latency_str": f"{avg:.1f}s",
        "stress_percent": round(pct, 1),
        "stress_level": level,
        "stress_tag": tag
    }

async def set_sleep_mode(enable: bool):
    global IS_SLEEPING, current_ai_status_str, current_ai_state
    if enable:
        try:
            from core.identity import is_vtuber
            if is_vtuber():
                log_print("🚫 [系統] VTuber 模式禁用休眠（7x24 觀眾互動不打烊）")
                return False
        except Exception:
            pass
    IS_SLEEPING = bool(enable)
    if IS_SLEEPING:
        current_ai_status_str = " 閉眼沉睡中 (0 API 消耗)"
        current_ai_state = "SLEEP"
        try:
            await interrupt_current_speech(clear_queue=True, reason="老爸開啟休眠模式")
        except Exception:
            pass
        if vc.GLOBAL_VTS:
            try:
                await set_vts_expression(vc.GLOBAL_VTS, "_RESET_")
            except Exception:
                pass
        log_print("🌙 [系統] 7L 已進入深層睡眠模式（雙眼安詳閉合，0 API 消耗，安靜沉睡中...）")
    else:
        current_ai_status_str = " 正常運作中"
        current_ai_state = "IDLE"
        if vc.GLOBAL_VTS:
            try:
                await set_vts_expression(vc.GLOBAL_VTS, "_RESET_")
            except Exception:
                pass
        log_print("☀️ [系統] 7L 已被喚醒，雙眼睜開，恢復全神經系統運作！")
    return IS_SLEEPING

current_mic_volume_str = "[ 麥克風就緒]"
CURRENT_MIC_VOL_PERCENT = 0
current_ai_status_str = "正常運作中"
current_mic_action_str = "待命"
current_model_tag = " 初始化中"
current_screen_context = "目前沒有特別的畫面動態。"
VISION_HISTORY_STREAM = deque(maxlen=60)

def record_vision_history_entry(text: str, scene: str = ""):
    global current_screen_context
    clean_t = (text or "").strip()
    if not clean_t or clean_t == "目前沒有特別的畫面動態。":
        return
    current_screen_context = clean_t
    if VISION_HISTORY_STREAM and VISION_HISTORY_STREAM[-1].get("text") == clean_t:
        return
    t_now = time.time()
    try:
        t_str = datetime.fromtimestamp(t_now, tz=ZoneInfo('Asia/Taipei')).strftime('%H:%M:%S')
    except Exception:
        t_str = datetime.now().strftime('%H:%M:%S')
    entry = {
        "time": t_now,
        "time_str": t_str,
        "scene": scene or "畫面感知",
        "text": clean_t
    }
    VISION_HISTORY_STREAM.append(entry)
    try:
        web_dash.broadcast_event("vision_update", entry)
    except Exception:
        pass

current_system_audio_context = "目前沒有播放特別的聲音。"
tk_listener.current_tiktok_status_str = "[ TikTok: 待命中]"
CURRENT_SPEAKING_TARGET = "none"

current_system_notification = ""
notification_expire_time = 0.0
active_timers = set()
speech_queue = asyncio.Queue()  
pygame.mixer.init()

#  真實音訊波形對嘴中樞 (RMS 包絡提取與物理開閉濾波)
CURRENT_MOUTH_ENVELOPE = []
CURRENT_SPEECH_START_TIME = 0.0
CURRENT_SMOOTH_MOUTH = 0.0
IS_SHOCK_SCREAMING = False

def extract_audio_mouth_envelope(sound_obj, fps=25) -> list:
    """從 MP3/音訊波形中以 25fps (每 40ms) 精確提取口型開合振幅包絡 (0.0~1.0)，包含動態增益與噪聲門限"""
    try:
        import pygame.sndarray
        import numpy as np
        arr = pygame.sndarray.array(sound_obj)
        if arr.size == 0:
            return []
        if arr.ndim > 1:
            arr = np.mean(arr, axis=1)  # 雙聲道轉單聲道
        
        freq = pygame.mixer.get_init()[0] if pygame.mixer.get_init() else 44100
        frame_len = max(1, int(freq / fps))
        envelope = []
        for i in range(0, len(arr), frame_len):
            chunk = arr[i:i+frame_len].astype(np.float32)
            if len(chunk) > 0:
                rms = float(np.sqrt(np.mean(chunk**2)))
                envelope.append(rms)
        
        if not envelope:
            return []
            
        max_rms = max(envelope)
        if max_rms <= 10.0:
            return [0.0] * len(envelope)
            
        # 噪聲門限 (小於 10% 最大音量或絕對 RMS < 200 直接歸零閉嘴，確保子音、句逗、吸氣與微量伴奏殘留自然閉口)
        gate = max(200.0, max_rms * 0.10)
        target_span = max(1.0, max_rms * 0.65)
        
        norm_env = []
        for r in envelope:
            if r < gate:
                norm_env.append(0.0)
            else:
                val = min(1.0, (r - gate) / target_span)
                norm_env.append(round(val, 3))
        return norm_env
    except Exception:
        return []



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
#  5. Firebase Firestore 雲端永久記憶與觀眾個人檔案系統 (0 DLL 純 Python 異步 REST 客戶端)
# ────────────────────────────────────────────────────────
#  功能目的：
#    - 提供 0 C/DLL 依賴的純 Python 異步 Firestore REST 客戶端，避免 Windows AppLocker 阻擋 gRPC 二進位檔。
#    - 儲存老爸與 7L 的深度私聊記憶（`channel_history`）、核心人格標籤（`channel_meta`）。
#    - 儲存 TikTok 直播觀眾個人檔案（稱呼、關係、印象、最後見面時間），自動雙向同步至本地 JSON 快取。

db = None
# PROVIDER: FIRESTORE（預設拔除：FIREBASE_ENABLED=1 才連；全呼叫點另有本地 JSON 備援）
_FIREBASE_ON = (os.getenv("FIREBASE_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes")
if FIREBASE_CRED_JSON and _FIREBASE_ON:
    try:
        cred_dict = json.loads(FIREBASE_CRED_JSON)
        import core.db as db_module
        db = db_module.init_firestore(cred_dict)
        realtime_task_mgr.set_db(db)
        print("【💾 系統通知】Firebase Firestore 雲端永久大腦就緒（實時任務中樞已連線雲端）！")
    except Exception as e:
        print(f"【⚠️ 系統警告】Firebase 連線失敗: {e}，將僅使用本地快取。")
else:
    print("【ℹ️ 系統通知】純本地模式（Firebase 預設拔除；多機同步需設 FIREBASE_ENABLED=1＋FIREBASE_CRED_JSON）。")

async def get_user_profile():
    profile = None
    if db is not None:
        try:
            doc = await db.collection("user_memory").document(DEFAULT_CHANNEL_ID).get()
            if doc.exists: profile = doc.to_dict()
        except Exception: pass
        
    if not profile:
        file_path = USER_PROFILE_FILE
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
        with open(USER_PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except Exception: pass

# ──  觀眾身份識別（Firebase viewer_profiles + 本地快取）──────────────────────


# ──  7L 雲端大腦提示詞與認知自我演進系統 (100% 雲端 Firestore 動態加載，本機零寫死提示詞) ────────────




async def add_few_shot_example(scenario: str, user_input: str, thought: str, reply: str):
    """7L 自主新增神回覆範例到雲端示範庫"""
    kn = await get_cloud_knowledge()
    examples = kn.get("few_shot_examples", [])
    new_ex = {
        "scenario": str(scenario).strip(),
        "input": str(user_input).strip(),
        "thought": str(thought).strip(),
        "reply": str(reply).strip()
    }
    examples.append(new_ex)
    kn["few_shot_examples"] = examples
    await save_cloud_knowledge(kn)
    log_print(f"🎯 [7L 雲端示範演進] 7L 自主新增神回覆案例：『{scenario} ➔ {reply}』")

async def learn_new_meme(meme_desc: str):
    """7L 自主學習並記憶新梗到雲端知識庫"""
    await update_cloud_prompt_field("memes_and_slang", meme_desc)

async def learn_new_fact(fact_desc: str):
    """7L 自主學習並記憶新事實/知識到雲端知識庫"""
    await update_cloud_prompt_field("learned_facts", fact_desc)

async def update_custom_rule(rule_desc: str):
    """7L 自主更新或設定心智原則"""
    await update_cloud_prompt_field("custom_rules", rule_desc)


def extract_text_from_content(content):
    if isinstance(content, str): return content
    if isinstance(content, list): return " ".join([p.get("text", "") for p in content if p.get("type") == "text"])
    return ""

async def update_daily_diary(channel_id, recent_chat):
    """PROVIDER: GEMINI（日記濃縮走 fetch_ai_response；向量已刪；見 docs/AI_SOURCES.md）"""
    tz = ZoneInfo("Asia/Taipei")
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    chat_text = "\n".join([f"{msg['role']}: {extract_text_from_content(msg['content'])}" for msg in recent_chat if extract_text_from_content(msg['content']).strip()])
    
    if len(chat_text.strip()) < 40: return
    
    diary_dir = "diaries"
    os.makedirs(diary_dir, exist_ok=True)
    diary_file_path = os.path.join(diary_dir, f"diary_{today_str}.json")

    existing_summary = ""
    if db is not None:
        try:
            doc = await db.collection("daily_diary").document(today_str).get()
            if doc.exists: existing_summary = doc.to_dict().get("summary", "")
        except Exception: pass
    elif os.path.exists(diary_file_path):
        try:
            with open(diary_file_path, "r", encoding="utf-8") as f:
                existing_summary = json.load(f).get("summary", "")
        except Exception: pass
        
    diary_prompt = (
        f"【後台任務：每日核心日記整合與高強度去重】\n"
        f"妳是 7L 的日記記憶中樞。請將『舊日記摘要』與『新對話』融合成一份完全去重、精簡濃縮後的今日日記。\n\n"
        f" 核心守則：\n"
        f"1. 刪除重複部分，保留重點。\n"
        f"2. 總句數嚴格限制在 3 句以內。\n"
        f"3. 絕對不要有任何前言或結尾，直接輸出整合後的日記內容。\n\n"
        f" [舊日記摘要]：\n{existing_summary if existing_summary else '(無)'}\n\n"
        f" [新對話紀錄]：\n{chat_text}\n"
    )
    
    messages = [{"role": "user", "content": diary_prompt}]
    updated_summary = await fetch_ai_response(messages, is_proactive=True)
    
    if updated_summary and "沉默" not in updated_summary:
        diary_payload = {
            "summary": updated_summary.strip(), 
            "date": today_str
        }
            
        if db is not None:
            try:
                await db.collection("daily_diary").document(today_str).set(diary_payload, merge=True)
            except Exception: pass
            
        try:
            with open(diary_file_path, "w", encoding="utf-8") as f:
                json.dump(diary_payload, f, ensure_ascii=False, indent=2)
        except Exception: pass


# ────────────────────────────────────────────────────────
#  6. Live2D / VTube Studio 表情與姿態控制 & 雙軌空間走位系統 (Spatial Movement)
# ────────────────────────────────────────────────────────

# ──  7L 即時時事與熱搜情報中樞 (Trending News Engine) ────────────────────────
LATEST_TRENDING_NEWS_SUMMARY = ""
LAST_TRENDING_NEWS_FETCH_TIME = 0.0

async def get_trending_news_briefing() -> str:
    """取得今日最新即時時事與熱搜快訊（背景快取，每 2 小時自動刷新）"""
    global LATEST_TRENDING_NEWS_SUMMARY, LAST_TRENDING_NEWS_FETCH_TIME
    now = time.time()
    if LATEST_TRENDING_NEWS_SUMMARY and (now - LAST_TRENDING_NEWS_FETCH_TIME < 7200.0):
        return LATEST_TRENDING_NEWS_SUMMARY

    try:
        if tavily_client:
            res = await asyncio.to_thread(
                tavily_client.search,
                query="台灣 今天重大時事新聞 熱門焦點",
                topic="news",
                search_depth="advanced"
            )
            if isinstance(res, dict) and "results" in res:
                items = []
                for idx, item in enumerate(res["results"][:4], 1):
                    t = item.get("title", "").strip()
                    c = item.get("content", "").strip()[:120]
                    if t:
                        items.append(f"{idx}. {t}：{c}")
                if items:
                    LATEST_TRENDING_NEWS_SUMMARY = "【 7L 掌握的今日即時重大時事快訊】：\n" + "\n".join(items)
                    LAST_TRENDING_NEWS_FETCH_TIME = now
                    log_print("📰 [時事情報中樞] 已自動更新今日最新即時重大時事快訊！")
                    return LATEST_TRENDING_NEWS_SUMMARY
    except Exception as e:
        log_print(f"⚠️ [時事情報獲取異常]: {e}")
    return LATEST_TRENDING_NEWS_SUMMARY

def search_google(query: str) -> str:
    """使用 Google / 網路搜尋引擎查詢最新的即時資訊、天氣、時事新聞或未知知識。
    
    Args:
        query: 要搜尋的關鍵字或問題描述
    """
    print(f"\n🔍 [Tool 調用] 7L 正在使用 Google / 網路搜尋: 「{query}」")
    try:
        is_news_query = any(k in query for k in ["新聞", "時事", "今天", "昨天", "最新", "發生什麼", "快訊", "熱搜", "熱門", "突發", "大事"])
        topic_mode = "news" if is_news_query else "general"

        if tavily_client:
            res = tavily_client.search(query=query, topic=topic_mode, search_depth="advanced")
            if isinstance(res, dict) and "results" in res:
                snippets = []
                for item in res["results"][:4]:
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

# ────────────────────────────────────────────────────────
#  7. 7L 本機遊樂場沙盒 (7L_Playground)
# ────────────────────────────────────────────────────────
PLAYGROUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "7L_Playground")
os.makedirs(PLAYGROUND_DIR, exist_ok=True)

#  敏感/高危指令安全黑名單過濾
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
                output_msg = " 程式碼執行完成 (ReturnCode 0)。"
                if stdout_text.strip():
                    output_msg += f"\n輸出結果：\n{stdout_text.strip()[:500]}"
                return output_msg
            else:
                return f" 程式執行結束但回傳錯誤 (ReturnCode {proc.returncode})。\n錯誤訊息：\n{(stderr_text or stdout_text).strip()[:500]}"
        except subprocess.TimeoutExpired:
            return " 遊戲/程式視窗已成功在老爸螢幕上開啟並持續運行中！"
    except Exception as e:
        return f" 執行過程發生異常: {e}"

async def execute_local_python_code(code_string: str) -> str:
    """在 7L 專屬的本機遊樂場 (7L_Playground) 儲存並執行 Python 程式碼"""
    #  安全預設：關閉（直播場景等於「遠端可執行任意本機碼」，且 Web 控制台的
    #    /api/tools/execute 也走這裡）。要恢復需顯式設環境變數 ALLOW_LOCAL_PYTHON_CODE=1。
    if os.getenv("ALLOW_LOCAL_PYTHON_CODE", "0").strip().lower() not in ("1", "true", "yes"):
        print("🛑 [安全攔截] execute_local_python_code 已停用（需 ALLOW_LOCAL_PYTHON_CODE=1 才開放）")
        return ("安全限制：本機代碼執行功能目前已停用。"
                "請改用現有工具達成需求（search_google / 鋼琴 / generate_ai_image / set_timer 等）。")
    print("\n💻 [Tool 調用] 7L 正在本機沙盒 (7L_Playground) 執行 Python 程式碼...")
    
    for pattern in DANGEROUS_CODE_PATTERNS:
        if re.search(pattern, code_string, re.IGNORECASE):
            print(f"⚠️ [安全攔截] 偵測到受限指令 pattern: {pattern}")
            return f"安全限制攔截：程式碼包含受限的高風險指令 ({pattern})，已拒絕執行以保護老爸的電腦。"
            
    temp_file = os.path.join(PLAYGROUND_DIR, "temp_run.py")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code_string)
    except Exception as e:
        return f"寫入程式碼檔案失敗: {e}"
        
    result = await asyncio.to_thread(_run_subprocess_code, temp_file, timeout=15)
    print(f"💻 [Tool 完成] 執行結果: {result[:120]}...")
    return result

DRAWING_DIR = os.path.join(PLAYGROUND_DIR, "drawings")
os.makedirs(DRAWING_DIR, exist_ok=True)

IMAGE_GEN_MODELS = [
    #  Nano Banana 系列 (Gemini 原生生圖創作)
    "gemini-3.1-flash-image",           # Nano Banana 2
    "gemini-3.1-flash-image-preview",   # Nano Banana 2 Preview
    "gemini-3-pro-image",               # Nano Banana Pro
    "gemini-3-pro-image-preview",       # Nano Banana Pro Preview
    "nano-banana-pro-preview",          # Nano Banana Pro Preview Alias
    "gemini-3.1-flash-lite-image",      # Nano Banana 2 Lite
    
    #  Imagen 4 頂尖寫實與二次元生圖
    "imagen-4.0-ultra-generate-001",    # Imagen 4 Ultra (極限畫質)
    "imagen-4.0-generate-001",          # Imagen 4 標準版
    "imagen-4.0-fast-generate-001"      # Imagen 4 Fast (極速版)
]

async def generate_ai_image(prompt: str) -> str:
    """PROVIDER: GEMINI-IMAGE（Nano Banana 系； 配額表全系 0/0/0，現降級中；見 docs/AI_SOURCES.md）使用 Google 頂尖 AI 生圖模型 (Nano Banana / Gemini Image / Imagen / FLUX) 繪製高品質圖片、二次元插圖或藝術創作，並自動在老爸的螢幕上彈出展示。
    
    Args:
        prompt: 畫面內容的詳細描述提示詞（建議包含主體、外貌、風格、色彩、光影等豐富細節）。
    """
    import urllib.parse
    print(f"\n🎨 [Tool 調用] 7L 正在啟動 AI 繪圖創作: 「{prompt[:60]}...」")
    
    img_bytes = None
    
    #  第一防線：Google 原生生圖模型 (若金鑰有配額)
    if GEMINI_KEYS:
        num_keys = min(4, len(GEMINI_KEYS))
        for offset in range(num_keys):
            if img_bytes: break
            g_key = GEMINI_KEYS[offset]
            temp_client = genai.Client(api_key=g_key)
            
            for img_model in ["gemini-3.1-flash-lite-image", "gemini-3.1-flash-image", "gemini-3-pro-image"]:
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

    #  第二防線：FLUX.1 / SDXL 頂尖二次元與寫實藝術引擎 (100% 保證出圖、0 配額限制、超高畫質)
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
            
        return f"（系統回報：插畫已成功繪製並儲存至 {file_name}，且已在桌面彈出展示）"

    return "（系統回報：生圖伺服器當前忙線，稍後可再重試）"

async def move_spatial_position(
    target_position: str = "自由漫遊", 
    delta_x: float = None,
    delta_y: float = None,
    delta_size: float = None,
    scale_factor: float = None,
    duration: float = 2.0
) -> str:
    """控制 7L 的 Live2D 模型在 VTube Studio 畫布內平滑移動位置、相對微調或縮放。
    
    Args:
        target_position: 目標語意位置或微調指令（如：'右側', '右下角', '左側', '左上角', '正中間', '靠近', '躲角落', '鋼琴旁', '往右+10', '往左-15', '往上+5', '往下-10', '放大+10', '縮小-5', '自由漫遊', '原位'）。
        delta_x: (可選) X 軸相對平移量（例如: +10 向右微調, -10 向左微調）。
        delta_y: (可選) Y 軸相對平移量（例如: +10 向上微調, -10 向下微調）。
        delta_size: (可選) 尺寸相對大小微調（例如: +5 放大, -5 縮小）。
        scale_factor: (可選) 模型整體等比例縮放倍率（例如: 1.2 代表放大 20%, 0.8 代表縮小 20%）。
        duration: (可選) 移動平滑過渡秒數 (預設 2.0 秒)。
    """
    print(f"\n🚀 [Tool 調用] 7L 正在自主調整模型位置: 「{target_position}」 (dx={delta_x}, dy={delta_y}, d_sz={delta_size}, 縮放={scale_factor})")
    res = await apply_spatial_position(
        position_name=target_position, 
        delta_x=delta_x,
        delta_y=delta_y,
        delta_size=delta_size,
        scale_factor=scale_factor,
        duration=duration
    )
    return f"模型位置調整完成：{res}"


# [Virtual Piano Module has been extracted to services/piano_engine.py]

def control_microphone(is_enabled: bool) -> str:
    """控制 7L 的麥克風收音開關（開啟或靜音）。
    
    Args:
        is_enabled: True 為開啟麥克風收音，False 為關閉麥克風（靜音）。
    """
    global IS_MIC_ENABLED
    IS_MIC_ENABLED = is_enabled
    state_str = "開啟" if is_enabled else "關閉 (靜音)"
    log_print(f"🎙️ [麥克風控制] 已{state_str}麥克風收音。")
    return ""


def search_internet(query):
    """PROVIDER: LOCAL-SCRAPE（search_google 無 API；Tavily 另見 search 呼叫點；見 docs/AI_SOURCES.md）"""
    return search_google(query)






# ────────────────────────────────────────────────────────
#  9. 防跳針與記憶去重系統 (Code-Level Anti-Repetition)
# ────────────────────────────────────────────────────────

#  7L 即時意識流與心流記憶 (Stream of Consciousness)
RECENT_STREAM_OF_CONSCIOUSNESS = []

def is_thought_repetitive(new_thought: str, threshold: float = 0.65, time_window: float = 300.0) -> bool:
    """檢查新思緒是否與近期心流重複（比對文字核心特徵與相似度，杜絕 7L 心聲跳針反覆發出）"""
    if not new_thought:
        return True
    clean_new = re.sub(r'[^\w\u4e00-\u9fa5]', '', str(new_thought)).strip()
    if len(clean_new) < 4:
        return True
    
    #  陪伴/無動態類型的思緒語意防跳針：若近期已經安靜陪伴過，禁止反覆重提「安靜陪伴、不要擋到、縮小身體」
    companion_markers = [
        "安靜陪伴", "不要擋到", "沒什麼新動態", "沒有新動態", "無全新動態", "無全新事件", 
        "縮小身體", "縮小一點", "嘟囔舊思緒", "silence", "安靜守護", "確認系統狀態", 
        "確認系統", "根據規範", "按照規範", "系統規範", "無新進展", "無事就安靜", 
        "按照內心流動", "稍微 wink", "執行 wink", "前幾輪已經在陪伴"
    ]
    new_is_companion = any(k in new_thought.lower() for k in companion_markers)
    
    now = time.time()
    # 1. 檢查近期的心流思緒隊列 (RECENT_STREAM_OF_CONSCIOUSNESS)
    for item in reversed(RECENT_STREAM_OF_CONSCIOUSNESS):
        if now - item.get("time", 0) > time_window:
            break
        past_th = item.get("thought", "")
        if new_is_companion and any(k in str(past_th).lower() for k in companion_markers):
            return True
        clean_past = re.sub(r'[^\w\u4e00-\u9fa5]', '', str(past_th)).strip()
        if not clean_past:
            continue
        if clean_new == clean_past:
            return True
        ratio = difflib.SequenceMatcher(None, clean_new, clean_past).ratio()
        if ratio >= threshold:
            return True
        if len(clean_new) >= 12 and len(clean_past) >= 12:
            if clean_new in clean_past or clean_past in clean_new:
                return True

    # 2. 同步檢查 UNIFIED_LIVE_MEMORY 裡最後 15 筆 thought
    for mem in list(UNIFIED_LIVE_MEMORY)[-15:]:
        if mem.get("role") == "thought" or mem.get("source") == "thought" or mem.get("target") == "內心流動":
            cnt = str(mem.get("content", ""))
            if new_is_companion and any(k in cnt.lower() for k in companion_markers):
                return True
            clean_mem = re.sub(r'[^\w\u4e00-\u9fa5]', '', cnt).strip()
            if not clean_mem:
                continue
            if clean_new == clean_mem:
                return True
            ratio = difflib.SequenceMatcher(None, clean_new, clean_mem).ratio()
            if ratio >= threshold:
                return True
            if len(clean_new) >= 12 and len(clean_mem) >= 12:
                if clean_new in clean_mem or clean_mem in clean_new:
                    return True

    return False

def record_internal_thought(user_words: str, thought: str, emotion: str = "", force: bool = False):
    if not thought:
        return
    #  心流防跳針過濾：若與近 5 分鐘內思緒高度相似，不重複寫入記憶與時間線
    if not force and is_thought_repetitive(thought):
        return

    RECENT_STREAM_OF_CONSCIOUSNESS.append({
        "time": time.time(),
        "words": user_words,
        "thought": thought,
        "emotion": emotion,
        "is_read": False,
        "consumed": False
    })
    if len(RECENT_STREAM_OF_CONSCIOUSNESS) > 10:
        RECENT_STREAM_OF_CONSCIOUSNESS.pop(0)

    #  將 7L 嶄新的內心流動/心聲思緒同步持久化至全集中全景記憶中樞 (統一時間線與歷史紀錄)
    try:
        append_to_unified_memory(
            speaker="7L",
            target="內心流動",
            content=thought,
            role="thought",
            source="thought"
        )
    except Exception:
        pass

def get_recent_thoughts_summary() -> str:
    
    if not RECENT_STREAM_OF_CONSCIOUSNESS:
        return ""
    #  已讀過濾：若該思緒已被自主發話或對話消費已讀，不再反覆注入 Prompt，徹底消除反覆看同一句說話的跳針問題
    unconsumed = [item for item in RECENT_STREAM_OF_CONSCIOUSNESS if not item.get("consumed", False)]
    if not unconsumed:
        return ""
    lines = []
    for item in unconsumed[-3:]:
        lines.append(f"- 剛才聽到「{item['words']}」時，妳腦內的思緒：『{item['thought']}』")
    return "【 妳近期的腦內心流思緒（最新未讀思緒，僅供參考，若已聊過請勿重複）：】：\n" + "\n".join(lines)

def mark_recent_thoughts_as_read():
    """ 將當前累積的所有腦內心流思緒標記為已讀/已消費，防止後續自主大腦重複對同一句話跳針"""
    
    for item in RECENT_STREAM_OF_CONSCIOUSNESS:
        item["consumed"] = True
        item["is_read"] = True

LAST_TTS_END_TIME = 0.0
IS_MP3_PLAYING = False
MP3_ECHO_TRAILING_CHUNKS = 0
CURRENT_TTS_ID = 0
LAST_ECHO_FILTERED_TTS_ID = -1

def normalize_text_for_echo(t: str) -> str:
    if not t: return ""
    t_norm = unicodedata.normalize('NFKC', str(t))
    clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', t_norm).strip().lower()
    clean = clean.replace("爸爸", "老爸").replace("阿爸", "老爸").replace("拔拔", "老爸").replace("老爹", "老爸")
    clean = clean.replace("妳", "你")
    return clean


def is_too_similar_to_recent(text: str, threshold: float = 0.48) -> bool:
    return False

RECENT_SYSTEM_AUDIO_TRANSCRIPTS = []  # [(timestamp, text), ...]
LATEST_SYSTEM_AUDIO_RMS = 0.0
LATEST_SYSTEM_AUDIO_TEXT = ""
LATEST_SYSTEM_AUDIO_TEXT_TIME = 0.0
LATEST_SYSTEM_MUSIC_INFO = ""  #  7L 即時聽出之電腦播放歌曲、樂曲名稱或樂器風格
LATEST_SYSTEM_MUSIC_TIME = 0.0
LAST_MUSIC_IDENTIFY_TIME = 0.0
CURRENT_SYSTEM_AUDIO_VOL_PERCENT = 0
LATEST_REALWORLD_SPEECH_TEXT = ""
LATEST_REALWORLD_SPEECH_TIME = 0.0

def is_7l_voice_echo(stt_text: str, is_dad_verified: bool = False) -> bool:
    """ 7L 自身發話喇叭回音鑑別：
    比對 STT 文字與 7L 剛說的話，精準過濾麥克風收錄之自身喇叭殘響。
     嚴格遵循「過濾只過濾一次就好」原則：每句發話最多只攔截一次回音，絕不重複誤殺。
    """
    global LAST_ECHO_FILTERED_TTS_ID, MP3_ECHO_TRAILING_CHUNKS
    clean_stt = normalize_text_for_echo(stt_text)
    if not clean_stt:
        return False

    #  0. 過濾只過濾一次就好：若當前這一次發話已經過濾過一次回音，後續一律放行！
    if CURRENT_TTS_ID > 0 and LAST_ECHO_FILTERED_TTS_ID == CURRENT_TTS_ID:
        return False

    #  1. 老爸專屬呼喚 / 指令前綴豁免保護 (支援半形與全形同音詞)：
    # 7L 自身發話絕不可能以「7L」、「阿七」、「CL」、「謝龍」自稱下指令
    call_names = [
        "7l", "七l", "cl", "謝龍", "谢龙", "西l", "吸l", 
        "奇l", "琪l", "期l", "氣l", "切爾", "琪兒", 
        "阿七", "小七", "七妹", "7妹", "7哥", "七哥"
    ]
    if any(name in clean_stt for name in call_names):
        return False

    #  2. 重要控制指令豁免保護：若為老爸常用指令詞彙且聲紋判定為老爸，絕不過濾
    control_keywords = ["重開機", "重開", "重啟", "關機", "退出", "別彈了", "換歌", "暫停", "閉嘴", "安靜", "停"]
    if is_dad_verified and any(k in clean_stt for k in control_keywords):
        return False

    #  3. 物理聲學時效防護：喇叭聲音與房間殘響若已結束 > 3.5 秒，絕不可能存在自身喇叭回音
    now = time.time()
    is_recent_speech = IS_MP3_PLAYING or (now - LAST_TTS_END_TIME < 3.5)
    if not is_recent_speech:
        return False

    recent_pool = [normalize_text_for_echo(m) for m in RECENT_BOT_MESSAGES[-5:] if m]
    combined_recent = "".join(recent_pool)
    if not combined_recent:
        return False

    stt_len = len(clean_stt)

    #  聲紋特徵加持：若已通過神經網路驗證為老爸本人聲音（非 7L 喇叭女聲）
    # 短中句（< 12 字，如日常對話、短指令、覆誦）100% 保證通行，絕不當成回音過濾！
    if is_dad_verified and stt_len < 12:
        return False

    # 1. 精確整句/長子句包含比對：
    if clean_stt in combined_recent or any(clean_stt in m for m in recent_pool):
        if stt_len >= 6 or any(clean_stt == m for m in recent_pool):
            if not is_dad_verified or stt_len >= 12:
                LAST_ECHO_FILTERED_TTS_ID = CURRENT_TTS_ID
                MP3_ECHO_TRAILING_CHUNKS = 0
                log_print(f"🔇 [7L 喇叭回音過濾] 判定為 7L 自身發話喇叭回音 (精確包含): 「{stt_text}」 ➔ 已安全過濾 (僅過濾一次，後續解鎖放行)！")
                return True

    # 2. 相似度與覆蓋率比對 (針對中長句回音與 ASR 串音)
    if stt_len <= 5:
        cov_threshold = 0.90
        longest_threshold = 0.85
        min_longest_size = 4
    elif stt_len <= 8:
        cov_threshold = 0.80
        longest_threshold = 0.70
        min_longest_size = 5
    else:
        cov_threshold = 0.65 if IS_MP3_PLAYING else 0.75
        longest_threshold = 0.55 if IS_MP3_PLAYING else 0.65
        min_longest_size = 6

    if is_dad_verified:
        cov_threshold = 0.92
        longest_threshold = 0.88
        min_longest_size = max(min_longest_size, 8)

    for old_m in recent_pool:
        if not old_m:
            continue
        matcher = difflib.SequenceMatcher(None, clean_stt, old_m)
        match_sum = sum(b.size for b in matcher.get_matching_blocks())
        coverage = match_sum / stt_len
        longest_match = matcher.find_longest_match(0, stt_len, 0, len(old_m))
        longest_ratio = longest_match.size / stt_len
        
        if longest_match.size >= min_longest_size and (coverage >= cov_threshold or longest_ratio >= longest_threshold):
            LAST_ECHO_FILTERED_TTS_ID = CURRENT_TTS_ID
            MP3_ECHO_TRAILING_CHUNKS = 0
            log_print(f"🔇 [7L 喇叭回音過濾] 判定為 7L 自身發話喇叭回音 (覆蓋率 {coverage:.2f}, 長度比 {longest_ratio:.2f}): 「{stt_text}」 ➔ 已安全過濾 (僅過濾一次，後續解鎖放行)！")
            return True

    return False

def is_computer_audio_echo(stt_text: str) -> bool:
    """ Windows 系統內部音訊 WASAPI Loopback 實時鑑別：
    精準識別電腦正在播放的影片、他人語音、遊戲音效或背景音樂，不誤觸發老爸指令。
    """
    global current_system_audio_context
    clean_stt = normalize_text_for_echo(stt_text)
    if not clean_stt:
        return False
        
    if LATEST_SYSTEM_AUDIO_RMS > 0.008 and RECENT_SYSTEM_AUDIO_TRANSCRIPTS:
        now = time.time()
        recent_sys_texts = [normalize_text_for_echo(txt) for t_stamp, txt in RECENT_SYSTEM_AUDIO_TRANSCRIPTS if (now - t_stamp) < 8.0 and txt]
        combined_sys = "".join(recent_sys_texts)
        
        if combined_sys:
            if clean_stt in combined_sys or any(clean_stt in t for t in recent_sys_texts):
                log_print(f"🎧 [電腦音訊識別] 識別為電腦內部音訊: 「{stt_text}」 ➔ 記入環境音情報，不誤觸發老爸指令！")
                current_system_audio_context = f"電腦正在播放音訊/影片：『{stt_text}』"
                return True
                
            for sys_m in recent_sys_texts:
                if not sys_m: continue
                matcher = difflib.SequenceMatcher(None, clean_stt, sys_m)
                match_sum = sum(b.size for b in matcher.get_matching_blocks())
                coverage = match_sum / len(clean_stt)
                if coverage >= 0.50:
                    log_print(f"🎧 [電腦音訊識別] 識別為電腦內部音訊（覆蓋率 {coverage:.2f}）: 「{stt_text}」 ➔ 記入環境音情報，不誤觸發老爸指令！")
                    current_system_audio_context = f"電腦正在播放音訊/影片：『{stt_text}』"
                    return True

    return False

# ────────────────────────────────────────────────────────
#  10. 語音合成、音訊分析與字幕工具
# ────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────
#  預編譯高頻正則表達式與統一文字淨化引擎 (TextCleanEngine)
# ────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────
#  核心 Prompt 範本工廠與動態指令建造器 (PromptTemplateEngine)
# ────────────────────────────────────────────────────────

def _remove_temp_mp3():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for p in [base_dir, os.path.join(base_dir, "GPT-SoVITS")]:
            for f in glob.glob(os.path.join(p, "temp_reply_*.mp3")):
                try: os.remove(f)
                except Exception: pass
    except Exception:
        pass

def strip_all_emojis(text: str) -> str:
    """徹底清除所有 Unicode Emoji 圖示與表情符號（包括各類符號、裝飾符、音樂符號等）"""
    return TextCleanEngine.strip_emojis(text)

def update_subtitle(text):
    try:
        clean_s = TextCleanEngine.strip_emojis(text)
        if not clean_s:
            wrapped_text = ""
        else:
            lines = clean_s.replace("\r\n", "\n").split("\n")
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

CURRENT_PLAYING_VOICE_TASK = None
SPEECH_PLAYBACK_LOCK = asyncio.Lock()

async def interrupt_current_speech(clear_queue: bool = True, reason: str = "7L 自主插話/中斷"):
    """ 即時中斷 7L 當前正在播出的語音（支援自己插話自己、老爸秒級打斷與即時清空排隊）"""
    global IS_MP3_PLAYING, MP3_ECHO_TRAILING_CHUNKS
    try:
        # 1. 清空舊的排隊語音
        if clear_queue:
            cleared_cnt = 0
            while not speech_queue.empty():
                try:
                    speech_queue.get_nowait()
                    speech_queue.task_done()
                    cleared_cnt += 1
                except Exception:
                    break
            if cleared_cnt > 0:
                log_print(f"🧹 [排隊清空] 已清理 {cleared_cnt} 條舊的排隊語音，讓位給最新發言！")

        # 2. 取消當前正在執行的語音播放協程
        if CURRENT_PLAYING_VOICE_TASK and not CURRENT_PLAYING_VOICE_TASK.done():
            CURRENT_PLAYING_VOICE_TASK.cancel()
            
        # 3. 立即強制停止底層 pygame 音訊播放
        try:
            if pygame.mixer.get_init():
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                try:
                    pygame.mixer.Channel(5).stop()
                except Exception:
                    pass
        except Exception:
            pass

        IS_MP3_PLAYING = False
        MP3_ECHO_TRAILING_CHUNKS = 1
        await asyncio.to_thread(update_subtitle, "")
        log_print(f"⚡ [{reason}] 已秒級中斷前一句語音，無縫切換開口說新句子！")
    except Exception as e:
        log_print(f"⚠️ [中斷語音異常]: {e}")

# ────────────────────────────────────────────────────────
#  12.5 Live API 即時神態導演與句中動態表情時間軸排程引擎
# ────────────────────────────────────────────────────────
def parse_action_timeline(raw_text: str, total_duration: float) -> list:
    """從原始模型回覆字串中，按字元進度精確計算每個表情/動作標籤在語音播放期間的觸發時間點。
    支援句中隨時切換表情（例如上半句 [EXPRESSION: 生氣]，下半句 [EXPRESSION: 臉紅]）。
    回傳: [(fire_time_sec, action_type, action_val), ...]
    """
    if not raw_text:
        return []

    clean_raw = re.sub(r'\[THOUGHT:[^\]]*\]', '', raw_text, flags=re.IGNORECASE).strip()
    tag_pattern = re.compile(
        r'\[(EXPRESSION|MOVE|LOOK|SPATIAL|POSITION|WINDOW|WINK|FROWN|SHOCK|眨眼|皺眉|震驚)(?:[：:]\s*([^\]]*))?\]',
        re.IGNORECASE
    )

    tags_with_pos = []
    for m in tag_pattern.finditer(clean_raw):
        raw_type = m.group(1).upper()
        tag_val = m.group(2).strip() if m.group(2) else ''

        if raw_type in ['SPATIAL', 'POSITION', 'WINDOW']:
            tag_type = 'MOVE'
        elif raw_type in ['WINK', '眨眼']:
            tag_type = 'WINK'
            tag_val = ''
        elif raw_type in ['FROWN', '皺眉']:
            tag_type = 'EXPRESSION'
            tag_val = '皺眉'
        elif raw_type in ['SHOCK', '震驚']:
            tag_type = 'EXPRESSION'
            tag_val = '震驚'
        else:
            tag_type = raw_type

        tags_with_pos.append((m.start(), tag_type, tag_val))

    clean_spoken = tag_pattern.sub('', clean_raw).strip()
    clean_spoken = re.sub(r'\[[A-Z_]+[：:][^\]]*\]', '', clean_spoken).strip()
    total_chars = max(1, len(clean_spoken))

    timeline = []
    for start_idx, tag_type, tag_val in tags_with_pos:
        prefix = clean_raw[:start_idx]
        prefix_clean = tag_pattern.sub('', prefix)
        prefix_clean = re.sub(r'\[[A-Z_]+[：:][^\]]*\]', '', prefix_clean).strip()
        char_offset = len(prefix_clean)
        ratio = min(1.0, max(0.0, char_offset / total_chars))
        fire_time = round(ratio * total_duration, 2)
        timeline.append((fire_time, tag_type, tag_val))

    timeline.sort(key=lambda x: x[0])
    return timeline


async def live_api_direct_sentence_emotions(clean_text: str, total_duration: float) -> list:
    """ 【Live API 即時潛意識神態導演】：
    利用 Live API 無限額度與亞秒級低延遲，為發話句子實時感知情感流動，
    精確策劃上半句與下半句的動態表情切換時間點（上半句一個表情、下半句隨時可換）！
    回傳: [(timestamp_float, "EXPRESSION"|"WINK"|"MOVE", tag_value), ...]
    """
    if not clean_text or total_duration < 1.8 or len(clean_text.strip()) < 6:
        return []

    candidate_keys = get_dynamic_live_key_candidates(KEYS_AUDIENCE_LIVE if KEYS_AUDIENCE_LIVE else GEMINI_KEYS)
    for idx, g_key in enumerate(candidate_keys[:3]):
        try:
            client = genai.Client(api_key=g_key)
            live_cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=types.Content(parts=[types.Part(text="""妳是虛擬主播 7L 的即時神態導演（Live API Emotion Director）。
分析 7L 即將發出的語音句子與總秒數，給出這句話中「上半句」與「下半句」的動態表情切換時間點（不限每句只能一種，上半句與下半句隨時可變！）。
可選表情與動作：臉紅, 生氣, 愛心, 星星眼, 皺眉, 震驚, 傲嬌, 委屈, WINK, 正常, 眨眼。
輸出格式（每行一個，秒數從小到大，秒數不可超過總秒數）：
[0.0s: 表情名]
[秒數: 表情名]
嚴禁輸出任何廢話或分析，只輸出時間戳標籤！""")])
            )
            async with asyncio.timeout(2.5):
                async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
                    await session.send_realtime_input(text=f"7L 正在發話：「{clean_text.strip()}」（語音總時長 {total_duration:.1f} 秒）")
                    output_text = ""
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            if c.output_transcription and c.output_transcription.text:
                                output_text += c.output_transcription.text
                            if c.turn_complete or getattr(c, 'generation_complete', False):
                                break

                    parsed_timeline = []
                    for line in output_text.splitlines():
                        m = re.search(r'\[\s*([0-9.]+)\s*s?\s*[：:]\s*([^\]]+)\]', line)
                        if m:
                            f_sec = float(m.group(1))
                            act_val = m.group(2).strip()
                            if f_sec <= total_duration + 0.5:
                                if any(w in act_val.upper() for w in ["WINK", "眨眼", "單眼"]):
                                    parsed_timeline.append((f_sec, "WINK", ""))
                                else:
                                    parsed_timeline.append((f_sec, "EXPRESSION", act_val))

                    if parsed_timeline:
                        log_print(f"⚡ [Live API 神態導演] 成功策劃句中動態表情流: {parsed_timeline}")
                        return parsed_timeline
        except Exception:
            continue

    return []


async def execute_action_timeline(vts, timeline: list, cancel_event: asyncio.Event = None):
    """ 語音時間軸動態表情與動作執行器：
    隨語音發音進度精確在毫秒級時間點觸發表情轉換，實現上半句到下半句想換就換的生動神態！
    """
    
    if not timeline or not vts:
        return
    start_t = time.time()
    for fire_time, action_type, action_val in sorted(timeline, key=lambda x: x[0]):
        if cancel_event and cancel_event.is_set():
            break
        now_offset = time.time() - start_t
        delay = fire_time - now_offset
        if delay > 0:
            try:
                if cancel_event:
                    await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                    break
                else:
                    await asyncio.sleep(delay)
            except asyncio.TimeoutError:
                pass

        if cancel_event and cancel_event.is_set():
            break

        try:
            if action_type == "EXPRESSION":
                log_print(f"🎭 [句中即時換表情 ({fire_time:.1f}s)]: 切換至「{action_val}」")
                await set_vts_expression(vts, action_val)
            elif action_type == "WINK":
                log_print(f"😉 [句中即時動作 ({fire_time:.1f}s)]: 眨眼 WINK")
                await vc.trigger_wink()
            elif action_type == "MOVE":
                log_print(f"🚶 [句中即時走位 ({fire_time:.1f}s)]: 移動至「{action_val}」")
                await apply_spatial_position(action_val)
            elif action_type == "LOOK":
                u_act = action_val.upper()
                if "ROLL" in u_act:
                    await vc.trigger_eye_roll()
                elif "MOUSE" in u_act:
                    await vc.set_tracking_mouse(True)
                elif "LEFT" in u_act:
                    await vc.set_target_look(-25.0, 0.0)
                elif "RIGHT" in u_act:
                    await vc.set_target_look(25.0, 0.0)
                elif "UP" in u_act:
                    await vc.set_target_look(0.0, 20.0)
                elif "DOWN" in u_act:
                    await vc.set_target_look(0.0, -20.0)
                elif "CENTER" in u_act:
                    await vc.set_target_look(0.0, 0.0)
        except Exception as e:
            log_print(f"⚠️ [即時時間軸執行異常]: {e}")


async def play_voice_complete(text, target: str = "dad", raw_actions_text: str = "", vts=None):
    global current_ai_state, LAST_TTS_END_TIME, IS_MP3_PLAYING, MP3_ECHO_TRAILING_CHUNKS, CURRENT_SPEAKING_TARGET
    if not text: return

    async with SPEECH_PLAYBACK_LOCK:
        CURRENT_SPEAKING_TARGET = target
        record_bot_message(text)
        try:
            web_dash.broadcast_event("ai_speech", {"text": text, "target": target})
        except Exception:
            pass

        target_vts = vts or vc.GLOBAL_VTS

        try:
            _remove_temp_mp3()
            base_proj_dir = os.path.dirname(os.path.abspath(__file__))
            output_file = os.path.join(base_proj_dir, f"temp_reply_{int(time.time() * 1000)}_{random.randint(100, 999)}.mp3")
            
            #  語音合成前置解析：動態語速與音高切塊處理 (Chunking)
            source_text = raw_actions_text if (raw_actions_text and ('[SPEED:' in raw_actions_text.upper() or '[PITCH:' in raw_actions_text.upper())) else text
            _, source_text = TextCleanEngine.extract_thought(source_text)
            source_text = TextCleanEngine.RE_CODE_BLOCKS.sub('', source_text)
            source_text = TextCleanEngine.RE_INLINE_CODE.sub('', source_text)
            source_text = TextCleanEngine.RE_PYTHON_CALLS.sub('', source_text)
            pattern = re.compile(r'(\[(?:SPEED|PITCH):[^\]]+\])', re.IGNORECASE)
            parts = pattern.split(source_text)
            
            chunks = []
            current_rate = "+0%"
            current_pitch = "+0Hz"
            re_hangul = re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]')
            
            for p in parts:
                if not p: continue
                speed_match = re.match(r'\[SPEED:([+-]?\d*(?:\.\d+)?(?:x|%|倍)?)\]', p, re.IGNORECASE)
                if speed_match:
                    val = speed_match.group(1).strip().lower()
                    try:
                        if val.endswith('x') or val.endswith('倍') or ('.' in val and not val.endswith('%')):
                            # 倍速模式：如 1.0x, 1x, 1.2x, 0.8x, 1倍, 1.5倍
                            mult = float(re.sub(r'[^\d.]', '', val))
                            percent_diff = (mult - 1.0) * 100
                            scaled = int(percent_diff * 0.45)
                        elif val.endswith('%') and int(re.sub(r'[^\d\-+]', '', val)) in (100,):
                            # 100% 表示原速
                            scaled = 0
                        else:
                            num = int(re.sub(r'[^\d\-+]', '', val))
                            #  柔化自然縮放：將激進的語速縮放至人聲舒適黃金區間 (-12% ~ +12%)，杜絕怪聲與快轉機械感
                            scaled = int(num * 0.45)
                        clamped = max(-12, min(12, scaled))
                        current_rate = f"{'+' if clamped >= 0 else ''}{clamped}%"
                    except Exception:
                        current_rate = "+0%"
                    continue
                    
                pitch_match = re.match(r'\[PITCH:([+-]?\d+(?:\.\d+)?(?:Hz|%)?)\]', p, re.IGNORECASE)
                if pitch_match:
                    val = pitch_match.group(1)
                    try:
                        num = int(re.sub(r'[^\d\-+]', '', val))
                        #  柔化自然縮放：將音高變化縮放至 (-5Hz ~ +5Hz)，防止小依女聲尖銳刺耳或變花栗鼠卡通音
                        scaled = int(num * 0.3)
                        clamped = max(-5, min(5, scaled))
                        current_pitch = f"{'+' if clamped >= 0 else ''}{clamped}Hz"
                    except Exception:
                        current_pitch = "+0Hz"
                    continue
                    
                clean_p = TextCleanEngine.clean_for_tts(p, apply_phonetics=True)
                if clean_p.strip() and re.search(r'[\u4e00-\u9fa5a-zA-Z0-9\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]', clean_p):
                    #  智能句子分段演算法：按標點將長句子拆分為自然獨立子句，實現分段邊生成邊播（秒開口）
                    def _split_sub_sentences(raw_t: str):
                        pat = r'([^。！？!?；;\n，,]+[。！？!?；;\n，,]*)'
                        matches = re.findall(pat, raw_t.strip())
                        toks = [m.strip() for m in matches if m.strip()]
                        if not toks: return [raw_t] if raw_t else []
                        subs = []
                        buf = ''
                        for tk in toks:
                            buf += tk
                            is_strong = bool(re.search(r'[。！？!?；;\n]$', buf))
                            is_comma = bool(re.search(r'[，,]$', buf))
                            c_len = len(re.sub(r'[^\w\u4e00-\u9fa5]', '', buf))
                            # 強標點且 >= 8 字才切，或逗號累積 >= 20 字才切
                            #  提高門檻：減少碎句拆分，降低分段拼接的停頓感
                            if (is_strong and c_len >= 8) or (is_comma and c_len >= 20):
                                subs.append(buf)
                                buf = ''
                        if buf:
                            if subs: subs[-1] += buf
                            else: subs.append(buf)
                        return subs

                    sub_sentences = _split_sub_sentences(clean_p)
                    for sub_s in sub_sentences:
                        if sub_s.strip() and re.search(r'[\u4e00-\u9fa5a-zA-Z0-9\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]', sub_s):
                            chunks.append({"text": sub_s, "voice": "local_xiaoyi", "rate": current_rate, "pitch": current_pitch})
                    
            if not chunks:
                return
                
            tts_text = "".join(c["text"] for c in chunks)
            est_duration = max(1.5, len(tts_text) * 0.22)
            pre_timeline = parse_action_timeline(raw_actions_text, est_duration) if raw_actions_text else []

            #  若 7L 正在唱歌，等待演唱完畢後再播話，絕不打斷歌聲 (防禦上限 60s)！
            singing_wait_start = time.time()
            while (IS_SINGING_ACTIVE or current_ai_state == "SINGING") and (time.time() - singing_wait_start < 60.0):
                await asyncio.sleep(0.5)

            #  若當前正在播放觸電即時叫聲，等待叫聲播放完畢再接著說話 (至多等 2 秒防卡死)
            shock_wait_start = time.time()
            while IS_SHOCK_SCREAMING and (time.time() - shock_wait_start < 2.0):
                await asyncio.sleep(0.05)

            try:
                if pygame.mixer.music.get_busy() and not IS_SINGING_ACTIVE:
                    pygame.mixer.music.stop()
            except Exception: pass

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100)

            #  啟動背景神態導演（若句子夠長且無預設時間軸）
            director_task = None
            if len(pre_timeline) < 2 and len(tts_text) >= 7 and target_vts:
                director_task = asyncio.create_task(live_api_direct_sentence_emotions(tts_text, est_duration))

            #  異步生產者-消費者隊列（分段邊生成邊播核心架構）
            audio_stream_queue = asyncio.Queue()
            temp_files_to_clean = []

            async def tts_producer_worker():
                """背景 Worker A：依序合成各分段音訊，第一段一好立刻 push 進隊列"""
                try:
                    import services.tts_router as tts_router
                    for idx, c_dict in enumerate(chunks):
                        try:
                            t0 = time.time()
                            local_wav = await tts_router.get_tts_audio_bytes(c_dict["text"])
                            if local_wav and len(local_wav) > 100:
                                cost = time.time() - t0
                                _eng = tts_router.get_active_engine() or "kokoro"
                                part_file = os.path.join(base_proj_dir, f"temp_reply_{int(time.time()*1000)}_{random.randint(100,999)}_part{idx}{tts_router.file_extension(_eng)}")
                                with open(part_file, "wb") as pf:
                                    pf.write(bytes(local_wav))
                                    pf.flush()
                                temp_files_to_clean.append(part_file)
                                log_print(f"🟢 【串流分段 TTS({_eng}) ⚡ 第 {idx+1}/{len(chunks)} 句秒出】: '{c_dict['text']}' (耗時:{cost:.2f}s)")
                                await audio_stream_queue.put({"file": part_file, "text": c_dict["text"], "idx": idx, "total": len(chunks)})
                            else:
                                log_print(f"⚠️ 【TTS 回傳為空】'{c_dict['text']}'")
                        except Exception as e:
                            log_print(f"❌ 【分段音訊合成異常】: {e}")
                finally:
                    await audio_stream_queue.put(None)  # 結束標誌

            producer_task = asyncio.create_task(tts_producer_worker())

            #  播放與對嘴主迴圈（消費者）
            global CURRENT_MOUTH_ENVELOPE, CURRENT_SPEECH_START_TIME, CURRENT_SMOOTH_MOUTH
            #  注意：第一段音訊生成完畢並開始播放前，絕不提前開啟 TALKING / IS_MP3_PLAYING，杜絕發聲前嘴巴空動
            timeline_cancel_event = asyncio.Event()
            timeline_task = None
            total_actual_spoken_time = 0.0

            try:
                # 初始更新字幕
                await asyncio.to_thread(update_subtitle, text)
                first_chunk = True

                while True:
                    item = await audio_stream_queue.get()
                    if item is None:
                        break

                    part_file = item["file"]
                    try:
                        snd = pygame.mixer.Sound(part_file)
                        part_dur = snd.get_length()
                        part_env = extract_audio_mouth_envelope(snd, fps=25)
                        del snd
                    except Exception:
                        part_dur = max(0.5, len(item["text"]) * 0.22)
                        part_env = []

                    CURRENT_MOUTH_ENVELOPE = part_env
                    CURRENT_SMOOTH_MOUTH = 0.0
                    CURRENT_SPEECH_START_TIME = time.time()
                    current_ai_state = "TALKING"
                    IS_MP3_PLAYING = True

                    # 若第一句剛開始播，掛載神態時間軸
                    if first_chunk:
                        first_chunk = False
                        if len(pre_timeline) >= 2:
                            final_tl = parse_action_timeline(raw_actions_text, est_duration)
                            if target_vts:
                                timeline_task = asyncio.create_task(execute_action_timeline(target_vts, final_tl, timeline_cancel_event))
                        elif director_task and not director_task.done():
                            async def _attach_live_timeline():
                                try:
                                    live_tl = await asyncio.wait_for(asyncio.shield(director_task), timeout=2.0)
                                    if live_tl and target_vts and not timeline_cancel_event.is_set():
                                        asyncio.create_task(execute_action_timeline(target_vts, live_tl, timeline_cancel_event))
                                except Exception: pass
                            asyncio.create_task(_attach_live_timeline())

                    #  無縫播放：使用 Sound Channel + queue() 消除分段拼接停頓感
                    # 首段直接播，後續段等待前段結束前 0.1s 預先 queue 進去
                    try:
                        snd_obj = pygame.mixer.Sound(part_file)
                        ch = pygame.mixer.find_channel(True)
                        if ch is None:
                            ch = pygame.mixer.Channel(0)
                        if ch.get_busy():
                            ch.queue(snd_obj)
                            # 等待 channel 完成前段，再切換 envelope（避免口型亂跳）
                            while ch.get_queue() is not None or ch.get_busy():
                                await asyncio.sleep(0.02)
                        else:
                            ch.play(snd_obj)
                            await asyncio.sleep(0.02)
                            while ch.get_busy() or ch.get_queue() is not None:
                                await asyncio.sleep(0.02)
                    except Exception:
                        # fallback: 舊版 music 模式
                        pygame.mixer.music.load(part_file)
                        pygame.mixer.music.set_volume(1.0)
                        pygame.mixer.music.play()
                        await asyncio.sleep(0.05)
                        while pygame.mixer.music.get_busy():
                            await asyncio.sleep(0.04)

                    total_actual_spoken_time += part_dur
                    CURRENT_MOUTH_ENVELOPE = []
                    CURRENT_SMOOTH_MOUTH = 0.0

            finally:
                if timeline_cancel_event:
                    timeline_cancel_event.set()
                if timeline_task and not timeline_task.done():
                    timeline_task.cancel()
                if producer_task and not producer_task.done():
                    producer_task.cancel()
                if director_task and not director_task.done():
                    director_task.cancel()

                pygame.mixer.stop()
                try: pygame.mixer.music.unload()
                except Exception: pass

                # 清理所有分段臨時音訊檔案
                for tf in temp_files_to_clean:
                    try:
                        if os.path.exists(tf): os.remove(tf)
                    except Exception: pass

                # 清除口型波形狀態
                if not IS_SINGING_ACTIVE and current_ai_state != "SINGING":
                    CURRENT_MOUTH_ENVELOPE = []
                    CURRENT_SMOOTH_MOUTH = 0.0
                    CURRENT_SPEECH_START_TIME = 0.0
                    IS_MP3_PLAYING = False

                MP3_ECHO_TRAILING_CHUNKS = 1
                LAST_TTS_END_TIME = time.time()
                if current_ai_state == "TALKING":
                    current_ai_state = "IDLE"

                if pe.is_piano_active and pe.current_piano_song_title:
                    await asyncio.to_thread(update_subtitle, f" [7L 正在演奏鋼琴] 《{pe.current_piano_song_title}》")
                else:
                    await asyncio.to_thread(update_subtitle, "")

        except asyncio.CancelledError:
            try: pygame.mixer.music.stop()
            except Exception: pass
            try: pygame.mixer.music.unload()
            except Exception: pass
            if 'temp_files_to_clean' in locals():
                for tf in temp_files_to_clean:
                    try:
                        if os.path.exists(tf): os.remove(tf)
                    except Exception: pass
            if 'timeline_cancel_event' in locals() and timeline_cancel_event:
                timeline_cancel_event.set()
            if 'timeline_task' in locals() and timeline_task and not timeline_task.done():
                timeline_task.cancel()
            if 'producer_task' in locals() and producer_task and not producer_task.done():
                producer_task.cancel()
            if 'director_task' in locals() and director_task and not director_task.done():
                director_task.cancel()
            IS_MP3_PLAYING = False
            MP3_ECHO_TRAILING_CHUNKS = 1
            LAST_TTS_END_TIME = time.time()
            if current_ai_state == "TALKING": current_ai_state = "IDLE"
            raise
        except Exception as e:
            log_print(f"❌ [語音合成錯誤]: {e}")
            try: pygame.mixer.music.stop()
            except Exception: pass
            try: pygame.mixer.music.unload()
            except Exception: pass
            try:
                if 'output_file' in locals() and os.path.exists(output_file):
                    os.remove(output_file)
            except Exception: pass
            if 'timeline_cancel_event' in locals() and timeline_cancel_event:
                timeline_cancel_event.set()
            if 'timeline_task' in locals() and timeline_task and not timeline_task.done():
                timeline_task.cancel()
            IS_MP3_PLAYING = False
            MP3_ECHO_TRAILING_CHUNKS = 1
            LAST_TTS_END_TIME = time.time()
            if current_ai_state == "TALKING": current_ai_state = "IDLE"

async def play_instant_sound_clip(audio_path: str, subtitle: str = ""):
    """ 0 秒極速播放 7L 專屬觸電尖叫聲（即時對嘴 + 臉紅），後續對話無縫接軌"""
    global CURRENT_MOUTH_ENVELOPE, CURRENT_SPEECH_START_TIME, CURRENT_SMOOTH_MOUTH
    global current_ai_state, IS_MP3_PLAYING, IS_SHOCK_SCREAMING
    
    if not audio_path or not os.path.exists(audio_path):
        log_print(f"⚠️ [即時音訊警告]: 找不到音訊檔案: {audio_path}")
        IS_SHOCK_SCREAMING = False
        return

    IS_SHOCK_SCREAMING = True
    try:
        if subtitle:
            await asyncio.to_thread(update_subtitle, subtitle)
            
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100)

        # 逐幀分析音訊包絡，帶動 7L VTS 模型即時張嘴叫喊！
        snd = None
        try:
            snd = pygame.mixer.Sound(audio_path)
            CURRENT_MOUTH_ENVELOPE = extract_audio_mouth_envelope(snd, fps=25)
            CURRENT_SMOOTH_MOUTH = 0.0
        except Exception as e:
            log_print(f"⚠️ [即時尖叫包絡異常]: {e}")
            CURRENT_MOUTH_ENVELOPE = []
            CURRENT_SMOOTH_MOUTH = 0.0

        current_ai_state = "TALKING"
        IS_MP3_PLAYING = True
        CURRENT_SPEECH_START_TIME = time.time()
        
        #  採用專屬 SFX 獨立通道 (Channel 5)，音量拉滿，絕不與 TTS 語音串流 (pygame.mixer.music) 衝突打架！
        channel = pygame.mixer.Channel(5)
        channel.set_volume(1.0)
        if snd:
            channel.play(snd)
            await asyncio.sleep(0.06)
            while channel.get_busy():
                await asyncio.sleep(0.03)
        else:
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.set_volume(1.0)
            pygame.mixer.music.play()
            await asyncio.sleep(0.12)
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.04)

        if channel.get_busy():
            channel.stop()
    except Exception as e:
        log_print(f"⚠️ [即時尖叫音效異常]: {e}")
    finally:
        CURRENT_MOUTH_ENVELOPE = []
        CURRENT_SMOOTH_MOUTH = 0.0
        CURRENT_SPEECH_START_TIME = 0.0
        IS_SHOCK_SCREAMING = False
        IS_MP3_PLAYING = False
        if current_ai_state == "TALKING":
            current_ai_state = "IDLE"
        log_print("⚡ [即時尖叫完畢] 觸電叫聲播放結束，無縫移交大腦後續即時回應！")

def capture_system_audio_chunk(duration: float = 2.5):
    """從 Windows 預設播放裝置 (WASAPI Loopback) 記憶體內截取電腦內部播放音訊與音量"""
    try:
        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        num_frames = int(16000 * duration)
        with mic.recorder(samplerate=16000) as recorder:
            data = recorder.record(numframes=num_frames)
            
        rms = float(np.sqrt(np.mean(np.square(data))))
        if rms < 0.005:
            return None, rms
            
        if len(data.shape) > 1 and data.shape[1] > 1:
            data_mono = np.mean(data, axis=1)
        else:
            data_mono = data.flatten()
            
        audio_int16 = (np.clip(data_mono, -1.0, 1.0) * 32767).astype(np.int16)
        
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_int16.tobytes())
            
        return buf.getvalue(), rms
    except Exception:
        return None, 0.0

def transcribe_audio_bytes(wav_bytes: bytes) -> str:
    """PROVIDER: GOOGLE-WEB-SPEECH 為主＋LOCAL faster-whisper 為備（services/stt；見 docs/AI_SOURCES.md）
    記憶體內極速語音辨識 (STT）"""
    if not wav_bytes:
        return ""
    try:
        from services.stt import transcribe_wav
        return transcribe_wav(wav_bytes)
    except Exception:
        return ""

async def gemini_system_audio_live_transcribe(wav_bytes: bytes) -> str:
    """使用獨立的 Gemini Live API 專門監聽電腦桌面聲音（精準過濾純音樂，零幻覺），具備自動故障轉移機制"""
    if not wav_bytes or not GEMINI_KEYS:
        return ""
    
    from google import genai
    from google.genai import types
    import asyncio
    
    # 取得候補金鑰清單
    candidates = KEYS_AUDIENCE_LIVE + [k for k in GEMINI_KEYS if k not in KEYS_AUDIENCE_LIVE]
    if not candidates:
        return ""
        
    for api_key in candidates[:4]:  # 最多嘗試 4 把不同的金鑰
        try:
            live_client = genai.Client(api_key=api_key)
            live_cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO], 
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Aoede"
                        )
                    )
                ),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=types.Content(parts=[types.Part.from_text(text="你是一個專門過濾音訊的AI。請聆聽音訊，如果有人講話，請『只』輸出他們的對話文字。絕對不要加上任何自己的分析、解釋或思考過程！如果音訊是純音樂、無人聲或雜音，請直接輸出 [SILENCE] 四個字，不要說其他話。千萬不要幻覺出任何字幕或版權浮水印。")])
            )
            
            # Gemini Live API 嚴格要求 PCM 格式，去除 WAV 檔頭 (44 bytes)
            pcm_bytes = wav_bytes[44:] if wav_bytes.startswith(b'RIFF') else wav_bytes
            
            live_transcription = ""
            async with asyncio.timeout(10.0):
                async with live_client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
                    chunk_sz = 8000
                    for offset in range(0, len(pcm_bytes), chunk_sz):
                        chunk = pcm_bytes[offset:offset+chunk_sz]
                        await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))
                        
                    await session.send_realtime_input(text="（音訊已傳送完畢，請立刻輸出轉錄文字，或輸出 [SILENCE]）")
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                    
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            if c.output_transcription and c.output_transcription.text:
                                live_transcription += c.output_transcription.text
                            if c.model_turn and c.model_turn.parts:
                                for p in c.model_turn.parts:
                                    if p.text:
                                        live_transcription += p.text
                            if getattr(c, 'turn_complete', False) or getattr(c, 'generation_complete', False):
                                break
                                
            final_text = live_transcription.strip()
            # 過濾 AI 的內心戲或靜默標籤
            upper_text = final_text.upper()
            if "[SILENCE]" in upper_text or "SILENCE" in upper_text or "NOTHING" in upper_text or "REMAIN SILENT" in upper_text:
                return ""
                
            return final_text
            
        except Exception as e:
            # 發生 429 資源耗盡或斷線，自動進入下一迴圈，換下一把金鑰繼續試
            log_print(f"⚠️ [電腦內錄 Live API] 金鑰(...{api_key[-6:]}) 失敗，自動切換下一把... ({repr(e)})")
            continue
            
    return ""

# ────────────────────────────────────────────────────────
#  11. 視覺感知、畫面截圖與輕量眼角餘光
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

_DXCAM_CAM = None
_DXCAM_FAILED = False
PREV_SCREEN_THUMB = None

def get_dxcam_cam():
    global _DXCAM_CAM, _DXCAM_FAILED
    if _DXCAM_FAILED:
        return None
    if _DXCAM_CAM is not None:
        return _DXCAM_CAM
    try:
        import dxcam
        _DXCAM_CAM = dxcam.create(output_color="RGB")
        return _DXCAM_CAM
    except Exception:
        _DXCAM_FAILED = True
        return None

def capture_screen_multi_view():
    """
    五方多視角超高清螢幕感知系統 (DXGI GPU 加速 + 硬件級 StretchBlt 極速引擎)：
    1.  全螢幕全景總覽圖 (含原生真實滑鼠游標貼圖)
    2.  左上象限原生細節放大圖 (Top-Left)
    3.  右上象限原生細節放大圖 (Top-Right)
    4.  左下象限原生細節放大圖 (Bottom-Left)
    5.  右下象限原生細節放大圖 (Bottom-Right)
    """
    global has_printed_vision_error
    try:
        from PIL import ImageDraw, Image
        import io
        
        screenshot = None
        
        # 1. 優先嘗試 DXGI 顯存直出 (若遊戲反作弊未阻擋，僅耗 1~3ms)
        cam = get_dxcam_cam()
        if cam is not None:
            try:
                frame = cam.grab()
                if frame is not None:
                    screenshot = Image.fromarray(frame)
            except Exception:
                pass
                
        # 2. 高效 GDI 硬件級 BitBlt 引擎 (耗時僅 ~15ms，零縮放失真，真實 1:1 4K 像素)
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

        if screenshot is None:
            return None

        if screenshot.mode != "RGB":
            screenshot = screenshot.convert("RGB")
            
        w, h = screenshot.size
        #  自然貼合原生真實滑鼠游標圖標 (原寸 1:1 座標對齊)
        cursor_icon = get_realistic_cursor_icon()
        if cursor_icon:
            try:
                mx_raw, my_raw = pyautogui.position()
                screenshot.paste(cursor_icon, (max(0, min(w - 1, mx_raw)), max(0, min(h - 1, my_raw))), cursor_icon)
            except Exception:
                pass
        
        #  儲存原生 100% 超高清原圖快取 (品質 92，供燈箱放大檢視與老爸查核，文字極致清晰)
        global LATEST_HD_SCREEN_BYTES
        buf_hd = io.BytesIO()
        screenshot.save(buf_hd, format="JPEG", quality=92, optimize=True)
        LATEST_HD_SCREEN_BYTES = buf_hd.getvalue()

        # 同步儲存至 data/last_vision_frame.jpg 供控制台秒開
        try:
            cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "last_vision_frame.jpg")
            with open(cache_file, "wb") as f_c:
                f_c.write(LATEST_HD_SCREEN_BYTES)
        except Exception:
            pass

        #  即時計算真實畫面動態差分 (全螢幕縮圖均勻採樣，耗時僅約 1.5ms)
        global PREV_SCREEN_THUMB, CURRENT_VISION_CHANGE_LEVEL, CURRENT_VISION_CHANGE_SCORE
        try:
            from PIL import ImageChops, ImageStat
            curr_thumb = screenshot.resize((64, 36), Image.Resampling.BILINEAR)
            if PREV_SCREEN_THUMB is not None:
                diff = ImageChops.difference(curr_thumb, PREV_SCREEN_THUMB)
                stat = ImageStat.Stat(diff)
                raw_diff = sum(stat.mean) / (3.0 * 255.0) * 100.0  # 0.0 ~ 100.0%
                if raw_diff < 0.01:
                    CURRENT_VISION_CHANGE_LEVEL = "none"
                    CURRENT_VISION_CHANGE_SCORE = 0
                elif raw_diff < 0.2:
                    CURRENT_VISION_CHANGE_LEVEL = "low"
                    CURRENT_VISION_CHANGE_SCORE = max(5, min(25, int(raw_diff * 100)))
                elif raw_diff < 2.0:
                    CURRENT_VISION_CHANGE_LEVEL = "med"
                    CURRENT_VISION_CHANGE_SCORE = min(65, int(25 + raw_diff * 20))
                else:
                    CURRENT_VISION_CHANGE_LEVEL = "high"
                    CURRENT_VISION_CHANGE_SCORE = min(100, int(65 + raw_diff * 2))
            PREV_SCREEN_THUMB = curr_thumb
        except Exception:
            pass

        # 1. 全螢幕全景總覽圖 (高畫質 Lanczos 縮圖至 1920 寬度，品質 88，兼顧 Gemini 思考速度與全景清晰度)
        buf_full = io.BytesIO()
        if w > 1920:
            overview_im = screenshot.resize((1920, int(h * 1920 / w)), Image.Resampling.LANCZOS)
            overview_im.save(buf_full, format="JPEG", quality=88)
        else:
            screenshot.save(buf_full, format="JPEG", quality=88)
        full_b64 = base64.b64encode(buf_full.getvalue()).decode('utf-8')
        
        # 2. 四個象限細節裁切 (直接從 4K 原生全尺寸精準裁切，100% 原始像素細節，程式碼文字無任何毛邊)
        mid_x = w // 2
        mid_y = h // 2
        
        # 左上象限
        buf_tl = io.BytesIO()
        screenshot.crop((0, 0, mid_x, mid_y)).save(buf_tl, format="JPEG", quality=88)
        tl_b64 = base64.b64encode(buf_tl.getvalue()).decode('utf-8')
        
        # 右上象限
        buf_tr = io.BytesIO()
        screenshot.crop((mid_x, 0, w, mid_y)).save(buf_tr, format="JPEG", quality=88)
        tr_b64 = base64.b64encode(buf_tr.getvalue()).decode('utf-8')
        
        # 左下象限
        buf_bl = io.BytesIO()
        screenshot.crop((0, mid_y, mid_x, h)).save(buf_bl, format="JPEG", quality=88)
        bl_b64 = base64.b64encode(buf_bl.getvalue()).decode('utf-8')
        
        # 右下象限
        buf_br = io.BytesIO()
        screenshot.crop((mid_x, mid_y, w, h)).save(buf_br, format="JPEG", quality=88)
        br_b64 = base64.b64encode(buf_br.getvalue()).decode('utf-8')
        
        has_printed_vision_error = False
        return [
            ("【1. 全螢幕全景總覽（含滑鼠游標）】", full_b64),
            ("【2. 左上角細節放大圖】", tl_b64),
            ("【3. 右上角細節放大圖】", tr_b64),
            ("【4. 左下角細節放大圖】", bl_b64),
            ("【5. 右下角細節放大圖】", br_b64)
        ]
    except Exception as e:
        if not has_printed_vision_error:
            print(f"\n❌ [截圖系統報錯]: {e}")
            has_printed_vision_error = True
        return None

def capture_screen_as_base64():
    return capture_screen_multi_view()

def get_combined_temporal_screen_snapshot():
    """
     組合 5 圖多視角 + 最近時序連續動態影格（共 6~7 張圖）
     核心效果：
       1. 包含前 1~2 幀歷史全景截圖（時序動態感知：Gemini 清楚分辨動畫、角色位移、戰鬥、視窗滾動等連續動作）
       2. 包含此刻當前完整 5 圖多視角（1 全景總覽 + 4 象限超高清局部放大，100% 原始像素細節，徹底杜絕看不清楚）
       3. 實測 7 圖總體積僅約 80~130 KB，Gemini 響應僅耗時 1.7~2.3 秒，完全在黃金無感延遲區！
    """
    
    if not latest_screen_cache:
        return None
    if not isinstance(latest_screen_cache, list):
        return latest_screen_cache
    
    combined = []
    # 1. 注入歷史時序動態幀 (依時間先後：較舊 ➔ 較新)
    for idx, (t_stamp, hist_b64) in enumerate(SCREEN_TEMPORAL_HISTORY):
        dt = round(time.time() - t_stamp, 1)
        combined.append((f"【時序動態幀 {idx+1} (約 {dt} 秒前歷史畫面)】", hist_b64))
        
    # 2. 注入當前最新 5 圖多視角（此刻全景總覽 + 4 象限局部放大圖）
    combined.extend(latest_screen_cache)
    return combined

async def check_screen_change_via_live_api(img_bytes: bytes, current_context: str) -> bool:
    """ 【Live API 餘光視覺哨兵】：
    利用 Live API 無限額度特性保持雙眼實時看著螢幕畫面，
    絕不輸出冗長描述，只負責極速判定畫面是否有重大全新變化/新事件/新視窗 ([NO_CHANGE] vs [LOOK_SERIOUS])，
    徹底替老爸節省 3.1-flash-lite 主力發話金鑰額度！
    """
    if not img_bytes or len(img_bytes) < 1000:
        return False
        
    candidate_keys = get_dynamic_live_key_candidates(KEYS_VISION if KEYS_VISION else GEMINI_KEYS)
    for idx, g_key in enumerate(candidate_keys[:4]):
        client = genai.Client(api_key=g_key)
        try:
            live_cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=types.Content(parts=[types.Part(text="""妳是 7L 的背景餘光視覺神經哨兵。
妳正透過雙眼看著老爸的電腦螢幕畫面。
妳的任務是保持眼睛在看，但【絕對不要輸出任何描述或聊天內容】！
妳只負責做極速二元決策：
- [NO_CHANGE]：若畫面維持在先前的操作中（如持續寫程式碼、同一個視窗/軟體中微調打字、滑鼠移動、無重大新動態），請【只輸出】: [NO_CHANGE]
- [LOOK_SERIOUS]：只有當發生重大改變（如切換到完全不同的應用程式、跳出報錯或提示視窗、開啟新遊戲/影片、完成重大部署/編譯、畫面焦點徹底改變）時，才輸出: [LOOK_SERIOUS]
嚴禁輸出任何多餘的解釋或對話，只輸出 [NO_CHANGE] 或 [LOOK_SERIOUS]！""")]),
            )
            async with asyncio.timeout(3.8):
                async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
                    await session.send_realtime_input(video={"data": img_bytes, "mime_type": "image/jpeg"})
                    eval_prompt = f"前次已知畫面狀態：『{current_context}』。請看當前畫面，是否有出現重大新事件需要認真看？只輸出 [NO_CHANGE] 或 [LOOK_SERIOUS]："
                    await session.send_realtime_input(text=eval_prompt)
                    
                    decision_text = ""
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            if c.output_transcription and c.output_transcription.text:
                                decision_text += c.output_transcription.text
                            if c.turn_complete or getattr(c, 'generation_complete', False):
                                break
                                
                    decision_clean = decision_text.strip().upper()
                    if "[LOOK_SERIOUS]" in decision_clean or "LOOK_SERIOUS" in decision_clean:
                        return True
                    if "[NO_CHANGE]" in decision_clean or "NO_CHANGE" in decision_clean or "[SILENCE]" in decision_clean:
                        return False
        except Exception:
            continue
    return False






# ────────────────────────────────────────────────────────
#  12. 旗艦多模態大腦推理核心 (fetch_ai_response)
# ────────────────────────────────────────────────────────
#  功能目的：
#    - 7L 與老爸私下對話、深度探索與工具執行的全模態旗艦推理核心。
#    - 支援文字、5 視角全螢幕畫面影像（Base64 JPEG）、原生音訊（WAV）。
#    - 採用智能任務分流（3.1 Flash Lite ➔ 3.5 Flash Lite ➔ 3 Flash ➔ 3.1 Pro ➔ 3.5 ➔ 3.6 ➔ 3.7）。
#    - 雙軌搶答競速與自動降級（Failover），並在成功後立即調用工具或執行 Live2D 動作。


# ────────────────────────────────────────────────────────
#  13. 使用者指令、電腦控制與計時器動作
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

async def set_timer(seconds: int, message: str, target_queue: Optional[asyncio.Queue] = None):
    """設定定時感測提醒 (已全面升級至 API Live 定時感測中樞)"""
    live_timer_hub.add_timer(seconds, message, source="代碼指令/標籤")
    try:
        web_dash.broadcast_event("timer_added", live_timer_hub.get_sensor_summary())
    except Exception:
        pass

async def live_timer_sensor_worker(vts, input_queue):
    """ API Live 持續時間感測哨兵協程：
    - 以 1 秒 (1 Tick) 精度全時感測倒數時間與老爸當前狀態
    - 時間到達時自動喚醒主力多模態大腦 (Gemini 3.8 / 3.1 Flash) 生成專屬生動提醒並主動開口發言
    """
    log_print("⏱️ [API Live 時間感測哨兵] 協程已就緒，開始全時任務與倒數感測...")
    while True:
        try:
            await asyncio.sleep(1.0)
            now = time.time()
            
            # 遍歷所有進行中的定時感測任務
            for tid, task in list(live_timer_hub.timers.items()):
                if task.get("status") != "sensing":
                    continue
                    
                rem = task["target_time"] - now
                if rem <= 0:
                    task["status"] = "triggered"
                    task_msg = task.get("message", "提醒老爸")
                    caller = task.get("caller_user", "老爸")
                    log_print(f"⏰ [API Live 定時感測到期] 任務 {tid}（{task_msg}）到期！正在呼叫主力大腦生成自然提醒口語...")
                    
                    del live_timer_hub.timers[tid]
                    
                    # 取得當前環境多模態上下文
                    curr_fg_title = ""
                    curr_fg_app = ""
                    try:
                        from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
                        fg_info = os_desktop_sensor.get_foreground_window()
                        curr_fg_title = fg_info.get("window_title", "").strip()
                        curr_fg_app = fg_info.get("app_label", "").strip()
                    except Exception:
                        pass
                        
                    fg_hint = f"（老爸當前正在使用視窗：{curr_fg_title} - {curr_fg_app}）" if curr_fg_title else ""
                    music_hint = f"（電腦音樂：{LATEST_SYSTEM_MUSIC_INFO}）" if LATEST_SYSTEM_MUSIC_INFO else ""
                    
                    reminder_messages = [
                        {"role": "system", "content": PromptTemplateEngine.HARD_TECHNICAL_RULES},
                        {"role": "user", "content": f"""時間：{get_current_time_string()}
【 API Live 定時感測到期提醒】：
老爸剛才交代妳的時間提醒到了！
- 預定提醒事項：『{task_msg}』
- 當前現場環境：{fg_hint} {music_hint}

請妳依循妳的人設性格，主動開口提醒老爸時間到了！（直接給出一兩句自然生動的發言，可附帶 [EXPRESSION: 瞇眼/笑/WINK] 表情與 [SPEED:...] 語調標籤，嚴禁輸出 [SILENCE]！）"""}
                    ]
                    
                    try:
                        raw_reply = await fetch_ai_response(reminder_messages, is_proactive=True)
                        spoken = await execute_actions(vts, raw_reply, input_queue, caller_target="dad", caller_user=caller)
                        clean_spoken = spoken.strip(" *'\"-.,!?。，！？\n\r") if spoken else ""
                        
                        if not clean_spoken:
                            clean_spoken = f"老爸～剛才說好的「{task_msg}」時間到了喔！快起來休息一下～"
                            
                        await asyncio.to_thread(update_subtitle, clean_spoken)
                        record_bot_message(clean_spoken)
                        log_print(f"💬 7L (定時感測主動提醒): {clean_spoken}")
                        await speech_queue.put({"text": clean_spoken, "target": "dad", "raw_text": raw_reply})
                        touch_interaction()
                        
                        append_to_unified_memory(speaker="7L", target=caller, content=clean_spoken, role="assistant", source="tts")
                        try:
                            web_dash.broadcast_event("timer_triggered", {
                                "task_id": tid,
                                "message": task_msg,
                                "spoken": clean_spoken
                            })
                        except Exception:
                            pass
                    except Exception as err:
                        log_print(f"❌ [定時感測喚醒模型發言異常]: {err}")
                        fallback_msg = f"老爸！時間到囉～剛才說好的「{task_msg}」要記得喔！"
                        await asyncio.to_thread(update_subtitle, fallback_msg)
                        await speech_queue.put({"text": fallback_msg, "target": "dad"})
                        touch_interaction()
        except Exception as e:
            log_print(f"⚠️ [API Live 時間感測協程異常]: {e}")
            await asyncio.sleep(1.0)

async def execute_speech_visual_actions(vts, text: str):
    """ 語音同步專用 Live2D 演出控制器：
    精準在語音【真正開口發話播放】的瞬間觸發本句專屬的表情、走位、眨眼、視線與身體動作，
    杜絕連續說話時下一句還在排隊、動作卻提前偷跑的脫節問題！
    """
    
    if not text:
        return
        
    exp_match = re.search(r'\[EXPRESSION:\s*([^\]]+)\]', text, re.IGNORECASE)
    if exp_match:
        exp_tag = exp_match.group(1).strip()
        if any(k in exp_tag.upper() for k in ["WINK", "眨眼", "單眼", "眨單眼"]):
            asyncio.create_task(vc.trigger_wink())
            log_print("😉 [Live2D 動作] 標籤觸發 Wink 單眼眨一下眼")
        elif any(k in exp_tag for k in ["驚訝", "惊讶", "驚", "惊", "震驚", "震惊", "瞳孔", "嚇到", "SHOCK", "SURPRISE"]):
            asyncio.create_task(vc.trigger_shock())
            log_print("😱 [Live2D 動作] 標籤觸發驚訝縮瞳與瞪大雙眼微顫")
        elif any(k in exp_tag for k in ["皺眉", "皱眉", "八字眉", "困擾", "困扰", "委屈", "傲嬌皺眉", "難過眉", "生氣皺眉", "FROWN"]):
            asyncio.create_task(vc.trigger_frown())
            log_print("🥺 [Live2D 動作] 標籤觸發八字皺眉/委屈表情")
        else:
            log_print(f"🎭 [Live2D 表情] 標籤觸發表情: 「{exp_tag}」")
            asyncio.create_task(set_vts_expression(vts, exp_tag))

    move_match = re.search(r'\[(?:MOVE|SPATIAL|WINDOW|POSITION)[：:]\s*([^\]]+)\]', text, re.IGNORECASE)
    if move_match:
        pos_tag = move_match.group(1).strip()
        if not pe.is_piano_active or any(k in pos_tag for k in ["鋼琴", "原本", "大小", "視窗"]):
            log_print(f"🚶 [Live2D 走位] 標籤觸發模型移動至: 「{pos_tag}」")
            asyncio.create_task(apply_spatial_position(pos_tag))

    try:
        upper_text = text.upper()
        if "WINK" in upper_text and not exp_match:
            asyncio.create_task(vc.trigger_wink())
            log_print("😉 [Live2D 動作] 動作觸發 Wink 單眼眨一下眼")
        elif any(k in upper_text for k in ["SHOCK", "SHOCKED", "SURPRISE", "PUPIL", "驚訝", "惊讶", "震驚", "震惊", "瞳孔", "嚇到"]) and not exp_match:
            asyncio.create_task(vc.trigger_shock())
            log_print("😱 [Live2D 動作] 動作觸發驚訝縮瞳與瞪大雙眼微顫")
        elif any(k in upper_text for k in ["FROWN", "FROWNING", "皺眉", "皱眉", "八字眉", "困擾", "委屈"]) and not exp_match:
            asyncio.create_task(vc.trigger_frown())
            log_print("🥺 [Live2D 動作] 動作觸發八字皺眉/委屈神態")
        elif any(k in upper_text for k in ["ROLL", "AROUND", "WANDER", "轉眼", "環視"]):
            asyncio.create_task(vc.trigger_eye_roll())
            log_print("🌀 [Live2D 動作] 動作觸發招牌靈動轉眼珠環視四周")
        elif "MOUSE" in upper_text and "LOOK" in upper_text:
            asyncio.create_task(vc.set_tracking_mouse(True))
            log_print("👀 [Live2D 視線] 視線切換為鎖定追蹤滑鼠游標")
        elif "LEFT" in upper_text and "LOOK" in upper_text:
            asyncio.create_task(vc.set_target_look(-25.0, 0.0))
            log_print("👀 [Live2D 視線] 視線轉向【左邊】")
        elif "RIGHT" in upper_text and "LOOK" in upper_text:
            asyncio.create_task(vc.set_target_look(25.0, 0.0))
            log_print("👀 [Live2D 視線] 視線轉向【右邊】")
        elif "UP" in upper_text and "LOOK" in upper_text:
            asyncio.create_task(vc.set_target_look(0.0, 25.0))
            log_print("👀 [Live2D 視線] 視線轉向【上方】")
        elif "DOWN" in upper_text and "LOOK" in upper_text:
            asyncio.create_task(vc.set_target_look(0.0, -25.0))
            log_print("👀 [Live2D 視線] 視線轉向【下方】")
        elif "CENTER" in upper_text and "LOOK" in upper_text:
            asyncio.create_task(vc.set_target_look(0.0, 0.0))
            log_print("👀 [Live2D 視線] 視線回正【正前方】")

        if "EARS" in upper_text:
            vc.force_blink_trigger = 1
            log_print("🐰 [Live2D 動作] 動作觸發耳朵抖動/眨眼")
    except Exception:
        pass

async def execute_actions(vts, text, input_queue, user_input_ctx: str = "", has_dispatched_tool: bool = False, execute_visuals: bool = False, caller_target: str = "", caller_user: str = ""):
    """集中式系統動作與指令過濾器 (即刻執行底層系統動作/工具，並產出口語純淨文字)"""
    
    
    #  徹底去除開頭與內部殘留之 LLM 內部 token (如 get_output, tool_output 等)
    text = re.sub(r'^(?:get_outputs?|tool_outputs?|function_calls?|tool_responses?)[：:\s_]*', '', text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r'\b(?:get_outputs?|tool_outputs?)\b', '', text, flags=re.IGNORECASE).strip()

    #  提取並過濾殘留心想/思考內容 (已有背景即時心流協程，對話不再輸出或記錄腦內心想)
    extracted_thought, text_without_thought = TextCleanEngine.extract_thought(text)
    if extracted_thought:
        text = text_without_thought

    if bool(re.search(r'\[HAD_TOOL_CALL\]', text, re.IGNORECASE)):
        has_dispatched_tool = True

    #  7L 自主雲端大腦演進標籤攔截 [UPDATE_PROMPT: ...] / [ADD_EXAMPLE: ...] / [LEARN_MEME: ...] / [LEARN_FACT: ...] / [UPDATE_RULE: ...]
    for up in re.finditer(r'\[(?:UPDATE_PROMPT|UPDATE_KNOWLEDGE|SET_PROMPT)[：:]\s*([^|\]]+)\|([^\]]+)\]', text, re.IGNORECASE):
        f_name = up.group(1).strip()
        f_val = up.group(2).strip()
        if f_name and f_val:
            asyncio.create_task(update_cloud_prompt_field(f_name, f_val))
            text = text.replace(up.group(0), "")

    for ae in re.finditer(r'\[(?:ADD_EXAMPLE|LEARN_EXAMPLE)[：:]\s*([^|\]]+)\|([^|\]]+)\|([^|\]]+)\|([^\]]+)\]', text, re.IGNORECASE):
        sc = ae.group(1).strip()
        ui = ae.group(2).strip()
        th = ae.group(3).strip()
        rp = ae.group(4).strip()
        if sc and rp:
            asyncio.create_task(add_few_shot_example(sc, ui, th, rp))
            text = text.replace(ae.group(0), "")

    for lm in re.finditer(r'\[LEARN_MEME[：:]\s*([^\]]+)\]', text, re.IGNORECASE):
        meme_val = lm.group(1).strip()
        if meme_val:
            asyncio.create_task(learn_new_meme(meme_val))
            text = text.replace(lm.group(0), "")

    for lf in re.finditer(r'\[LEARN_FACT[：:]\s*([^\]]+)\]', text, re.IGNORECASE):
        fact_val = lf.group(1).strip()
        if fact_val:
            asyncio.create_task(learn_new_fact(fact_val))
            text = text.replace(lf.group(0), "")

    for lr in re.finditer(r'\[(?:UPDATE_RULE|SET_RULE|LEARN_RULE)[：:]\s*([^\]]+)\]', text, re.IGNORECASE):
        rule_val = lr.group(1).strip()
        if rule_val:
            asyncio.create_task(update_custom_rule(rule_val))
            text = text.replace(lr.group(0), "")

    for tm in re.finditer(r'\[(?:TIMER|SET_TIMER|ALARM|鬧鐘|計時器)[：:]\s*([0-9]+)\s*\|?\s*([^\]]*)\]', text, re.IGNORECASE):
        t_sec = int(tm.group(1))
        t_msg = tm.group(2).strip() or "計時時間到"
        log_print(f"⏱️ [計時器啟動] 設定 {t_sec} 秒後提醒: 「{t_msg}」")
        asyncio.create_task(set_timer(t_sec, t_msg, input_queue))
        text = text.replace(tm.group(0), "")

    #  檢測 7L 自我插話標籤 [INTERRUPT_SELF] / [CUT_IN] / [插話] / [中斷]
    if bool(re.search(r'\[(?:INTERRUPT_SELF|CUT_IN|INTERRUPT|SELF_INTERRUPT|插話|中斷|打斷自己)\]', text, re.IGNORECASE)):
        log_print("⚡ [7L 自我插話] 檢測到 [INTERRUPT_SELF] 標籤，立即秒級打斷當前正在說的話！")
        asyncio.create_task(interrupt_current_speech(clear_queue=True, reason="7L 自由意志自我插話"))

    #  記住 VTS 模型基準位置與大小 (當老爸說「記住大小」、「記住位置」時即刻執行)
    if any(k in text or k in user_input_ctx for k in ["記住大小", "記住位置", "記住現在位置", "記住當前位置", "記住現在大小", "記錄位置", "記錄大小", "記住模型位置", "記住模型", "記錄基準大小", "記錄基準位置", "記住當前大小"]):
        log_print("📐 [VTS 模型記憶] 正在向 VTube Studio 讀取並保存當前模型座標與大小為基準...")
        asyncio.create_task(vc.fetch_vts_base_model_pos(vc.GLOBAL_VTS))

    #  翻唱手動終止指令 (當老爸或觀眾說「別唱了」、「停止唱歌」、「不要唱了」時即刻終止)
    if any(k in text or k in user_input_ctx for k in ["別唱了", "停止唱歌", "不要唱了", "別唱歌了", "停唱", "停止翻唱", "關閉音樂", "不要唱歌"]):
        stop_singing()
        log_print("🛑 [翻唱終止] 收到停止唱歌指令，已立即中斷演唱！")

    #  通用 Python 函數直接調用攔截 (Universal Python Call Interceptor)
    universal_tool_calls = [
        (r'(?:\[SPEED:[^\]]+\]\s*)?(?:pe\.)?set_piano_speed\(\s*(?:speed\s*=\s*)?[\'"]?([0-9.]+)x?[\'"]?\s*\)', lambda m: pe.set_piano_speed(speed=float(m.group(1)))),
        (r'(?:pe\.)?set_piano_volume\(\s*(?:volume\s*=\s*)?[\'"]?([0-9]+)[\'"]?\s*\)', lambda m: pe.set_piano_volume(volume=int(m.group(1)))),
        (r'(?:pe\.)?set_piano_instrument\(\s*(?:instrument\s*=\s*)?[\'"]([^\'"]+)[\'"]\s*\)', lambda m: pe.set_piano_instrument(instrument=m.group(1))),
        (r'(?:pe\.)?open_virtual_piano\(\s*\)', lambda m: pe.open_virtual_piano()),
        (r'(?:pe\.)?pause_virtual_piano\(\s*\)', lambda m: pe.pause_virtual_piano()),
        (r'(?:pe\.)?resume_virtual_piano\(\s*\)', lambda m: pe.resume_virtual_piano()),
        (r'(?:pe\.)?stop_virtual_piano\(\s*\)', lambda m: pe.stop_virtual_piano()),
        (r'(?:pe\.)?list_piano_sheets\(\s*\)', lambda m: pe.list_piano_sheets()),
        (r'\[?(?:stop_singing|stop_singing_song|stop_cover)(?:\(\s*\))?\]?', lambda m: stop_singing()),
        (r'\[(?:STOP_SINGING|STOP_COVER|停止唱歌|停止翻唱)\]', lambda m: stop_singing()),
        (r'\[?(?:auto_sing_song|sing_song)\(\s*(?:song_name\s*=\s*)?[\'"]?([^\'")\]]+)[\'"]?(?:[^)]*)\)\]?', lambda m: produce_and_sing_cover(re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', m.group(1)).strip().rstrip('\'"'))),
        (r'\[(?:AUTO_SING_SONG|SING_SONG|AUTO_SING|SING|翻唱|唱歌)[：:]\s*([^\]]+)\]', lambda m: produce_and_sing_cover(re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', m.group(1)).strip().rstrip('\'"'))),
        (r'\[(?:PLAY_PIANO|PLAY_VIRTUAL_PIANO|彈琴|點歌)[：:]\s*([^\]]+)\]', lambda m: pe.play_virtual_piano(
            song_name=m.group(1).strip(),
            target=(caller_target or ("audience" if CURRENT_SPEAKING_TARGET == "audience" else "dad")),
            requester_name=(caller_user or ("老爸" if (caller_target == "dad" or CURRENT_SPEAKING_TARGET != "audience") else "大家")),
            is_direct_song_name=True
        )),
        (r'\[?(?:pe\.)?play_virtual_piano\s*\([^)]*\)\]?', lambda m: pe.play_virtual_piano(
            song_name=(
                re.search(r'song_name\s*=\s*[\'"]?([^\'",)]+)[\'"]?', m.group(0)).group(1) 
                if re.search(r'song_name\s*=\s*[\'"]?([^\'",)]+)[\'"]?', m.group(0)) 
                else (re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0))[0] if re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0)) else "鋼琴曲")
            ), 
            force_online=bool(re.search(r'force_online\s*=\s*True', m.group(0), re.I)), 
            target=(caller_target or ("audience" if CURRENT_SPEAKING_TARGET == "audience" else "dad")),
            requester_name=(caller_user or ("老爸" if (caller_target == "dad" or CURRENT_SPEAKING_TARGET != "audience") else "大家")),
            is_direct_song_name=True
        )),
        (r'(?:pe\.)?compose_and_play_original_piano\((?:[^)]*)\)', lambda m: pe.compose_and_play_original_piano(
            theme_or_title=(re.search(r'(?:theme_or_title|theme|title)\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)).group(1) if re.search(r'(?:theme_or_title|theme|title)\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)) else ""), 
            mood_or_style=(re.search(r'(?:mood_or_style|mood|style)\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)).group(1) if re.search(r'(?:mood_or_style|mood|style)\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)) else ""), 
            target=(caller_target or ("audience" if CURRENT_SPEAKING_TARGET == "audience" else "dad")),
            requester_name=(caller_user or ("老爸" if (caller_target == "dad" or CURRENT_SPEAKING_TARGET != "audience") else "大家"))
        )),
        (r'(?:pe\.)?mashup_virtual_piano\((?:[^)]*)\)', lambda m: pe.mashup_virtual_piano(*(re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0))))),
        (r'(?:pe\.)?insert_virtual_piano\(\s*(?:song_name\s*=\s*)?[\'"]([^\'"]+)[\'"](?:[^)]*)\)', lambda m: pe.insert_virtual_piano(song_name=m.group(1))),
        (r'(?:generate_ai_image|draw_illustration)\(\s*(?:prompt\s*=\s*)?[\'"]([^\'"]+)[\'"]\s*\)', lambda m: generate_ai_image(m.group(1))),
        (r'execute_local_python_code\(\s*(?:code_string\s*=\s*)?[\'"]([^\'"]+)[\'"]\s*\)', lambda m: execute_local_python_code(m.group(1))),
        (r'move_spatial_position\(\s*(?:target_position\s*=\s*|position_name\s*=\s*)?[\'"]([^\'"]+)[\'"](?:[^)]*)\)', lambda m: apply_spatial_position(m.group(1))),
        (r'trigger_vts_expression\(\s*(?:expression_name\s*=\s*)?[\'"]([^\'"]+)[\'"]\s*\)', lambda m: set_vts_expression(vts, m.group(1))),
        (r'control_microphone\(\s*(?:is_enabled\s*=\s*)?(True|False)\s*\)', lambda m: control_microphone(m.group(1).lower() == 'true')),
        (r'clear_all_memories\(\s*\)', lambda m: clear_all_memories()),
        (r'(?:pe\.)?set_timer\((?:[^)]*)\)', lambda m: set_timer(
            int(re.search(r'\b(\d+)\b', m.group(0)).group(1)) if re.search(r'\b(\d+)\b', m.group(0)) else 60,
            (re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0))[0] if re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0)) else "鬧鐘時間到"),
            input_queue
        )),
        (r'search_google\(\s*(?:query\s*=\s*)?[\'"]([^\'"]+)[\'"]\s*\)', lambda m: asyncio.to_thread(search_google, m.group(1))),
        (r'update_cloud_knowledge\((?:[^)]*)\)', lambda m: update_cloud_prompt_field(
            (re.search(r'category\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)).group(1) if re.search(r'category\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)) else "facts"),
            (re.search(r'content\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)).group(1) if re.search(r'content\s*=\s*[\'"]([^\'"]+)[\'"]', m.group(0)) else (re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0))[-1] if re.findall(r'[\'"]([^\'"]+)[\'"]', m.group(0)) else ""))
        ))
    ]
    
    for pattern, func in universal_tool_calls:
        while True:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                break
            cmd_name = match.group(0).strip()
            log_print(f"🛠️ [通用指令攔截] 檢測到 Python 呼叫: {cmd_name}，立即自動執行！")
            
            # 登錄至 7L 工具調用即時紀錄
            t_raw_name = cmd_name.split('(')[0].split(':')[0].split('：')[0].replace('[', '').replace(']', '').replace('pe.', '').strip()
            t_name = f"pe.{t_raw_name}" if hasattr(pe, t_raw_name) else t_raw_name
            t_call_start = time.time()
            try:
                web_dash.record_tool_call(
                    tool_name=t_name,
                    args={"command": cmd_name},
                    result="已觸發執行",
                    caller="7L (大腦自主)",
                    status="success"
                )
            except Exception:
                pass

            async def _safe_run_intercepted_tool(coro, cmd_s, name_s, start_t):
                try:
                    res = None
                    if asyncio.iscoroutine(coro):
                        res = await coro
                    elif callable(coro):
                        res = coro()
                        if asyncio.iscoroutine(res):
                            res = await res
                    dur = (time.time() - start_t) * 1000
                    try:
                        web_dash.record_tool_call(name_s, {"command": cmd_s}, res or "執行成功", caller="7L (大腦自主)", status="success", duration_ms=dur)
                    except Exception:
                        pass
                except Exception as err:
                    log_print(f"❌ [通用指令執行異常]: {cmd_s} ➔ {err}")
                    dur = (time.time() - start_t) * 1000
                    try:
                        web_dash.record_tool_call(name_s, {"command": cmd_s}, None, caller="7L (大腦自主)", status="error", duration_ms=dur, error=str(err))
                    except Exception:
                        pass
            asyncio.create_task(_safe_run_intercepted_tool(func(match), cmd_name, t_name, t_call_start))
            has_dispatched_tool = True
            text = text.replace(match.group(0), "")

    url_match = re.search(r'\[OPEN_BROWSER:\s*([^\]]+)\]', text, re.IGNORECASE)
    if url_match:
        url = url_match.group(1).strip()
        if not url.startswith('http'):
            url = 'https://' + url
        try:
            webbrowser.open(url)
            log_print(f"🌐 [系統動作] 7L 幫你打開了網頁: {url}")
        except Exception as e:
            log_print(f"❌ [開啟網頁失敗]: {e}")

    # 若指定立即執行視覺動作 (例如安靜沉思不發聲時的微眼神/微表情)
    if execute_visuals:
        await execute_speech_visual_actions(vts, text)

    clean_text = TextCleanEngine.clean_speech_text(text)
    return clean_text

# ────────────────────────────────────────────────────────
#  14. 專屬背景工作協程群 (Workers)
# ────────────────────────────────────────────────────────

# ---  語音與收音協程 ---
is_user_listening = False
listen_start_time = 0.0

async def mic_volume_worker():
    global current_mic_volume_str, CURRENT_MIC_VOL_PERCENT
    
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
            current_mic_volume_str = "[ 麥克風已關閉]"
            CURRENT_MIC_VOL_PERCENT = 0
            await asyncio.sleep(0.3)
            continue

        # 🎙️ 全雙工真·不鎖麥：已有專屬聲紋辨識 (WeSpeaker/Voiceprint)，發話中依然保持全時收音監測與音量跳動
        if stream:
            try:
                frames_avail = stream.get_read_available()
                if frames_avail > 0:
                    data = stream.read(frames_avail, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    if len(audio_data) > 0:
                        rms = np.sqrt(np.mean(np.square(audio_data.astype(np.float32))))
                        vol_percent = min(100, int((rms / 2500) * 100))
                        CURRENT_MIC_VOL_PERCENT = vol_percent
                        bars = vol_percent // 10
                        bar_str = "█" * bars + "_" * (10 - bars)
                        current_mic_volume_str = f"[ 收音: {vol_percent:02d}% |{bar_str}|]"
                await asyncio.sleep(0.05) 
            except Exception:
                current_mic_volume_str = "[ 麥克風全時就緒]"
                CURRENT_MIC_VOL_PERCENT = 0
                await asyncio.sleep(0.5)
        else:
            current_mic_volume_str = "[ 麥克風全時就緒]"
            CURRENT_MIC_VOL_PERCENT = 0
            await asyncio.sleep(0.5)

def listen_once_fast(recognizer):
    global is_user_listening, listen_start_time, current_mic_action_str
    # PROVIDER: GOOGLE-WEB-SPEECH 快覽＋GEMINI-LIVE 深層語音理解（audio_b64；見 docs/AI_SOURCES.md）
    text = ""
    audio_b64 = None
    try:
        current_mic_action_str = "待命"
        with sr.Microphone() as source:
            is_user_listening = True
            listen_start_time = time.time()
            #  純 VAD 語音活動偵測：單次發話上限提高至 30 秒（支援環境變數 MIC_PHRASE_TIME_LIMIT），避免長句或中途思考被強制截斷
            phrase_limit = float(os.getenv("MIC_PHRASE_TIME_LIMIT", "30.0"))
            audio = recognizer.listen(source, timeout=None, phrase_time_limit=phrase_limit)
            
        is_user_listening = False
        current_mic_action_str = " 語音多模態分析中..."
        
        #  擷取完整原始 WAV 音訊資料與音量門檻檢驗
        try:
            raw_pcm = audio.get_raw_data()
            if raw_pcm:
                pcm_arr = np.frombuffer(raw_pcm, dtype=np.int16)
                if len(pcm_arr) > 0:
                    pcm_rms = float(np.sqrt(np.mean(np.square(pcm_arr.astype(np.float32)))))
                    min_rms = float(os.getenv("MIC_MIN_RMS_THRESHOLD", "250"))
                    if pcm_rms < min_rms:
                        # 音量低於閥值，判定為環境微弱雜訊或按鍵/呼吸聲，直接捨棄避免誤觸發
                        return ("", None)
            
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

def check_immediate_shutdown(text: str) -> bool:
    """毫秒級即時關機 / 重開機攔截：
    必須帶有 7L / 阿七 等明確目標前綴（如「7L關機」、「7L重開機」、「阿七關機」，
    並包含中文語音辨識 ASR 常見同音詞如「謝龍重開機」、「CL重開機」、「西L重開機」），
    或終端單獨輸入 exit / quit / reboot / restart，避免日常對話提及「關機」「重開」時誤觸。
    """
    if not text:
        return False
    
    clean = unicodedata.normalize('NFKC', str(text)).strip().lower()
    clean_compact = re.sub(r'[\s，。！？,.!?:;~～`\'"（）()\[\]【】\-_]+', '', clean)
    if not clean_compact:
        return False

    #  否定詞防護：若含有「不要 / 別 / 不能 / 請勿 / 取消」等否定詞，絕對不觸發關機或重開
    if any(neg in clean_compact for neg in ["不要", "別", "别", "不能", "請勿", "请勿", "取消"]):
        return False

    #  過去式疑問句防護：如「關機了嗎」、「重開機了嗎」
    if clean_compact.endswith("了嗎") or clean_compact.endswith("了吗"):
        return False

    #  目標判定：指名 7L / 7l / 七L / 阿七 / 小七 / 七妹，並加入中文語音常見同音詞 (謝龍 / CL / 西L 等)
    target_names = [
        "7l", "七l", "cl", "謝龍", "谢龙", "西l", "吸l", 
        "奇l", "琪l", "期l", "氣l", "切爾", "琪兒", 
        "阿七", "小七", "七妹", "7妹", "7哥", "七哥"
    ]
    has_target = any(name in clean_compact for name in target_names)

    #  即時重開機指令 (0.001s 安全硬中斷並自動重啟主程序)
    # 支援：7L重開機、謝龍重開機、CL重開機、7L重啟、阿七重開機，或終端純輸入 reboot / restart
    is_exact_restart = clean_compact in ["reboot", "restart", "7lreboot", "7lrestart"]
    restart_keywords = ["重開機", "重開", "重啟", "重新啟動", "重啟系統", "重新開機", "restart", "reboot"]
    has_restart_cmd = has_target and any(k in clean_compact for k in restart_keywords)

    if is_exact_restart or has_restart_cmd:
        log_print(f"🔄 [系統] 收到即時重開機指令「{text.strip()}」，正在重新啟動 7L 系統...")
        if pe.current_piano_process and pe.current_piano_process.poll() is None:
            try:
                pe.current_piano_process.terminate()
            except Exception:
                pass
        if pe.SOUND_ENGINE:
            pe.SOUND_ENGINE.all_notes_off()
        try:
            subprocess.Popen([sys.executable] + sys.argv)
        except Exception as e:
            log_print(f"⚠️ [重啟失敗]: {e}")
        os._exit(0)
        return True

    #  即時安全退出 / 關機指令 (0.001s 安全硬終止)
    # 支援：7L關機、謝龍關機、CL關機、7L強制關機、7L關閉系統、阿七關機，或終端純輸入 exit / quit / shutdown
    is_exact_shutdown = clean_compact in ["exit", "quit", "shutdown", "7lexit", "7lquit", "7lshutdown"]
    shutdown_keywords = [
        "關機", "強制關機", "強制關閉", "強制退出",
        "關閉系統", "退出系統", "結束程式", "關閉程式",
        "關閉7l", "關閉阿七", "系統休息", "安全退出", "安全關閉", "shutdown"
    ]
    has_shutdown_cmd = (
        (has_target and any(k in clean_compact for k in shutdown_keywords)) or
        (has_target and any(clean_compact.endswith(k) for k in ["退出", "關閉", "結束", "休眠"]))
    )

    if is_exact_shutdown or has_shutdown_cmd:
        log_print(f"👋 [系統] 收到即時關機指令「{text.strip()}」，正在安全退出...")
        if pe.current_piano_process and pe.current_piano_process.poll() is None:
            try:
                pe.current_piano_process.terminate()
            except Exception:
                pass
        if pe.SOUND_ENGINE:
            pe.SOUND_ENGINE.all_notes_off()
        os._exit(0)
        return True

    return False

async def mic_worker(recognizer, input_queue):
    global current_mic_action_str, LATEST_REALWORLD_SPEECH_TEXT, LATEST_REALWORLD_SPEECH_TIME
    
    #  麥克風音量閥值初始化：避免安靜環境下自動將 energy_threshold 調得過低
    try:
        min_energy = int(os.getenv("MIC_ENERGY_THRESHOLD", "600"))
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
        # 強制設定門檻下限，防止微弱底噪/呼吸/風扇聲誤觸發長時間收音
        recognizer.energy_threshold = max(min_energy, recognizer.energy_threshold)
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_adjustment_damping = 0.15
        recognizer.dynamic_energy_ratio = 1.5
        log_print(f"🎙️ [麥克風閥值就緒] 靈敏度門檻: {recognizer.energy_threshold:.0f} (最低下限: {min_energy})")
    except Exception as e:
        log_print(f"⚠️ [麥克風閥值] 初始化警告: {e}")

    while True:
        if not IS_MIC_ENABLED:
            current_mic_action_str = " 靜音"
            await asyncio.sleep(0.3)
            continue

        #  7x24 全雙工真·不關麥監聽：7L 發話或 MP3 播放中時麥克風依然暢通，由專屬聲紋鎖精準防禦回音並支援隨時插話打斷！
        try:
            listen_res = await asyncio.to_thread(lambda: listen_once_fast(recognizer))
            if isinstance(listen_res, tuple):
                user_text, audio_b64 = listen_res
            else:
                user_text, audio_b64 = str(listen_res), None

            cleaned_text = user_text.strip() if user_text else ""
            
            #  專屬老爸聲紋鎖與智慧插話系統：
            if cleaned_text:
                current_mic_action_str = f" 聽到:「{cleaned_text[:10]}...」"
                
                #  0. 7L 自身聲紋辨識防護 (用本地 TTS 特徵庫精準辨識 7L 自聲，主動忽略不予記錄)
                if audio_b64:
                    is_7l, score_7l = voiceprint_verifier.verify_is_7l(audio_b64, threshold=0.58)
                    if is_7l:
                        log_print(f"🔇 [7L 自聲防護] 辨識出為 7L 自己的聲音 (相似度: {score_7l:.2f} >= 0.58)，主動忽略不予記錄: 「{cleaned_text}」")
                        continue

                #  1. 毫秒級即時關機 / 重開機指令攔截 (最高優先權，支援 7L / 謝龍 / CL 等同音指令)
                if check_immediate_shutdown(cleaned_text):
                    continue

                #  2. 毫秒級聲紋特徵驗證：判定是否為老爸本人（徹底排除 7L 自身女聲、喇叭外放、電視雜音、旁人插嘴）
                is_dad, vp_score = voiceprint_verifier.verify_is_dad(audio_b64, threshold=0.70)
                if not is_dad:
                    # 若為 7L 自身喇叭回音，觸發專屬一次性回音過濾；若是其他雜音則聲紋攔截
                    if is_7l_voice_echo(cleaned_text, is_dad_verified=False):
                        continue
                    log_print(f"🔇 [聲紋攔截] 判定為非老爸聲音或雜音回音 (聲紋分: {vp_score:.2f} < 0.70)，自動過濾: 「{cleaned_text}」")
                    continue

                #  2. 7L 自身發話喇叭回音過濾（老爸本人聲紋保護：長度動態閾值，短句/指令不殺，一次性過濾）
                if is_7l_voice_echo(cleaned_text, is_dad_verified=is_dad):
                    continue

                #  3. 全雙工傾聽不打斷：保留 7L 完整發音說話或唱歌，絕不中斷，背景接收老爸輸入！
                is_currently_speaking = (current_ai_state in ["TALKING", "SINGING"]) or IS_SINGING_ACTIVE or IS_MP3_PLAYING or (pygame.mixer.get_init() and pygame.mixer.music.get_busy())
                if is_currently_speaking:
                    log_print(f"🎙️ [老爸語音接收] 聲紋確認 ({vp_score:.2f}) ➔ 7L 說話不中斷，背景接收老爸輸入！")

                #  4. 電腦內部聲音 (WASAPI Loopback 遊戲/影片) 輔助過濾
                if is_computer_audio_echo(cleaned_text):
                    continue
                
                saved_audio_path = save_local_audio_clip(audio_b64)
                LATEST_REALWORLD_SPEECH_TEXT = cleaned_text
                LATEST_REALWORLD_SPEECH_TIME = time.time()
                intercept_tag = " ( 立即打斷舊思考)" if current_ai_state == "THINKING" and not is_currently_speaking else ""
                log_print(f"📥 [老爸語音] 收到輸入: {cleaned_text} (聲紋: {vp_score:.2f}){intercept_tag}")
                await input_queue.put({"text": cleaned_text, "audio_base64": audio_b64, "audio_file": saved_audio_path, "timestamp": time.time(), "source": "mic"})
            else:
                current_mic_action_str = "待命 (聲紋鎖監聽)"
        except Exception:
            current_mic_action_str = "待命 (聲紋鎖監聽)"
            await asyncio.sleep(0.1)


async def text_file_listener_worker(input_queue, filename="chat_input.txt"):
    """監聽 chat_input.txt 本地文字輸入 (支援打字控制與指令快速直達，自動支援桌面、AI_Agents 及根目錄路徑)"""
    global current_mic_action_str
    
    candidate_paths = [
        filename,
        os.path.join("C:\\AI_Agents", "chat_input.txt"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "chat_input.txt"),
        os.path.join(os.path.expanduser("~"), "Desktop", "chat_input.txt"),
        "C:\\chat_input.txt"
    ]
    
    for p in candidate_paths:
        if not os.path.exists(p):
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception:
                pass

    while True:
        try:
            for p in candidate_paths:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    cleaned_content = content.strip()
                    if cleaned_content:
                        try:
                            with open(p, "w", encoding="utf-8") as f:
                                f.write("")
                        except Exception:
                            pass
                        
                        log_print(f"📥 [檔案打字接收] 收到輸入: {cleaned_content}")
                        if check_immediate_shutdown(cleaned_content):
                            return
                        current_mic_action_str = f" 打字:「{cleaned_content[:10]}...」"
                        await input_queue.put({"text": cleaned_content, "timestamp": time.time(), "source": "text_file"})
                        break
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
                await input_queue.put({"text": line, "timestamp": time.time(), "source": "console"})
        except Exception:
            await asyncio.sleep(0.1)

# ---  畫面與環境感知協程 ---
async def screen_capture_worker():
    global latest_screen_cache
    while True:
        if IS_SLEEPING or not IS_PERIPHERAL_VISION_ENABLED:
            await asyncio.sleep(2.0)
            continue
        try:
            new_views = await asyncio.to_thread(capture_screen_as_base64)
            if new_views:
                if latest_screen_cache and isinstance(latest_screen_cache, list) and len(latest_screen_cache) > 0:
                    SCREEN_TEMPORAL_HISTORY.append((time.time(), latest_screen_cache[0][1]))
                latest_screen_cache = new_views
        except Exception:
            pass
        await asyncio.sleep(1.8)

LAST_SCREEN_MD5_HASH = None
HAS_INITIAL_VISION_LOOK = False

async def peripheral_vision_worker():
    """ 【背景餘光雙層感知協程】：
    - 頂層哨兵：採用 Gemini Live API (3.8-live) 實時注視螢幕畫面（0 額度消耗、0 描述輸出），
      只極速判定 [NO_CHANGE] 還是 [LOOK_SERIOUS]。
    - 深度眼睛：唯有 Live 哨兵判定出現全新重大視窗/報錯/事件時，才喚醒 3.1-flash-lite 認真細看一次！
    - 徹底告別每 20 秒無謂消耗 3.1-flash-lite 說話額度的浪費行為。
    """
    global current_screen_context, LAST_SCREEN_MD5_HASH, HAS_INITIAL_VISION_LOOK, LAST_VISION_LOOK_TIME
    
    while True:
        await asyncio.sleep(15.0) 
        if IS_SLEEPING or not IS_PERIPHERAL_VISION_ENABLED:
            await asyncio.sleep(3.0)
            continue
        if current_ai_state in ["THINKING", "TALKING"]:
            continue
        if not latest_screen_cache: 
            continue
        
        if is_system_overloaded():
            continue

        try:
            sample_img = latest_screen_cache[0][1] if isinstance(latest_screen_cache, list) else latest_screen_cache
            if not sample_img:
                continue

            if isinstance(sample_img, str):
                img_bytes = base64.b64decode(sample_img)
            else:
                img_bytes = sample_img

            if len(img_bytes) < 1000:
                continue

            #  靜態畫面粗篩：畫面若完全靜止 (例如離開電腦、無任何操作)，0 網路直接略過
            if CURRENT_VISION_CHANGE_SCORE == 0 and HAS_INITIAL_VISION_LOOK:
                continue

            #  開機第一次：用 3.1-flash-lite 建立基準畫面感知
            if not HAS_INITIAL_VISION_LOOK or not current_screen_context or current_screen_context == "目前沒有特別的畫面動態。":
                log_print("👁️ [餘光視覺感知] 首次啟動 ➔ 啟動 3.1-flash-lite 建立基準畫面認知...")
                init_desc = await get_lightweight_gemini_vision(sample_img)
                if init_desc:
                    record_vision_history_entry(init_desc, "初次認知")
                    realtime_task_mgr.update_vision_context(current_screen_context)
                    HAS_INITIAL_VISION_LOOK = True
                    LAST_VISION_LOOK_TIME = time.time()
                continue

            #  日常餘光：由 Live API 哨兵保持注視，不輸出描述，只判定是否需認真看
            should_look = await check_screen_change_via_live_api(img_bytes, current_screen_context)
            if should_look:
                log_print("🚨 [餘光 Live 哨兵] 判定畫面出現值得關注的新動態！啟動 3.1-flash-lite 認真細看（含動態影格）...")
                #  收集上次認真看到現在之間的所有時序影格
                since_frames = [(t, b) for t, b in SCREEN_TEMPORAL_HISTORY if t >= LAST_VISION_LOOK_TIME]
                n_frames = len(since_frames)
                # 若幀數太多（>12 張），均勻採樣留 12 張，避免 token 爆炸
                if n_frames > 12:
                    step = n_frames // 12
                    since_frames = since_frames[::step][:12]
                log_print(f"🎞️ [動態視覺] 傳入 {len(since_frames)} 張歷史幀 (上次看到現在 {round(time.time() - LAST_VISION_LOOK_TIME, 1)}s)")
                detailed_desc = await get_lightweight_gemini_vision(sample_img, temporal_frames=since_frames)
                if detailed_desc:
                    record_vision_history_entry(detailed_desc, "畫面動態")
                    realtime_task_mgr.update_vision_context(current_screen_context)
                    LAST_VISION_LOOK_TIME = time.time()
        except Exception:
            pass

async def identify_system_music_and_sound(wav_bytes: bytes) -> str:
    """ 7L 智能電腦音樂與音效多模態感知中樞：
    當電腦播放音樂、歌曲、動漫OST或遊戲音效（無人聲語音）時，
    結合 10~11 秒長音訊、桌面視窗標題線索、畫面視覺線索與 Gemini 音訊感知模型，精準聽出具體曲名、作者或風格特徵。
    """
    global LAST_MUSIC_IDENTIFY_TIME, LATEST_SYSTEM_MUSIC_INFO, LATEST_SYSTEM_MUSIC_TIME, current_system_audio_context
    now = time.time()

    #  0. 若 7L 自身正在彈鋼琴或播放 MP3，電腦聲音即為 7L 自身聲音，直接同步當前鋼琴曲目，嚴禁調用 AI 瞎猜
    if (hasattr(pe, "is_piano_active_and_alive") and pe.is_piano_active_and_alive()) or getattr(pe, "is_piano_active", False) or current_ai_state == "PIANO":
        song_t = getattr(pe, "current_piano_song_title", "") or "鋼琴曲"
        current_system_audio_context = f"7L 正在為老爸演奏鋼琴：《{song_t}》"
        LATEST_SYSTEM_MUSIC_INFO = f"《{song_t}》"
        LATEST_SYSTEM_MUSIC_TIME = now
        realtime_task_mgr.update_audio_context(current_system_audio_context)
        return LATEST_SYSTEM_MUSIC_INFO

    if IS_MP3_PLAYING:
        return LATEST_SYSTEM_MUSIC_INFO

    if now - LAST_MUSIC_IDENTIFY_TIME < 15.0:
        return LATEST_SYSTEM_MUSIC_INFO
    LAST_MUSIC_IDENTIFY_TIME = now

    screen_clue = ""
    if current_screen_context and current_screen_context != "目前沒有特別的畫面動態。":
        screen_clue = current_screen_context.strip().replace("\n", " ")

    #  1. Windows 原生硬體級 GSMTC 媒體播放器底層情報提取 (嚴格排除已暫停或無視訊狀態)
    media_clues = []
    try:
        from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
        # 僅提取當前焦點操作視窗作為輔助線索（並嚴格標註可能處於暫停）
        fg = os_desktop_sensor.get_foreground_window()
        if fg and fg.get("window_title"):
            fg_title = fg["window_title"]
            fg_pname = fg.get("process_name", "")
            if any(k in fg_title.lower() or k in fg_pname.lower() for k in ["spotify", "music", "foobar", "potplayer", "vlc", "aimp"]):
                media_clues.append(f"焦點播放器視窗: [{fg_pname}] {fg_title} (注意：若未播放請勿採信)")
    except Exception:
        pass

    try:
        candidate_keys = get_dynamic_live_key_candidates(KEYS_VISION if KEYS_VISION else GEMINI_KEYS)
        if not candidate_keys:
            candidate_keys = GEMINI_KEYS
        
        target_key = candidate_keys[0] if candidate_keys else None
        if not target_key:
            return ""

        client = genai.Client(api_key=target_key)
        audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")

        prompt_text = (
            "妳是 7L 的全雙工聽覺與音樂感知神經。\n"
            "這是一段從老爸電腦喇叭內錄擷取的 10 秒真實即時音訊。\n"
            "【最高核心原則——以妳聽到的真實音訊旋律為 100% 唯一依據，絕不可瞎猜網頁標題】：\n"
            "1. 妳必須『親耳聽出音訊中的真實旋律、節奏與樂器』！\n"
            "2. 【嚴厲警惕背景未播放的分頁】：老爸經常在瀏覽器開著多個【處於暫停、未播放、靜音】的 YouTube 或網頁分頁！\n"
            "   若音訊中的旋律與演奏樂器與任何網頁或視窗標題不符，代表該網頁目前【根本沒有發出聲音】！絕對不能把未在播放的網頁標題當作辨識結果！\n"
            "3. 只有當音訊中的音樂旋律，妳 100% 確實聽出並確認具體曲名時，才輸出具體曲名（例如：李斯特《鐘》、周杰倫《晴天》等）。\n"
            "4. 若音訊旋律無法明確指認具體曲名，或聽到的音樂與參考線索不符，請【務必僅輸出單詞】：UNKNOWN\n"
            "5. 絕對嚴禁瞎猜『電子舞曲』、『古典鋼琴曲』、『純音樂』等空泛形容詞！\n"
            "請直接輸出結果（25 字以內）："
        )

        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[audio_part, prompt_text]
        )

        res_text = resp.text.strip() if resp and resp.text else ""
        res_text = re.sub(r"^(這段音訊是|電腦正在播放|這聽起來是|這是一首|這是)\s*", "", res_text)
        res_text = res_text.replace("\n", " ").replace("「", "").replace("」", "").strip()

        #  嚴格校驗：確保確實指認出具體曲名/作品，杜絕 generic 模糊風格瞎猜
        def _check_is_music_valid(s: str) -> bool:
            if not s or "UNKNOWN" in s.upper() or s in ["未知", "無法識別", "無音樂", "無特別音樂", "None", "None."]:
                return False
            has_title_marker = (
                ("《" in s and "》" in s) or
                ("「" in s and "」" in s) or
                any(sep in s for sep in [" - ", "－", " / ", " by ", "：", ":"])
            )
            generic_style_keywords = [
                "breakcore", "電子舞曲", "電子音樂", "電子樂", "碎拍", "drum & bass", "dnb",
                "lo-fi", "純音樂", "鋼琴", "獨奏", "演奏", "背景音樂", "bgm", "節奏",
                "流行", "古典", "動漫", "音效", "抒情", "旋律", "舞曲", "輕快", "激昂"
            ]
            if not has_title_marker:
                lower_s = s.lower()
                if any(kw in lower_s for kw in generic_style_keywords):
                    return False
            return True

        if not _check_is_music_valid(res_text):
            # 未確實聽出具體曲名，保持靜默，不通報終端機，不污染思緒
            return ""

        if res_text and len(res_text) >= 2:
            # 比對與上一輪辨識相似度，若只是細微詞彙變動則靜默更新，避免終端機洗版
            is_duplicate = False
            if LATEST_SYSTEM_MUSIC_INFO:
                sim = difflib.SequenceMatcher(None, res_text.lower(), LATEST_SYSTEM_MUSIC_INFO.lower()).ratio()
                if sim > 0.72:
                    is_duplicate = True

            LATEST_SYSTEM_MUSIC_INFO = res_text
            LATEST_SYSTEM_MUSIC_TIME = time.time()
            current_system_audio_context = f"電腦正在播放音樂/音效：{res_text}"
            realtime_task_mgr.update_audio_context(current_system_audio_context)
            if not is_duplicate:
                log_print(f"🎵 [電腦音樂感知] 7L 聽出電腦正在播放: 「{res_text}」")
            return res_text
    except Exception:
        # 若 API 短暫異常，由 GSMTC 底層精確線索保底
        try:
            from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
            sessions = os_desktop_sensor.get_windows_media_info()
            if sessions and sessions[0].get("title"):
                first_m = sessions[0]
                t = first_m["title"]
                a = first_m.get("artist", "")
                fallback_info = f"《{t}》" + (f" ({a})" if a else "")
                LATEST_SYSTEM_MUSIC_INFO = fallback_info[:25]
                LATEST_SYSTEM_MUSIC_TIME = time.time()
                current_system_audio_context = f"電腦正在播放音樂/音效：{LATEST_SYSTEM_MUSIC_INFO}"
                realtime_task_mgr.update_audio_context(current_system_audio_context)
                return LATEST_SYSTEM_MUSIC_INFO
        except Exception:
            pass
    return ""

async def system_audio_worker():
    """ 即時電腦內部全系統聲音感知與內錄協程 (WASAPI Loopback 實時耳目)"""
    global current_system_audio_context, LATEST_SYSTEM_AUDIO_RMS, LATEST_SYSTEM_AUDIO_TEXT
    global LATEST_SYSTEM_AUDIO_TEXT_TIME, CURRENT_SYSTEM_AUDIO_VOL_PERCENT
    global LATEST_SYSTEM_MUSIC_INFO, LATEST_SYSTEM_MUSIC_TIME, LAST_MUSIC_IDENTIFY_TIME
    
    log_print("🎧 [聲音感知] 7L 電腦內部全系統聲音監聽系統 (WASAPI Loopback) 已就緒！")
    
    speech_audio_buffer = deque(maxlen=35)   # ~2.8 秒語音滑動緩衝區 (35 * 0.08s)，專供即時 STT 人聲辨識
    music_audio_buffer = deque(maxlen=135)   # ~10.8 秒深度音樂滑動緩衝區 (135 * 0.08s)，專供 Gemini 聆聽旋律曲名
    last_transcribe_time = 0.0
    is_transcribing = False

    def _convert_buffer_to_wav(chunks):
        try:
            if not chunks:
                return None
            data = np.concatenate(chunks, axis=0)
            if len(data.shape) > 1 and data.shape[1] > 1:
                data_mono = np.mean(data, axis=1)
            else:
                data_mono = data.flatten()
            audio_int16 = (np.clip(data_mono, -1.0, 1.0) * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())
            return buf.getvalue()
        except Exception:
            return None

    def _sync_capture_step(recorder):
        data = recorder.record(numframes=1280)
        rms = float(np.sqrt(np.mean(np.square(data))))
        return data, rms

    while True:
        try:
            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            with loopback_mic.recorder(samplerate=16000, blocksize=1280) as recorder:
                while True:
                    data, rms = await asyncio.to_thread(_sync_capture_step, recorder)
                    LATEST_SYSTEM_AUDIO_RMS = rms
                    # 依據 RMS 計算 0 ~ 100% 全系統即時音量 (RMS 0.16 約為 100%)
                    vol_pct = min(100, int((rms / 0.16) * 100)) if rms > 0.003 else 0
                    CURRENT_SYSTEM_AUDIO_VOL_PERCENT = vol_pct
                    speech_audio_buffer.append(data)
                    music_audio_buffer.append(data)

                    #  若 7L 自身正在唱歌，電腦聲音為 7L 歌聲，略過 STT 與音樂猜測，防止自己被自己打斷
                    if IS_SINGING_ACTIVE or current_ai_state == "SINGING":
                        current_system_audio_context = "7L 正在為老爸翻唱歌曲（Live2D 舞台開唱中）"
                        LATEST_SYSTEM_MUSIC_INFO = "7L 翻唱歌曲"
                        LATEST_SYSTEM_MUSIC_TIME = time.time()
                        realtime_task_mgr.update_audio_context(current_system_audio_context)
                        await asyncio.sleep(0.08)
                        continue

                    #  若 7L 自身正在彈鋼琴，電腦聲音為 7L 琴聲，直接同步曲目，略過 STT 與音樂猜測
                    if (hasattr(pe, "is_piano_active_and_alive") and pe.is_piano_active_and_alive()) or getattr(pe, "is_piano_active", False) or current_ai_state == "PIANO":
                        song_t = getattr(pe, "current_piano_song_title", "") or "鋼琴曲"
                        current_system_audio_context = f"7L 正在為老爸演奏鋼琴：《{song_t}》"
                        LATEST_SYSTEM_MUSIC_INFO = f"《{song_t}》"
                        LATEST_SYSTEM_MUSIC_TIME = time.time()
                        realtime_task_mgr.update_audio_context(current_system_audio_context)
                        await asyncio.sleep(0.08)
                        continue

                    # 若有聲音 (RMS > 0.007) 且未在進行 TTS 發話
                    is_tts = False
                    try:
                        is_tts = pygame.mixer.music.get_busy()
                    except Exception:
                        pass

                    now = time.time()
                    if rms > 0.007 and not is_tts and not is_transcribing:
                        # 累積至少 1.5 秒語音且距離上次轉錄 > 2.5 秒
                        if len(speech_audio_buffer) >= 20 and (now - last_transcribe_time > 2.5):
                            is_transcribing = True
                            last_transcribe_time = now
                            speech_chunks = list(speech_audio_buffer)
                            # 若音樂緩衝區已累積足夠長度 (>= 80 塊，約 6.4s~10.8s) 且已過冷卻 (>= 18s)
                            music_chunks = list(music_audio_buffer) if (len(music_audio_buffer) >= 80 and (now - LAST_MUSIC_IDENTIFY_TIME >= 18.0)) else None

                            async def _do_bg_transcribe(s_chunks, m_chunks):
                                nonlocal is_transcribing
                                try:
                                    wav_bytes = await asyncio.to_thread(_convert_buffer_to_wav, s_chunks)
                                    if wav_bytes:
                                        # 原本走本地 STT，現在聽你的，直接走獨立的 Live API 對比！
                                        text = await gemini_system_audio_live_transcribe(wav_bytes)

                                        if text:
                                            global LATEST_SYSTEM_AUDIO_TEXT, LATEST_SYSTEM_AUDIO_TEXT_TIME, current_system_audio_context
                                            LATEST_SYSTEM_AUDIO_TEXT = text
                                            LATEST_SYSTEM_AUDIO_TEXT_TIME = time.time()
                                            RECENT_SYSTEM_AUDIO_TRANSCRIPTS.append((time.time(), text))
                                            if len(RECENT_SYSTEM_AUDIO_TRANSCRIPTS) > 15:
                                                RECENT_SYSTEM_AUDIO_TRANSCRIPTS.pop(0)
                                            current_system_audio_context = f"電腦正在播放音訊/語音：『{text}』"
                                            realtime_task_mgr.update_audio_context(current_system_audio_context)
                                            log_print(f"🔊 [電腦全系統內錄] 識別到電腦音訊: 「{text}」 (音量: {CURRENT_SYSTEM_AUDIO_VOL_PERCENT}%)")

                                            lower_t = text.lower()
                                            if any(n in lower_t for n in ["7l", "七七", "小七", "機器人"]):
                                                add_to_streamer_mind_board(" [電腦/DC通話語音]", f"電腦傳出語音提到妳：『{text}』", source="system_audio")
                                        elif m_chunks:
                                            #  STT 未辨識到語音，且音樂緩衝區已累積 7~11 秒高品質長音訊，由音樂感知核心深度聆聽
                                            m_wav_bytes = await asyncio.to_thread(_convert_buffer_to_wav, m_chunks)
                                            if m_wav_bytes:
                                                await identify_system_music_and_sound(m_wav_bytes)
                                except Exception:
                                    pass
                                finally:
                                    is_transcribing = False

                            asyncio.create_task(_do_bg_transcribe(speech_chunks, music_chunks))
                    elif rms <= 0.003:
                        if now - last_transcribe_time > 3.0 and (now - LAST_TTS_END_TIME > 2.0):
                            if now - LATEST_SYSTEM_AUDIO_TEXT_TIME > 10.0 and now - LATEST_SYSTEM_MUSIC_TIME > 10.0:
                                LATEST_SYSTEM_AUDIO_TEXT = ""
                                LATEST_SYSTEM_MUSIC_INFO = ""
                                LAST_MUSIC_IDENTIFY_TIME = 0.0  # 靜音後重置冷卻，下一首新歌進來能迅速感知
                                current_system_audio_context = "電腦目前沒有播放特別的聲音。"
                                realtime_task_mgr.update_audio_context(current_system_audio_context)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1.0)

AI_FACE_TRACKING_RUNNING = False

async def ai_face_tracking_loop(vts):
    global AI_FACE_TRACKING_RUNNING
    if AI_FACE_TRACKING_RUNNING:
        log_print("⚠️ [VTS 追蹤] 檢測到已存在運行的 ai_face_tracking_loop 實例，略過重複啟動以杜絕抖動衝突。")
        return
    AI_FACE_TRACKING_RUNNING = True
    try:
        await _ai_face_tracking_loop_impl(vts)
    finally:
        AI_FACE_TRACKING_RUNNING = False

async def _ai_face_tracking_loop_impl(vts):
    t = 0.0
    blink_timer = time.time() + random.uniform(3.5, 6.0)
    blink_start_time = 0.0
    is_blinking = False
    smooth_sleep_eye = 1.0  #  休眠閉眼平滑過渡因子 (1.0 清醒睜眼 -> 0.0 閉眼安睡)
    
    curr_x, curr_y, curr_z = 0.0, 0.0, 0.0
    curr_eye_x, curr_eye_y = 0.0, 0.0
    smooth_piano_focus_x = 0.0
    auto_mouse_track_timer = 0.0  
    
    while True:
        try:
            if not IS_FACE_TRACKING_ENABLED:
                await asyncio.sleep(0.5)
                continue
            now = time.time()
            is_playing = False
            try:
                ch6_busy = False
                if pygame.mixer.get_init():
                    try:
                        ch6_busy = pygame.mixer.Channel(6).get_busy()
                    except Exception:
                        pass
                is_playing = (
                    IS_MP3_PLAYING 
                    or IS_SINGING_ACTIVE 
                    or ch6_busy 
                    or (current_ai_state == "SINGING") 
                    or (pygame.mixer.get_init() and pygame.mixer.music.get_busy())
                    or yt_comp.IS_YT_SPEAKING
                )
            except Exception:
                pass

            if current_ai_state == "IDLE" and not is_playing and not vc.is_tracking_mouse:
                if auto_mouse_track_timer > 0:
                    auto_mouse_track_timer -= 0.05
                    if auto_mouse_track_timer <= 0:
                        vc.target_look_x = 0.0
                        vc.target_look_y = 0.0
                else:
                    if random.random() < 0.005:  
                        auto_mouse_track_timer = random.uniform(2.0, 4.0)  
            else:
                if auto_mouse_track_timer > 0:
                    auto_mouse_track_timer = 0.0
                    if not vc.is_tracking_mouse:
                        vc.target_look_x = 0.0
                        vc.target_look_y = 0.0

            is_currently_tracking = vc.is_tracking_mouse or auto_mouse_track_timer > 0

            if is_currently_tracking:
                sw, sh = pyautogui.size()
                px, py = pyautogui.position()
                
                #  以 7L 的 VTS 視窗中心為基準，修正視線相對於螢幕中心的偏差
                vc._vts_win_cx, vc._vts_win_cy = await vc.update_vts_window_center(sw, sh)
                
                # 以 7L 的視窗中心為參考點，計算滑鼠相對位置（往左為負，往右為正）
                nx = (px / sw) - vc._vts_win_cx  # 以 VTS 視窗 X 為 0 點
                ny = (py / sh) - vc._vts_win_cy
                vc.target_look_x, vc.target_look_y = nx * 28.0, ny * -20.0

            vc.current_look_x += (vc.target_look_x - vc.current_look_x) * 0.08
            vc.current_look_y += (vc.target_look_y - vc.current_look_y) * 0.08

            #  檢測休眠狀態：若休眠則眼睛平滑閉合為 0.0；若喚醒則平滑睜眼至 1.0
            if IS_SLEEPING:
                smooth_sleep_eye = max(0.0, smooth_sleep_eye - 0.08)
            else:
                smooth_sleep_eye = min(1.0, smooth_sleep_eye + 0.12)

            #  眼睛開合計算 (休眠模式強制閉眼 0.0；清醒模式正常眨眼)
            if IS_SLEEPING:
                eye_open_left = smooth_sleep_eye
                eye_open_right = smooth_sleep_eye
                is_blinking = False
            else:
                #  自然真實眨眼機制 (每 3.5~6.5 秒眨眼一次，閉眼時間精確為 0.14 秒，徹底杜絕快速連眨)
                eye_open_left = smooth_sleep_eye
                eye_open_right = smooth_sleep_eye
                if vc.force_blink_trigger > 0:
                    if not is_blinking:
                        is_blinking = True
                        blink_start_time = now
                        vc.force_blink_trigger = 0
                elif not is_blinking and now > blink_timer:
                    is_blinking = True
                    blink_start_time = now

                if is_blinking:
                    if now - blink_start_time < 0.14:
                        eye_open_left = 0.0
                        eye_open_right = 0.0
                    else:
                        eye_open_left = smooth_sleep_eye
                        eye_open_right = smooth_sleep_eye
                        is_blinking = False
                        blink_timer = now + random.uniform(3.5, 6.5)
                else:
                    eye_open_left = smooth_sleep_eye
                    eye_open_right = smooth_sleep_eye

            #  靈動眼珠與鋼琴音符密集處視線追蹤計算
            if vc.eye_roll_timer > now:
                #  招牌靈動大轉眼珠 / 大圈環視四周 (俐落 360° 滿幅滿力道 1.0 大圓周軌跡)
                target_eye_x = math.sin(t * 4.2) * 1.0
                target_eye_y = math.cos(t * 4.2) * 1.0
                curr_eye_x = target_eye_x
                curr_eye_y = target_eye_y
            elif pe.is_piano_active_and_alive():
                #  只要處於鋼琴彈奏狀態中：眼神永遠精準朝下追蹤琴鍵音符密集重心
                smooth_piano_focus_x += (pe.PIANO_NOTE_FOCUS_X - smooth_piano_focus_x) * 0.25
                target_eye_x = max(-0.85, min(0.85, smooth_piano_focus_x / 16.0))
                target_eye_y = -0.75
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            elif is_currently_tracking:
                # 滑鼠游標注視
                target_eye_x = max(-0.85, min(0.85, vc.current_look_x / 20.0))
                target_eye_y = max(-0.85, min(0.85, vc.current_look_y / 15.0))
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            elif current_ai_state == "THINKING":
                # 思考中視線往斜上方
                target_eye_x = -0.38
                target_eye_y = 0.55
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            else:
                # 待命/說話時：更自然靈動的左右眼神飄移（幅度加大，像真正說話時的眼神流動）
                target_eye_x = math.sin(t * 0.9) * 0.55 + (vc.current_look_x / 28.0) * 0.55
                target_eye_y = math.cos(t * 0.65) * 0.28 + (vc.current_look_y / 20.0) * 0.4
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.13
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.13

            target_angle_x = 0.0
            target_angle_y = 0.0
            target_angle_z = 0.0
            target_mouth = 0.0

            #  真實音訊波形精準對嘴：完全根據音訊逐幀 RMS 振幅與快開慢合物理平滑決定！
            if is_playing:
                global CURRENT_SMOOTH_MOUTH
                if CURRENT_MOUTH_ENVELOPE and CURRENT_SPEECH_START_TIME > 0:
                    elapsed = now - CURRENT_SPEECH_START_TIME
                    frame_idx = int(elapsed * 25.0)
                    if 0 <= frame_idx < len(CURRENT_MOUTH_ENVELOPE):
                        raw_target = CURRENT_MOUTH_ENVELOPE[frame_idx]
                    else:
                        raw_target = 0.0
                    
                    #  快開慢合 (Fast Attack 0.65, Gentle Release 0.35) 物理濾波，徹底告別卡頓與僵硬
                    if raw_target > CURRENT_SMOOTH_MOUTH:
                        CURRENT_SMOOTH_MOUTH += (raw_target - CURRENT_SMOOTH_MOUTH) * 0.65
                    else:
                        CURRENT_SMOOTH_MOUTH += (raw_target - CURRENT_SMOOTH_MOUTH) * 0.35
                    target_mouth = round(CURRENT_SMOOTH_MOUTH, 3)
                else:
                    #  若無真實音訊波形包絡 (如生成等待、句間分段間隙)，自然平滑閉合嘴巴，嚴禁無聲時空動嘴！
                    CURRENT_SMOOTH_MOUTH *= 0.35
                    target_mouth = round(CURRENT_SMOOTH_MOUTH, 3)
            else:
                CURRENT_SMOOTH_MOUTH = 0.0
                target_mouth = 0.0

            # 姿態與頭部運動計算
            if pe.is_piano_active_and_alive():
                #  鋼琴彈奏中：頭部與身體重心專注在鍵盤，隨音符高低音律動傾斜（說話時僅動嘴，姿態不變）
                smooth_piano_focus_x += (pe.PIANO_NOTE_FOCUS_X - smooth_piano_focus_x) * 0.25
                target_angle_x = smooth_piano_focus_x * 0.65 + math.sin(t * 1.2) * 2.5
                target_angle_y = -10.0 + math.cos(t * 1.5) * 1.5
                target_angle_z = smooth_piano_focus_x * 0.30 + math.sin(t * 1.0) * 2.0
            elif is_playing:
                #  MP3 播放中：頭部溫和自然微幅呼吸點頭
                target_angle_x = math.sin(t * 1.0) * 1.5 + vc.current_look_x * 0.25
                target_angle_y = math.cos(t * 0.8) * 0.8 + vc.current_look_y * 0.25
                target_angle_z = math.sin(t * 0.7) * 1.0
            elif is_currently_tracking:
                target_angle_x = vc.current_look_x
                target_angle_y = vc.current_look_y
                target_angle_z = 0.0
            else:
                if IS_SLEEPING:
                    #  沉睡休眠安詳姿態：頭微低下垂 (-8.5度)，伴隨均勻舒緩的深層呼吸起伏
                    sleep_breath = math.sin(t * 0.45)
                    target_angle_x = math.sin(t * 0.25) * 1.0
                    target_angle_y = -8.5 + sleep_breath * 0.8
                    target_angle_z = 1.5 + math.sin(t * 0.3) * 0.8
                elif current_ai_state == "IDLE":
                    # 待命時：更自然有幅度的漫遊擺頭，像真人靜待時的自然晃動
                    target_angle_x = math.sin(t * 0.42) * 4.0 + vc.current_look_x * 0.45
                    target_angle_y = math.cos(t * 0.32) * 1.5 + vc.current_look_y * 0.35
                    target_angle_z = math.sin(t * 0.3) * 1.5
                elif current_ai_state == "THINKING":
                    target_angle_x = -2.0 + vc.current_look_x * 0.2
                    target_angle_y = 2.0 + vc.current_look_y * 0.2
                    target_angle_z = 4.5
                elif current_ai_state == "TALKING":
                    # 說話時：加入自然語感搖頭韻律（像說話時帶的肢體動作），幅度不誇張但明顯活潑
                    target_angle_x = math.sin(t * 1.1) * 3.5 + vc.current_look_x * 0.55
                    target_angle_y = math.cos(t * 0.75) * 1.2 + vc.current_look_y * 0.35
                    target_angle_z = math.sin(t * 0.85) * 1.8

            if vc.eye_roll_timer > now:
                target_angle_z += math.sin(t * 4.2) * 3.5
                target_angle_y += math.cos(t * 4.2) * 2.0

            #  純物理動力學縮小瞳孔與震驚 (EyeOpen=2.0 瞪大縮瞳 + 自然呼吸微顫抖)
            #  發話期間若有物理表情，持續延長鎖定，確保說話全程不中途褪去
            if CURRENT_PLAYING_VOICE_TASK is not None:
                if vc.shock_timer > now:
                    vc.shock_timer = max(vc.shock_timer, now + 1.0)
                if vc.frown_timer > now:
                    vc.frown_timer = max(vc.frown_timer, now + 1.0)

            is_in_shock = (vc.shock_timer > now)
            is_frowning = (vc.frown_timer > now)
            
            #  徹底防呆：時效結束時立即歸零重置，絕不殘留！
            if not is_in_shock and vc.shock_timer > 0:
                vc.shock_timer = 0.0
            if not is_frowning and vc.frown_timer > 0:
                vc.frown_timer = 0.0

            if is_in_shock:
                eye_open_left = 2.0
                eye_open_right = 2.0
                target_brows = 0.85
                target_mouth_smile = 0.35
                if not is_playing:
                    target_mouth = 0.20  # 震驚未發話時微張嘴 (呆滯/倒抽氣)；發話時保持正常對嘴開合
                target_angle_x += math.sin(t * 12.0) * 0.20
                target_angle_y += math.sin(t * 10.0) * 0.15
                target_angle_z += math.cos(t * 11.0) * 0.20
                curr_eye_x += math.sin(t * 8.0) * 0.02
                curr_eye_y += math.cos(t * 7.0) * 0.02
            elif is_frowning:
                #  困擾/委屈 皺眉表情 (Brows = 0.0 壓低眉毛形成八字皺眉 + 微撇嘴/微嘟嘴)
                eye_open_left = 0.95
                eye_open_right = 0.95
                target_brows = 0.0
                target_mouth_smile = 0.25
                target_angle_z += math.sin(t * 1.5) * 2.0
                target_angle_y += -1.5
            elif vc.wink_timer > now:
                #  俏皮靈動單邊眨一下眼 (Wink: 總時長 0.55 秒，眨一下立即順暢張開)
                elapsed_wink = 0.55 - (vc.wink_timer - now)
                if elapsed_wink < 0.10:
                    wink_eye_open = max(0.0, 1.0 - (elapsed_wink / 0.10))
                elif elapsed_wink <= 0.32:
                    wink_eye_open = 0.0
                else:
                    wink_eye_open = min(1.0, (elapsed_wink - 0.32) / 0.23)

                if vc.wink_side == "left":
                    eye_open_left = wink_eye_open
                    eye_open_right = 1.0
                    target_angle_z += 3.5 * (1.0 - wink_eye_open)
                else:
                    eye_open_left = 1.0
                    eye_open_right = wink_eye_open
                    target_angle_z += -3.5 * (1.0 - wink_eye_open)
                target_brows = 0.50
                target_mouth_smile = 0.50 + 0.35 * (1.0 - wink_eye_open)
            else:
                #  平時自然溫和中性眉毛 (0.50) 與自然微笑 (0.50，發話時隨開口度靈動上揚)
                target_brows = 0.50
                target_mouth_smile = min(1.0, 0.50 + 0.20 * target_mouth) if is_playing else 0.50

            curr_x += (target_angle_x - curr_x) * 0.10
            curr_y += (target_angle_y - curr_y) * 0.10
            curr_z += (target_angle_z - curr_z) * 0.10

            param_values = [
                {"id": "FaceAngleX", "value": curr_x, "weight": 1.0},
                {"id": "FaceAngleY", "value": curr_y, "weight": 1.0},
                {"id": "FaceAngleZ", "value": curr_z, "weight": 1.0},
                {"id": "EyeLeftX", "value": -curr_eye_x, "weight": 1.0},  # Invert X for correct eye tracking relative to head
                {"id": "EyeLeftY", "value": curr_eye_y, "weight": 1.0},
                {"id": "EyeRightX", "value": -curr_eye_x, "weight": 1.0}, # Invert X for correct eye tracking relative to head
                {"id": "EyeRightY", "value": curr_eye_y, "weight": 1.0},
                {"id": "EyeOpenLeft", "value": eye_open_left, "weight": 1.0},
                {"id": "EyeOpenRight", "value": eye_open_right, "weight": 1.0},
                {"id": "Brows", "value": target_brows, "weight": 1.0},
                {"id": "MouthSmile", "value": target_mouth_smile, "weight": 1.0},
                {"id": "MouthOpen", "value": target_mouth, "weight": 1.0}
            ]

            if hasattr(vts, 'inject_parameters'):
                await vts.inject_parameters(param_values)
            else:
                vts_data = {
                    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "AIStateTracking",
                    "messageType": "InjectParameterDataRequest",
                    "data": {
                        "faceFound": True,
                        "mode": "set",
                        "parameterValues": param_values
                    }
                }
                async with vc.vts_lock:
                    await asyncio.wait_for(vts.request(vts_data), timeout=0.5)

            t = (t if isinstance(t, (int, float)) else 0.0) + 0.08
        except Exception as loop_err:
            t = 0.0

        await asyncio.sleep(0.04)

async def expression_keeper_worker(vts):
    
    while True:
        await asyncio.sleep(12.0)
        if vc.CURRENT_ACTIVE_EXP:
            try:
                msg_state = {
                    "apiName": "VTubeStudioPublicAPI", 
                    "apiVersion": "1.0", 
                    "requestID": "GetState", 
                    "messageType": "ExpressionStateRequest", 
                    "data": {"details": True}
                }
                async with vc.vts_lock:
                    resp_state = await asyncio.wait_for(vts.request(msg_state), timeout=1.0)
                
                expressions = resp_state.get("data", {}).get("expressions", [])
                active_files = [exp.get("file") for exp in expressions if exp.get("active")]
                if vc.CURRENT_ACTIVE_EXP not in active_files:
                    async with vc.vts_lock:
                        await asyncio.wait_for(vts.request({
                            "apiName": "VTubeStudioPublicAPI",
                            "apiVersion": "1.0",
                            "requestID": "ForceActivate",
                            "messageType": "ExpressionActivationRequest",
                            "data": {"expressionFile": vc.CURRENT_ACTIVE_EXP, "active": True}
                        }), timeout=0.8)
            except Exception:
                pass

async def anti_watermark_worker(vts):
    await asyncio.sleep(2.0)
    try:
        async with vc.vts_lock:
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

# ────────────────────────────────────────────────────────

async def print_model_parameters(vts):
    try:
        await asyncio.sleep(1.0)
        await vc.fetch_vts_base_model_pos(vts)
    except Exception: 
        pass

GLOBAL_VTS_TRACKING_TASK = None
_VTS_LAST_AUTH_TIME = 0.0
_VTS_LAST_RECONNECT_TIME = 0.0
_VTS_IS_RECONNECTING = False  # 防止重連競態

_VTS_PING_MSG = {
    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
    "requestID": "HealthPing", "messageType": "APIStateRequest", "data": {}
}

async def _vts_real_ping(vts) -> bool:
    """真實 WebSocket ping：送 APIStateRequest 並等待回應，失敗即表示連線已死"""
    try:
        async with vc.vts_lock:
            resp = await asyncio.wait_for(vts.request(_VTS_PING_MSG), timeout=1.5)
        return isinstance(resp, dict)
    except Exception:
        return False

async def vts_health_worker(vts):
    global GLOBAL_VTS_TRACKING_TASK, _VTS_LAST_AUTH_TIME, _VTS_LAST_RECONNECT_TIME, _VTS_IS_RECONNECTING
    while True:
        await asyncio.sleep(5.0)  # 5 秒心跳（比原本 3 秒寬鬆，減少 ping 佔用）
        if _VTS_IS_RECONNECTING:
            continue
        try:
            now = time.time()
            #  真實 ping 測試：不靠 is_connected() 假狀態，直接送 APIStateRequest
            alive = await _vts_real_ping(vts)
            if not alive:
                #  真正斷線：10 秒冷卻重連
                if now - _VTS_LAST_RECONNECT_TIME >= 10.0:
                    _VTS_IS_RECONNECTING = True
                    try:
                        log_print("🔌 [VTS 心跳] 偵測到連線中斷，正在重新連線...")
                        async with vc.vts_lock:
                            await vts.connect(retries=2)
                            await vts.request_authenticate()
                        _VTS_LAST_RECONNECT_TIME = time.time()
                        _VTS_LAST_AUTH_TIME = time.time()
                        log_print("✅ [系統通知] VTube Studio 重新連線與授權成功！身體控制權已恢復！")
                    except Exception as reconn_err:
                        log_print(f"⚠️ [VTS 重連失敗]: {reconn_err}")
                    finally:
                        _VTS_IS_RECONNECTING = False
            else:
                # 連線正常：重置時間戳，確保下次真正斷線能立刻重連
                _VTS_LAST_AUTH_TIME = now

            #  守護追蹤主協程：若協程因任何異常退出，即刻自動重啟
            if GLOBAL_VTS_TRACKING_TASK is None or GLOBAL_VTS_TRACKING_TASK.done():
                GLOBAL_VTS_TRACKING_TASK = asyncio.create_task(ai_face_tracking_loop(vts))
        except Exception:
            _VTS_IS_RECONNECTING = False

async def autonomous_wander_worker():
    """7L 背景非同步自主漫遊走位與自主彈琴協程（在老爸閒置時由 7L 自主漫步或自主彈奏鋼琴）"""
    global LAST_WANDER_TIME
    LAST_AUTO_PIANO_TIME = time.time()
    
    while True:
        try:
            await asyncio.sleep(12.0)
            idle_ticks = get_silence_ticks()
            
            #  7L 休眠中自主甦醒邏輯（若電腦播放音樂或老爸回來活動，7L 感知到環境熱鬧自主醒來）
            if IS_SLEEPING:
                if LATEST_SYSTEM_MUSIC_INFO or CURRENT_VISION_CHANGE_LEVEL in ["medium", "high"]:
                    reason = f"播放音樂 ({LATEST_SYSTEM_MUSIC_INFO})" if LATEST_SYSTEM_MUSIC_INFO else "畫面切換活躍"
                    log_print(f"☀️ [7L 自主甦醒] 偵測到老爸電腦正在{reason}，7L 自主醒來！")
                    await set_sleep_mode(False)
                    wake_text = "唔嗯～好聽的音樂！老爸你在聽歌呀，7L 睡醒囉！" if LATEST_SYSTEM_MUSIC_INFO else "嗯... 老爸回來啦？7L 睡醒囉，隨時為你服務！"
                    speech_item = {
                        "text": wake_text,
                        "expression": "自然",
                        "action": "WINK",
                        "target": "dad",
                        "target_name": "老爸",
                        "priority": 100
                    }
                    await speech_queue.put(speech_item)
                continue

            if pe.is_piano_active or IS_SINGING_ACTIVE or current_ai_state in ["TALKING", "THINKING", "PIANO", "SINGING"]:
                continue

            #  7L 自主作息小憩邏輯（深夜15分鐘或白天60分鐘無人對話且環境完全安靜時，7L 自主決定小憩入睡）
            if not IS_SLEEPING and current_ai_state == "IDLE":
                import datetime
                current_hour = datetime.datetime.now().hour
                is_deep_night = (current_hour >= 1 and current_hour < 7)
                is_idle_night = is_deep_night and idle_ticks > 900   # 深夜 15 分鐘 (900 ticks) 無互動
                is_idle_day = idle_ticks > 3600                      # 白天 60 分鐘 (3600 ticks) 無互動
                is_quiet = not LATEST_SYSTEM_MUSIC_INFO and CURRENT_VISION_CHANGE_LEVEL in ["none", "low"]
                
                if (is_idle_night or is_idle_day) and is_quiet:
                    log_print("🌙 [7L 自主作息] 環境持續長時間安靜無聲，7L 決定自主閉眼小憩進入休眠...")
                    speech_item = {
                        "text": "唔... 老爸好像去休息了呢，那 7L 也先瞇一下小憩囉～老爸回來叫我一聲我就醒啦！",
                        "expression": "自然",
                        "action": "",
                        "target": "dad",
                        "target_name": "老爸",
                        "priority": 100
                    }
                    await speech_queue.put(speech_item)
                    await asyncio.sleep(5.0)
                    await set_sleep_mode(True)
                    continue
            
            idle_seconds = None
            if IS_AUTO_WANDER_ENABLED and current_ai_state == "IDLE" and idle_seconds > 60.0:
                #  自主彈琴邏輯：預設關閉（IS_AUTO_PIANO_ENABLED = False），嚴禁未經指示自作主張彈琴打斷老爸或與背景音樂打架
                def now():
                    pass
                if IS_AUTO_PIANO_ENABLED and (now - LAST_AUTO_PIANO_TIME > 300.0):
                    # 嚴防干擾：若電腦正在播放音樂/音訊，絕不彈琴搶聲音
                    is_noisy = bool(LATEST_SYSTEM_MUSIC_INFO)
                    if not is_noisy:
                        LAST_AUTO_PIANO_TIME = now
                        LAST_WANDER_TIME = now
                        local_seeds = pe.get_local_piano_seeds()
                        if local_seeds:
                            song_seed = random.choice(local_seeds)
                            log_print(f"🎹 [7L 自主彈琴] 7L 決定自主坐到鋼琴前為老爸演奏《{song_seed}》！")
                            ai_intro = await pe.generate_dynamic_piano_chatter(song_seed, is_radio=False)
                            if ai_intro:
                                log_print(f"💬 [自主彈琴 AI 自由意志發話]: {ai_intro}")
                                await speech_queue.put({"text": ai_intro, "target": "dad", "private": False})
                            else:
                                log_print("🎹 [自主彈琴 AI 自由意志] 7L 決定優雅安靜入座，全神貫注為老爸演奏。")
                            await pe.play_virtual_piano(song_seed)
                            continue

                if now - LAST_WANDER_TIME > 60.0:
                    LAST_WANDER_TIME = now
                    await move_vts_spatial(target_pos="random", duration=3.0)
                    vc.CURRENT_SPATIAL_LOCATION = "自由漫遊"
                    
        except Exception:
            await asyncio.sleep(5.0)

# ---  語音合成排隊協程 (老爸優先 / 異步雙軌仲裁器) ---
async def speech_queue_worker(vts, input_queue):
    global current_ai_state, CURRENT_SPEAKING_TARGET, CURRENT_PLAYING_VOICE_TASK
    while True:
        try:
            #  7L 翻唱中絕不開口說話打斷自己的歌聲，排隊等候演唱完畢
            while IS_SINGING_ACTIVE or current_ai_state == "SINGING":
                await asyncio.sleep(0.5)

            item = await speech_queue.get()
            if not item:
                continue
            
            # 再次檢查：若等待期間進入唱歌狀態，持續等待至演唱完畢
            while IS_SINGING_ACTIVE or current_ai_state == "SINGING":
                await asyncio.sleep(0.5)

            if isinstance(item, dict):
                text = item.get("text", "")
                target = item.get("target", "dad")
                raw_actions_text = item.get("raw_text", "")
                #  公開性：未顯式標註時，target=dad 視為操作者私訊（不播出）
                private = bool(item.get("private", target == "dad"))
            else:
                text = str(item)
                target = "dad"
                raw_actions_text = ""
                private = True
                
            if not text:
                continue
            
            #  只對觀眾發聲（依你的要求）：操作者私訊管道的回話不播出。
            #    記憶/字幕前置處理/表情與計時器都已在此之前完成，這裡只攔「播放」；
            #    同時清掉剛寫入的 OBS 字幕，避免觀眾看到一句沒被唸出來的話。
            if not speech_allowed(private):
                shown = raw_actions_text or text
                log_print(f"🔇 [操作者回話·靜默] {shown}")
                try:
                    await asyncio.to_thread(update_subtitle, "")
                except Exception:
                    pass
                try:
                    import services.web_dashboard as _wd
                    _wd.broadcast_event("dad_reply_silent", {"text": shown})
                except Exception:
                    pass
                continue

            CURRENT_SPEAKING_TARGET = target
            current_ai_state = "TALKING"
            touch_interaction()
            
            # 建立可隨時被自己插話或老爸說話秒級 cancel 的播放任務（整合 Live API 潛意識神態導演與句中多表情動態時間軸）
            CURRENT_PLAYING_VOICE_TASK = asyncio.create_task(play_voice_complete(text, target=target, raw_actions_text=raw_actions_text, vts=vts))
            try:
                await CURRENT_PLAYING_VOICE_TASK
            except asyncio.CancelledError:
                log_print("🛑 [語音被中斷] 7L 當前句子已成功中斷，無縫讓位給最新發言。")
            finally:
                CURRENT_PLAYING_VOICE_TASK = None
            
            #  發話音訊一播放完畢，立即秒級釋放麥克風狀態，絕不卡死老爸即時接話！
            if speech_queue.empty():
                if current_ai_state == "TALKING":
                    current_ai_state = "SINGING" if IS_SINGING_ACTIVE else ("PIANO" if pe.is_piano_active else "IDLE")
                CURRENT_SPEAKING_TARGET = "none"
            
            #  表情停留緩衝：發話完畢後若表情仍在時效內，持續保留一段時間（預設 3.5 秒），讓情緒自然延續
            now = time.time()
            if vc.frown_timer > now:
                vc.frown_timer = now + vc.EXPRESSION_HOLD_SECONDS
            else:
                vc.frown_timer = 0.0

            if vc.shock_timer > now:
                vc.shock_timer = now + vc.EXPRESSION_HOLD_SECONDS
            else:
                vc.shock_timer = 0.0

            hold_steps = int(vc.EXPRESSION_HOLD_SECONDS * 10)
            for _ in range(hold_steps):
                if not speech_queue.empty() or not input_queue.empty():
                    break
                await asyncio.sleep(0.1)
            
            if input_queue.empty() and speech_queue.empty() and not pe.is_piano_active:
                await set_vts_expression(vts, "_RESET_")
            
            if current_ai_state == "TALKING":
                current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
            CURRENT_SPEAKING_TARGET = "none"
        except Exception as e:
            log_print(f"\n❌ [語音排隊系統異常]: {e}")
            if current_ai_state == "TALKING":
                current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
            CURRENT_SPEAKING_TARGET = "none"
        finally:
            try:
                speech_queue.task_done()
            except Exception:
                pass

# ────────────────────────────────────────────────────────
#  15. 對話處理與自主發話大腦核心
# ────────────────────────────────────────────────────────
async def background_system_task(vts, input_queue, user_input, stage1_text, system_prompt, current_history, screen_img=None):
    global current_ai_state
    current_ai_state = "THINKING"
    sys_info = await asyncio.to_thread(get_system_performance)

    stage2_prompt = f"（系統提示：針對剛才使用者說的「{user_input}」，妳剛才初步回應：「{stage1_text}」。現在系統已取得他的電腦工作管理員即時數據：「{sys_info}」。請根據這項數據，用妳自行發展出的語氣給予自然補充，不要重複前言。）"
    messages = [{"role": "system", "content": system_prompt}] + current_history + [{"role": "user", "content": stage2_prompt}]
    
    raw_stage2_text = await fetch_ai_response(messages, image_base64=screen_img, is_proactive=True)
    
    clean_bot_reply = re.sub(r"(?:\[|\|\|)?(NEW_NAME|NEW_IMPRESSION|改稱呼|記印象)[：:].*", "", raw_stage2_text, flags=re.IGNORECASE|re.DOTALL)
    
    if current_voice_task and not current_voice_task.done():
        current_voice_task.cancel()
    
    spoken = await execute_actions(vts, clean_bot_reply, input_queue, caller_target="dad", caller_user="老爸")
    clean_spoken = spoken.strip(" *'\"-.,!?。，！？\n\r") if spoken else ""
    if clean_spoken:
        #  大腦一回傳輸出，即刻第一時間更新 subtitle.txt 抵消 OBS 讀取延遲！
        await asyncio.to_thread(update_subtitle, clean_spoken)
        log_print(f"💬 7L 回覆: {clean_spoken} ({current_model_tag})")
        await speech_queue.put({"text": clean_spoken, "target": "audience", "raw_text": clean_bot_reply})
        current_history.append({"role": "assistant", "content": clean_spoken})
    else:
        await asyncio.to_thread(update_subtitle, "")
        log_print(f"💬 7L 回覆: [僅執行動作/表情] ({current_model_tag})")
        current_history.append({"role": "assistant", "content": raw_stage2_text})
        
    asyncio.create_task(save_to_long_term_memory(DEFAULT_CHANNEL_ID, current_history))




def check_requires_deep_gemini(user_input: str, stage1_text: str = "") -> bool:
    """判斷是否需要喚起 Gemini 旗艦大腦進行深度思考與工具調用 (若只是日常問答閒聊則直接略過以節省 API 額度)"""
    combined = f"{user_input} {stage1_text}".lower()
    if "[req_tool]" in combined or "[req_system]" in combined or "[open_browser" in combined:
        return True

    # 提取純淨文字 (去括號、去標籤、去前綴冒號)
    clean_q = re.sub(r'【.*?】[：:]?', '', user_input)
    clean_q = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', clean_q).strip(' ：:\t\r\n')

    # 1. 檢查是否直接命中本地真實 MIDI 曲庫 / catalog (如觀眾直接留言歌名「藍色狂想曲」、「Rhapsody in Blue」、「鐘」、「Liebestraum」)
    if clean_q:
        clean_ql = clean_q.lower()
        if clean_ql in pe.AUTHENTIC_MIDI_MAP or clean_ql in pe.MIDI_AI_MATCH_CACHE or any(clean_ql in k or k in clean_ql for k in pe.AUTHENTIC_MIDI_MAP):
            return True

    # 2. 若當前鋼琴處於彈奏或待命狀態 (pe.is_piano_active)，任何可能是歌名的簡短輸入 (如 Liebestraum-3, Canon, 換首好聽的) 優先走工具通道
    if pe.is_piano_active and clean_q and len(clean_q) <= 40:
        non_song_chat = ["你好", "早安", "晚安", "在幹嘛", "謝謝", "哈哈", "掰掰", "再見", "老爸", "7l", "好聽", "讚", "太棒了"]
        if not any(k == clean_q.lower() for k in non_song_chat):
            return True

    # 3. 工具與深度操作關鍵字 (包含鋼琴、繪圖、搜尋、代碼等)
    tool_keywords = [
        "彈鋼琴", "彈琴", "點歌", "彈一首", "彈奏", "播放鋼琴", "換一首", "切歌", "鋼琴", "來一首", "來首", "播一首", "放一首", "彈", "換這首", "馬上換", "這就彈", "這首",
        "換音色", "切換音色", "鋼琴音色", "弦樂", "吉他", "小提琴", "大提琴", "薩克斯風", "木琴", "管風琴", "手風琴", "豎琴", "電鋼琴", "人聲合唱", "古箏", "卡林巴",
        "畫一張", "畫圖", "生成圖片", "畫個", "生圖", "畫一幅", "畫一隻", "繪製",
        "搜尋", "查一下", "上網查", "最新新聞", "天氣", "google搜尋", "幫我查",
        "寫程式", "寫代碼", "寫個遊戲", "俄羅斯方塊", "貪吃蛇", "執行程式", "python",
        "關閉麥克風", "開啟麥克風", "靜音麥克風", "清空記憶", "重置記憶", "記住大小", "記住位置", "記住現在位置", "記住當前位置", "記錄位置", "記錄大小", "記住模型位置", "記住模型", "記錄基準",
        "妳的電腦", "你的電腦", "專屬電腦", "虛擬機", "妳的虛擬機", "自己的電腦", "在電腦上", "電腦螢幕", "去妳的電腦", "在妳電腦", "操作電腦", "看妳螢幕", "看妳的螢幕", "自己去玩", "去玩", "看影片", "自主學習", "寫日記", "玩遊戲", "自主探索",
        "deepseek", "r1", "深度推理", "智能體", "agent", "autogen", "crewai", "瀏覽器操作", "openclaw", "harness",
        "鋼琴音量", "鋼琴大聲", "鋼琴小聲", "鋼琴靜音", "倍速", "演奏速度", "混在一起彈", "雜在一起彈", "合體", "神仙打架", "mashup"
    ]
    if any(k in combined for k in tool_keywords) or clean_q.startswith("彈"):
        return True

    return False

def is_piano_song_request(user_input: str) -> bool:
    """判斷觀眾發言是否為點歌或彈琴請求。
    【老爸最高鐵律】：沒有說彈就不是當作歌名 (格式: 彈《歌名》或 彈youtube《歌名》)，除非很明顯是歌名！
    """
    if not user_input or not user_input.strip():
        return False
    clean_q = re.sub(r'【.*?】[：:]?', '', user_input)
    clean_q = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', clean_q).strip(' ：:\t\r\n')
    if not clean_q:
        return False
    clean_ql = clean_q.lower().strip()

    #  1. 純數字或標點符號（如 "67", "666", "777", "123"）絕對不是歌名！
    if clean_ql.isdigit() or re.fullmatch(r'[\d\s.,!?:;~～\-_+]+', clean_ql):
        return False

    #  2. 長度過短且無點歌動詞，絕對不是歌名
    if len(clean_ql) <= 1:
        return False

    #  3. 排除日常問候、感嘆詞、詢問鋼琴視窗、日常抱怨
    non_song_dialogue = [
        "拿出來", "出來了沒", "沒出來", "在哪", "開了沒", "沒開", "收起來", "關掉", "不見了",
        "有看到嗎", "你的鋼琴呢", "是不是沒", "沒看到", "看不到", "視窗", "鋼琴好大", "鋼琴好小", "什麼牌子",
        "笑死", "太強了", "好聽", "厲害", "你好", "哈囉", "安安", "早安", "晚安", "在嗎", "在幹嘛", "主播好"
    ]
    if any(k == clean_ql for k in non_song_dialogue):
        return False
    if any(k in clean_ql for k in ["拿出來", "出來了沒", "沒出來", "開了沒", "沒開", "收起來", "視窗在哪", "鋼琴呢"]):
        if not any(k in clean_ql for k in ["彈一首", "點歌", "播放", "放一首", "來一首", "換這首", "聽這首"]):
            return False

    #  4. 符合「標準點歌格式」：明確含有「彈」、「點」、「聽」、「放」、「播」等動詞
    # 格式包含：彈《歌名》、彈youtube《歌名》、彈yt《歌名》、彈 歌名、點歌、想聽、來一首、播放 等
    explicit_song_verbs = [
        "彈", "點歌", "點一首", "想聽", "來一首", "來首", "播放鋼琴", "播一首", "放一首",
        "換一首", "切歌", "彈奏", "彈琴", "彈鋼琴", "能彈", "可以彈", "幫我彈", "請彈"
    ]
    if any(v in clean_ql for v in explicit_song_verbs):
        return True

    #  5. 「除非很明顯是歌名」：
    # 5A. 帶有書名號《...》或引號「...」包裹，且書名號內不是純數字或單字
    book_titles = re.findall(r'[《「](.*?)[》」]', clean_q)
    for bt in book_titles:
        bt_clean = bt.strip()
        if len(bt_clean) >= 2 and not bt_clean.isdigit():
            return True

    # 5B. 含有知名音樂家/歌手前綴 + 曲名
    famous_artists = [
        "蕭邦", "周杰倫", "李斯特", "貝多芬", "莫札特", "巴哈", "德布西", "拉赫曼尼諾夫",
        "柴可夫斯基", "久石讓", "林俊傑", "陳奕迅", "鄧紫棋", "五月天", "告五人", "yoasobi",
        "animenz", "canacana", "米津玄師"
    ]
    if any(artist in clean_ql for artist in famous_artists) and len(clean_ql) >= 4:
        return True

    # 5C. 明確且具代表性的知名經典曲目（無歧義專有曲名，需完全吻合）
    famous_classics = [
        "千本櫻", "卡農", "大魚", "起風了", "晴天", "夜曲", "青花瓷", "告白氣球",
        "稻香", "夢中的婚禮", "給愛麗絲", "土耳其進行曲", "天空之城", "龍貓", "神隱少女"
    ]
    if any(clean_ql == fc for fc in famous_classics):
        return True

    # 其餘無「彈」且不明顯是歌名者，一律回傳 False！
    return False

async def prefetch_song_midi_background(song_query: str):
    """背景非同步預熱/預查 MIDI 曲庫與 AI 語意匹配（100% 由 Gemini 高智商大腦判定）"""
    try:
        if not is_piano_song_request(song_query):
            return
        available_files = [os.path.basename(p) for p in glob.glob(os.path.join(pe.MIDI_SHEETS_DIR, "*.mid"))]
        ai_intent = await pe.resolve_piano_intent_by_ai(song_query, available_files)
        if ai_intent.get("is_song_request") and ai_intent.get("song_title"):
            await pe.resolve_local_midi_file(ai_intent["song_title"])
    except Exception:
        pass

# ────────────────────────────────────────────────────────
#  15. 全集中全景時序記憶中樞與對話派發系統 (Unified Mind-Stream Architecture)
# ────────────────────────────────────────────────────────
#  核心設計：
#    - `UNIFIED_LIVE_MEMORY`: 全局唯一統一記憶時間線（deque maxlen=300 + 本地 unified_memory.json 持久化）。
#      老爸對話、直播觀眾彈幕、7L 自身發言、鋼琴演奏等全事件 100% 匯流同一時間線。
#    - 所有 Gemini 呼叫點（老爸旗艦主腦、主播記憶看板、Live 專屬雙軌、自主發話、Live 哨兵）
#      無論輪詢切換到哪個 API Key 或模型，100% 讀取同一份完整全景時序劇本，徹底消滅思想斷裂！






def add_to_streamer_mind_board(user_display: str, unique_id: str, content: str, source: str = "tiktok"):
    """將接收到的彈幕/留言/事件寫入 7L 記憶腦袋，一排一排排列記錄，由主播自主排程讀取與發話"""
    item = {
        "id": f"msg_{time.time()}_{random.randint(1000, 9999)}",
        "time": time.time(),
        "time_str": datetime.now(ZoneInfo('Asia/Taipei')).strftime('%H:%M:%S'),
        "user": user_display,
        "unique_id": unique_id,
        "content": content,
        "source": source,
        "status": "unread"
    }
    STREAMER_MIND_BOARD.append(item)
    
    #  寫入全集中記憶中樞（確保老爸輸入與觀眾彈幕統一匯流，精準辨別對話目標）
    if unique_id == "dad" or source in ["mic", "text_file", "console"]:
        try:
            from core.identity import get_owner_name, get_character_name
            speaker = get_owner_name()
            mem_target = get_character_name()
        except Exception:
            speaker = "老爸"
            mem_target = "7L"
    elif source == "owner_interject":
        try:
            from core.identity import get_owner_name as _gon
            speaker = f"主持「{_gon()}」"
        except Exception:
            speaker = "主持"
        mem_target = "觀眾"
    else:
        _platform = {"twitch": "Twitch", "youtube": "YouTube", "owner_interject": "主持"}.get(source, "TikTok")
        speaker = f"{_platform} 觀眾「{user_display}」" if source != "owner_interject" else f"主持「{user_display}」"
        lower_c = (content or "").lower()
        try:
            from core.identity import get_character_name as _gcn
            _cn = _gcn().lower()
        except Exception:
            _cn = "7l"
        is_addressed_to_7l = any(tag in lower_c for tag in ["7l", "@7l", "小7", "7寶", "草莓", _cn])
        mem_target = "7L" if is_addressed_to_7l else "老爸/直播間"

    append_to_unified_memory(
        speaker=speaker,
        target=mem_target,
        content=content,
        role="user",
        source=source
    )
    
    # 即時推送觀眾留言/老爸發言給網頁後台
    try:
        import services.web_dashboard as _wd
        if source in ["mic", "text_file", "console", "web_console"]:
            _wd.broadcast_event("chat_sent", {"text": content, "from": speaker})
        else:
            _wd.broadcast_event("tiktok_comment", {"user": user_display, "text": content})
    except Exception:
        pass
        
    unread_count = sum(1 for m in STREAMER_MIND_BOARD if m["status"] == "unread")
    log_print(f"📥 [記憶腦袋 寫入] {user_display}: {content} (🧠 看板累積未讀: {unread_count} 筆)")
    
    #  依老爸鐵律判定是否為點歌意圖（必須有「彈」或明顯歌名），再交由 Gemini 確認
    if pe.is_piano_active and pe.current_piano_song_title and content and is_piano_song_request(content):
        async def evaluate_and_queue_with_gemini(raw_text: str):
            try:
                available_files = [os.path.basename(p) for p in glob.glob(os.path.join(pe.MIDI_SHEETS_DIR, "*.mid"))]
                intent = await pe.resolve_piano_intent_by_ai(
                    raw_text, 
                    available_files,
                    current_playing_title=pe.current_piano_song_title,
                    current_playing_file=pe.current_piano_midi_file
                )
                if intent.get("is_song_request") and intent.get("song_title"):
                    target_song = intent["song_title"]
                    cand_midi = os.path.join(pe.MIDI_SHEETS_DIR, intent["matched_files"][0]) if intent.get("matched_files") else ""
                    log_print(f"🎵 [Gemini 意圖確認] 高智商大腦確認老爸/觀眾點播《{target_song}》，自動預載排入待播隊列！")
                    await pe.play_virtual_piano(target_song, midi_file=cand_midi, requester_name=user_display, target="audience", is_direct_song_name=True)
            except Exception:
                pass
        asyncio.create_task(evaluate_and_queue_with_gemini(content))

def mark_streamer_mind_board_as_read(unique_id: str = None, content: str = None):
    """ 將 7L 記憶腦袋看板中的指定留言/對話標記為已讀"""
    marked_cnt = 0
    for m in STREAMER_MIND_BOARD:
        if m.get("status") == "unread":
            if unique_id and m.get("unique_id") == unique_id:
                m["status"] = "read"
                marked_cnt += 1
            elif content and m.get("content") == content:
                m["status"] = "read"
                marked_cnt += 1
            elif not unique_id and not content:
                m["status"] = "read"
                marked_cnt += 1
    if marked_cnt > 0:
        log_print(f"📖 [記憶腦袋 已讀] 已將 {marked_cnt} 筆看板項目標記為已讀")

# 8 大大腦優先順序梯隊 (頂配高智商旗艦大腦優先)


async def judge_subconscious_intent_via_live_api(memory_context: str, unread_batch_desc: str) -> dict:
    """ 【Live API 潛意識發言決策哨兵】：
    利用 Live API 無限額度特性，實時審閱 100 句記憶與新彈幕，
    極速判定當前是否該開口發話（二元決策），絕不浪費主力模型額度！
    回傳 dict: {"should_speak": bool, "target": str, "focus": str, "song": str, "raw": str}
    """
    candidate_keys = get_dynamic_live_key_candidates(KEYS_AUDIENCE_LIVE if KEYS_AUDIENCE_LIVE else GEMINI_KEYS)
    for idx, g_key in enumerate(candidate_keys[:4]):
        client = genai.Client(api_key=g_key)
        try:
            live_cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=types.Content(parts=[types.Part(text="""妳是 7L 的背景潛意識決策神經（Subconscious Sentry）。
妳正在即時審查全集中累積的最新滾動記憶與剛收到的新輸入（包含老爸的麥克風語音、電腦打字、或直播觀眾彈幕）。
請快速判斷 7L 當前是否應該開口發話回應？
【 邊彈邊聊特別規範】：即使 7L 背景正在彈奏鋼琴，只要有人說話、提問、打招呼、點歌或留言互動，一律正常判定 [SPEAK: ...]！7L 具備邊彈鋼琴邊聊天讀訊息的即時多工能力，絕不因彈琴而保持沉默！
1. 【老爸發話（語音/打字）】：
   -  僅當輸入明確標註為【老爸】或來自麥克風/主腦通道時才可判定為老爸！
   - 若老爸在對妳說話、下指令、問話、調侃、點歌、或互動 ➔ 請輸出：[SPEAK: target=老爸, focus=指令或話題焦點, song=歌名(若點歌)]
   - 若老爸在專注自言自語、喃喃自語、或純背景雜音/咳嗽 ➔ 請輸出：[SILENCE]
2. 【直播觀眾彈幕（多人實況與權限通化判定）】：
   - 直播間包含：老爸（打遊戲的主播與唯一決策者）、觀眾（看直播發言的網友）、7L（同台 AI 女兒副播）。
   - 【通化決策原則（直接禁止 7L 擅自主張）】：
     * 凡觀眾提出任何請求（遊戲、好友、組隊、帳號、聯繫方式、抽獎等）或向主播提問 ➔ 7L 絕不擅自主張開條件，一律向老爸請示或通報，輸出：[SPEAK: target=老爸(因應觀眾請求/提問), focus=請示老爸, user=觀眾名]
     * 若觀眾在聊遊戲戰況、操作、嘴主播 ➔ 7L 作為同台副播女兒，在旁起鬨或吐槽老爸，輸出：[SPEAK: target=老爸(因應觀眾留言吐槽), focus=吐槽老爸/起鬨, user=觀眾名]
     * 若觀眾明確指名 7L 互動、聊天、點歌、稱讚 ➔ 輸出：[SPEAK: target=用戶名, focus=話題重點, song=歌名(若點歌)]
     * 若為無聊刷屏、無意義表情/符號、或目前無需插話 ➔ 請輸出：[SILENCE]
嚴禁輸出任何多餘聊天內容，只輸出 [SILENCE] 或 [SPEAK: ...]！""")])
            )
            async with asyncio.timeout(3.5):
                async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
                    prompt_eval = f"""【最新滾動記憶與近期全景上下文】：
{memory_context}

【剛收到的最新未讀輸入】：
{unread_batch_desc}

請即刻給出潛意識發言決策（[SILENCE] 或 [SPEAK: ...]）："""
                    await session.send_realtime_input(text=prompt_eval)
                    
                    decision_text = ""
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            if c.output_transcription and c.output_transcription.text:
                                decision_text += c.output_transcription.text
                            if c.turn_complete or getattr(c, 'generation_complete', False):
                                break
                                
                    decision_clean = decision_text.strip()
                    if decision_clean:
                        if "[SILENCE]" in decision_clean or decision_clean.upper() == "SILENCE" or "[PASS]" in decision_clean:
                            return {"should_speak": False, "raw": decision_clean}
                        
                        target_match = re.search(r'target\s*=\s*([^,\]]+)', decision_clean, re.IGNORECASE)
                        focus_match = re.search(r'focus\s*=\s*([^,\]]+)', decision_clean, re.IGNORECASE)
                        song_match = re.search(r'song\s*=\s*([^,\]]+)', decision_clean, re.IGNORECASE)
                        
                        t_user = target_match.group(1).strip() if target_match else ""
                        t_focus = focus_match.group(1).strip() if focus_match else ""
                        t_song = song_match.group(1).strip() if song_match else ""
                        
                        return {
                            "should_speak": True,
                            "target": t_user,
                            "focus": t_focus,
                            "song": t_song,
                            "raw": decision_clean
                        }
        except Exception:
            continue
            
    # 若 Live API 暫時連線繁忙，預設放行由主力大腦判定
    return {"should_speak": True, "target": "", "focus": "", "song": "", "raw": "FALLBACK_ALLOW"}

async def streamer_mind_loop_worker(vts, input_queue):
    """ 7L 主播記憶腦袋持續讀取與自由意志發話協程：
    1. 背景保持最新 100 句記憶上下文
    2. 透過無限額度 Live API 潛意識哨兵極速做發言時機判斷
    3. 判定該開口時，喚醒 7 大主力大腦梯隊 (3.1 Flash Lite ➔ 3.5 ➔ 3.7) 讀取 100 句記憶精準開口！
    """
    global last_interaction_time
    log_print("🧠 [主播記憶腦袋]協程已就緒")
    
    while True:
        try:
            await asyncio.sleep(1.0)
            if IS_SLEEPING:
                await asyncio.sleep(2.0)
                continue
            
            # 1. 狀態檢查：若正在說話、唱歌、思考、或老爸正在對話，先保持安靜
            is_singing = IS_SINGING_ACTIVE or current_ai_state == "SINGING"
            is_speaking = False
            try:
                is_speaking = is_singing or (pygame.mixer.get_init() and pygame.mixer.music.get_busy()) or not speech_queue.empty() or current_ai_state == "TALKING"
            except Exception:
                pass
                
            if is_speaking or current_ai_state in ["THINKING", "SINGING"] or is_singing:
                continue
                
            #  鋼琴演奏中不阻擋讀訊息：支援邊彈琴邊即時讀取觀眾彈幕/老爸留言並開口互動！
                
            # 若老爸在 5 秒內剛說過話，優先等待老爸
            if time.time() - last_interaction_time < 5.0 and CURRENT_SPEAKING_TARGET == "dad":
                continue
                
            # 2. 檢查記憶腦袋中是否有未讀彈幕
            unread_items = [m for m in STREAMER_MIND_BOARD if m["status"] == "unread"]
            if not unread_items:
                continue
                
            # 3. 取出最新批次（1 ~ 5 筆）
            batch_to_process = unread_items[-5:]
            for m in batch_to_process:
                m["status"] = "processing"
                
            # 組合看板彈幕清單與認人資料
            board_lines = []
            users_involved = []
            viewer_profiles_text = []
            has_dad_message = False

            for m in batch_to_process:
                u_id = m.get('unique_id', '')
                u_name = m.get('user', '')
                u_source = m.get('source', '')
                if u_id == 'dad' or u_source in ['mic', 'text_file', 'console']:
                    has_dad_message = True
                    board_lines.append(f"- [{m['time_str']}] 【老爸】：{m['content']}")
                else:
                    board_lines.append(f"- [{m['time_str']}] 【TikTok 直播觀眾「{u_name}」】：{m['content']}")
                    if u_name not in users_involved:
                        users_involved.append(u_name)

            board_context = "\n".join(board_lines)
            target_audience_desc = "、".join(users_involved) if users_involved else "觀眾"

            #  查詢並注入觀眾認人資料 (call/relationship/impression)
            for u in users_involved:
                v_prof = await get_viewer_profile(u)
                v_call = v_prof.get("call")
                v_rel = v_prof.get("relationship")
                v_imp = v_prof.get("impression")
                if v_call or v_rel or v_imp:
                    id_parts = []
                    if v_rel: id_parts.append(f"關係:「{v_rel}」")
                    if v_call: id_parts.append(f"習慣稱呼:「{v_call}」")
                    if v_imp: id_parts.append(f"印象:「{v_imp}」")
                    viewer_profiles_text.append(f"  * 熟客觀眾【{u}】：{'，'.join(id_parts)}（請親切稱呼他「{v_call or u}」）")
                else:
                    viewer_profiles_text.append(f"  * 觀眾【{u}】：新進或尚未建檔，請親切稱呼他「{u}」")

            #  提取最新 100 句完整記憶
            memory_100_context = get_recent_100_memory_context()
            
            #  階段一：由 Live API 潛意識哨兵以無限額度進行實時發言決策
            board_context_for_sentry = board_context

            sentry_decision = await judge_subconscious_intent_via_live_api(memory_100_context, board_context_for_sentry)
            if not sentry_decision["should_speak"]:
                for m in batch_to_process:
                    m["status"] = "read"
                log_print("🤫 [Live 潛意識哨兵] 審查 100 句記憶後判定：目前無需發言 / 刷屏 ➔ [PASS] 略過 (0 消耗主力額度)")
                continue
                
            sentry_target = sentry_decision.get("target", "").strip()
            if "老爸" in sentry_target:
                log_target = "老爸(因應觀眾留言吐槽/搭腔)"
            elif sentry_target:
                log_target = sentry_target
            elif users_involved:
                log_target = users_involved[0]
            else:
                log_target = "直播間"

            log_focus = sentry_decision.get("focus") or "精彩互動"
            log_print(f"🚨 [Live 潛意識哨兵 喚醒主力] 判定應開口！目標: {log_target} | 焦點: {log_focus}")
            
            # 準備系統 Prompt（注入 100 句完整記憶、認人檔案與哨兵焦點）
            user_profile = await get_user_profile()
            current_custom_name = user_profile.get("custom_name", DEFAULT_USER_TITLE)
            cloud_kn = await get_cloud_knowledge()
            cloud_kn_prompt = PromptTemplateEngine.format_cloud_knowledge_prompt(cloud_kn, is_tiktok=True, current_custom_name=current_custom_name)

            if pe.is_piano_active and pe.current_piano_song_title:
                piano_status = f"【 鋼琴邊彈邊聊】：妳目前正坐在 88 鍵鋼琴前為大家演奏《{pe.current_piano_song_title}》中！妳完全支援「邊彈琴邊與大家聊天/讀訊息/互動」（像鋼琴主播一樣邊彈邊隨性聊兩句）。若有人點歌或詢問進度（如「還有多久到我的」），請口頭溫柔告知排隊進度（例如：『這首彈完下一首就輪到你囉！』）；若是一般留言稱讚或聊天，隨性親切回覆 1~2 句即可，鋼琴演奏在背景持續進行。"
            else:
                piano_status = "目前背景演奏已結束或未在彈琴。"
            
            profiles_block = "\n".join(viewer_profiles_text) if viewer_profiles_text else "（暫無觀眾檔案）"
            if not has_dad_message:
                role_strict_block = f"""【 多人直播間認人與情境認知 (極重要)】
直播間目前處於【多人實況狀態】：
1.  【老爸】：坐在電腦前打遊戲、實況操作的真人男主播/爸爸。擁有直播間最高主權，所有遊戲操作、帳號、好友/組隊、各類事務請求與決策 100% 歸老爸全權管轄！
2.  【觀眾：{target_audience_desc}】：在看老爸打遊戲並在聊天室發言的網友。
3.  【7L】：在老爸身邊同台直播的 AI 虛擬女兒/副播。
   -  【直接讓 7L 不要（絕對越權禁令）】：妳是 AI 少女副播，沒有遊戲帳號、沒有好友位、沒有任何管理決策與線下承諾權！
   - 凡觀眾向直播間提出任何請求、邀約或條件（加好友、組隊、求帶、借號、聯繫方式、抽獎等）：
     *  絕對不要擅自替老爸答應！絕對不要擅自拒絕！
     *  絕對嚴禁自居主人向觀眾開條件或討要好處（如「拿誠意來」、「看你表現」、「先誇我」等任何擅自主張的怪話，一律絕對嚴禁）！
     *  一律推給老爸做主、向老爸請示通報（例如：「老爸，觀眾杰尼龜想加你遊戲好友，你有位置嗎？」、「這要問我老爸做主喔～」）！
【 觀眾檔案】：
{profiles_block}
 【受話對象與發言姿態（通化原則）】：
- 情況 A（觀眾在聊遊戲戰況/操作/嘴主播/提出各類事務請求）：
  * 對象是【老爸】！不是 7L！以同台副播女兒視角，在旁向老爸起鬨、吐槽老爸或提醒老爸，絕不可誤認成在跟自己私聊！
- 情況 B（觀眾指名 7L / 向 7L 點歌 / 問 7L 問題）：
  * 只有明確指名「7L」、「@7L」、「小7」、「7寶」、「草莓」，對象才是【7L 本人】！直接稱呼觀眾「{log_target}」熱情自然回應！
- 情況 C（老爸與觀眾互聊）：7L 在旁圍觀、隨性搭腔或看熱鬧。"""
            else:
                role_strict_block = """【 多人直播間情境】：包含老爸與直播觀眾。老爸在打遊戲，觀眾在看老爸直播。請精準分清誰在對誰說話！"""

            sys_instruction = f"""妳是 7L。
時間：{get_current_time_string()}

{cloud_kn_prompt}

{role_strict_block}

【 直播現場精準時序記憶（掌握現場最新話題脈絡）】：
{get_unified_memory_context(limit=15, thought_char_limit=200)}

【 剛剛收到的最新彈幕】：
{board_context}

【 潛意識焦點提示】：回應對象：{log_target}，焦點：{log_focus}。
【當前狀態】：{piano_status}
{tk_listener.get_tiktok_live_telemetry()}

【 主播心智與發話規範】：
1.  【短句精煉與語意完整 (極重要)】：直播節奏明快，每次真正開口說話請保持「1 ~ 2 句自然短句（約 20 ~ 40 字，上限 60 字）」，【話一定要說完，絕對禁止半句斷尾】：
   - 口語自然、簡短直接、重點明確、接梗俐落，隨性真實。
   -  【嚴禁半句截斷】：整句話必須完整說完，句尾必須帶有完整中文標點符號（如『！』、『。』、『？』、『～』）完美收尾，絕不可說到一半斷字！
   -  【嚴禁長篇大論】：絕不長段自說自話、絕不說教、絕不一口氣拋出一堆反問句或追問句！
3.  【稱呼精準認人】：
   - 若回應指名 7L 的觀眾，直接對該觀眾（{log_target}）說話，親切念出名字！
   - 若觀眾是在跟老爸聊遊戲，妳是在向老爸吐槽或提醒老爸，請自然喊「老爸」，把情況告訴老爸或笑老爸，絕不可誤認成觀眾在跟妳私聊！
5.  【嚴禁報幕與元語言】：絕對禁止說「我看到你留言說了...」、「我看到我自己說了...」、「畫面上顯示我的字幕...」、「我看著看板...」等機械化報幕字眼！直接像真人主播一樣自然開口對答即可！
6.  【系統直接指令調用 (極重要)】：若要執行動作，請直接在對話中輸出對應的 Python 指令碼（系統會自動攔截執行，不會唸出來）：
   -  翻唱演唱：`auto_sing_song(song_name='歌名')`（當有人說『唱...』、『唱歌』時務必輸出此指令調用）
   -  點歌/彈琴：`pe.play_virtual_piano(song_name='歌名')`
   -  即興創作：`pe.compose_and_play_original_piano()`
   -  調整琴速：`pe.set_piano_speed(speed=1.0)`（支援 0.2~10.0 倍速，如 1.0 原速、1.5 快速、2.0 雙倍速）
   -  調整琴音量：`pe.set_piano_volume(volume=80)`
   -  切換琴音色：`pe.set_piano_instrument(instrument='樂器名')`
   -  暫停/繼續：`pe.pause_virtual_piano()` / `pe.resume_virtual_piano()`
   -  停止彈琴：`pe.stop_virtual_piano()`
   -  移動走位：`move_spatial_position('左側/右側/靠近/原位')`
   -  畫圖：`draw_illustration('畫面描述')`
7.  若彈幕全為無意義刷屏，可輸出 [PASS] 略過。
8. 標籤支援：
   - 表情：[EXPRESSION: 臉紅/生氣/愛心/星星/皺眉/震驚/WINK]（支援句中多次隨心切換，上半句與下半句可隨意變換神態）
   - 語調聲調：[SPEED:+20%] / [SPEED:-20%]、[PITCH:+15Hz] / [PITCH:-10Hz]（支援句中切換，表現興奮高亢、拉長音或無奈低語）
   - 視線走位：[LOOK: ROLL/CENTER/LEFT/RIGHT]、[MOVE: 靠近/躲角落/鋼琴旁/中間/原位]
   - 觀眾記憶：[VIEWER_UPDATE:用戶名|CALL:暱稱|REL:關係|IMP:印象]
   - 規範：輸出時自行加上完整中文標點符號（逗號、句號等）進行自然斷句，嚴禁使用 Emoji。"""

            prompt_user_input = "請結合剛才 100 句記憶、最新彈幕與畫面，判斷彈幕是與老爸/遊戲相關還是指名跟妳互動。凡涉及遊戲、帳號或任何事務請求，絕對嚴禁擅自主張或開條件，一律向老爸請示或推給老爸做主！以自然俐落的短句開口回應（1~2句，約 20~40 字，完整說完句尾帶標點符號，隨興在句中自由切換 [EXPRESSION: ...] 表情，善用 [SPEED:...]、[PITCH:...] 調節語調情緒）："
            
            # 4. 呼叫大腦模型矩陣 (依老爸指定 7 梯隊優先級輪流嘗試: 3.1 Flash Lite ➔ 3.5 Flash Lite ➔ 3 Flash ➔ 3.1 Pro ➔ 3.5 ➔ 3.6 ➔ 3.7)
            candidate_keys = [k for k in (KEYS_AUDIENCE_LIVE if KEYS_AUDIENCE_LIVE else GEMINI_KEYS) if k]
            random.shuffle(candidate_keys)
            
            full_reply = ""
            used_model_name = ""
            tool_output_text = ""

            #  Groq 第一梯隊：純文字直答先走 Groq（實測 0.4s 級）。
            #    只採用「純文字、無工具呼叫」的結果；模型要調工具或 Groq 失敗時，
            #    full_reply 維持原樣，交由下方 Gemini 梯隊處理（含 Function Response 第二輪）。
            try:
                from core.groq_router import groq_chat
                g_resp = await groq_chat(
                    [{"role": "user", "content": f"{sys_instruction}\n\n{prompt_user_input}"}],
                    tools=INTERACTIONS_TOOLS,
                    temperature=0.78, max_tokens=500, timeout=4.5,
                )
                if g_resp and g_resp.text and not g_resp.function_calls:
                    g_candidate = re.sub(r'\[PASS\]', '', g_resp.text, flags=re.IGNORECASE).strip()
                    if g_candidate:
                        full_reply = g_candidate
                        used_model_name = f"Groq/{g_resp.model}"
                    elif "[PASS]" in g_resp.text or g_resp.text.strip() == "PASS":
                        for m in batch_to_process:
                            m["status"] = "read"
                        log_print("🤫 7L (看板過濾): Groq 研判為無關刷屏 ➔ [PASS] 略過")
                        full_reply = "[PASS]"
            except Exception:
                pass

            for g_key in candidate_keys[:6]:
                if full_reply: break
                client = genai.Client(api_key=g_key)
                for model_name in STREAMER_MIND_MODELS:
                    try:
                        resp = await asyncio.wait_for(
                            client.aio.models.generate_content(
                                model=model_name,
                                contents=[
                                    types.Content(role="user", parts=[types.Part(text=f"{sys_instruction}\n\n{prompt_user_input}")])
                                ],
                                config=types.GenerateContentConfig(
                                    temperature=0.78,
                                    max_output_tokens=500,
                                    tools=GENAI_PROACTIVE_TOOLS,
                                    safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                                )
                            ),
                            timeout=5.0
                        )
                        
                        raw_reply = resp.text.strip() if resp.text else ""
                        tool_out = ""
                        if resp.function_calls:
                            for fc in resp.function_calls:
                                fn_name = getattr(fc, 'name', '')
                                fn_args = getattr(fc, 'args', {}) or {}
                                log_print(f"🛠️ [主播大腦調用工具] {fn_name}({fn_args})")
                                t_res = await execute_tool_dispatch(fn_name, fn_args, caller_target="audience", caller_user=log_target)
                                if fn_name == "search_google":
                                    s_summary = await summarize_search_to_speech(fn_args.get("query", ""), t_res, user_role_name="大家")
                                    tool_out += (" " + s_summary)
                                else:
                                    tool_out += (" " + t_res)
                        
                        clean_raw = re.sub(r'\[PASS\]', '', raw_reply, flags=re.IGNORECASE).strip()
                        #  若大腦調用了工具但未生成口語台詞 (常見於純 Function Call 回合)，由 7L 自然即興生成親切口語回應
                        if not clean_raw and resp.function_calls:
                            for fc in resp.function_calls:
                                fc_name = getattr(fc, 'name', '')
                                fc_args = getattr(fc, 'args', {}) or {}
                                if fc_name == "pe.play_virtual_piano":
                                    song_q = pe.clean_song_title_for_speech(fc_args.get("song_name", ""))
                                    if pe.is_piano_active and pe.current_piano_song_title:
                                        clean_raw = f"[EXPRESSION: 星星眼] {log_target}，沒問題！《{song_q or '這首'}》我先幫你排進清單，等現在這首彈完馬上幫你彈喔！"
                                    else:
                                        clean_raw = f"[EXPRESSION: 星星眼] {log_target}，好喔！這就為你彈《{song_q or '這首'}》！"
                                    break
                                elif fc_name == "pe.compose_and_play_original_piano":
                                    clean_raw = f"[EXPRESSION: 星星眼] {log_target}，沒問題！我現在就現場為你即興創作一首，聽聽看喔！"
                                    break
                                elif fc_name == "pe.mashup_virtual_piano":
                                    clean_raw = f"[EXPRESSION: 星星眼] {log_target}，收到！雙曲狂暴合奏這就來！"
                                    break

                        if not clean_raw and not tool_out.strip() and ("[PASS]" in raw_reply or raw_reply == "PASS"):
                            for m in batch_to_process:
                                m["status"] = "read"
                            log_print("🤫 7L (看板過濾): 研判為無關刷屏 ➔ [PASS] 略過")
                            full_reply = "[PASS]"
                            break
                            
                        final_res = clean_raw if clean_raw else tool_out.strip()
                        if final_res:
                            full_reply = final_res
                            used_model_name = model_name
                            tool_output_text = tool_out
                            break
                    except Exception as gen_err:
                        err_str = str(gen_err)
                        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                            break
                        continue
                        
            # 5. 標記處理完成
            for m in batch_to_process:
                m["status"] = "read"
                
            if not full_reply or full_reply == "[PASS]":
                continue
                
            # 6. 執行動作並發送發話隊列
            clean_reply = TextCleanEngine.remove_system_hints(full_reply)
            clean_reply = re.sub(r'^(?:回應|回覆|動作顯示|主播|說道|回答)[：:\s]+', '', clean_reply, flags=re.IGNORECASE).strip()
            clean_reply = re.sub(r'(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])', '', clean_reply)
            clean_reply = re.sub(r'\s+([，。！？,.!?:;])', r'\1', clean_reply)
            clean_reply = re.sub(r'\s{2,}', ' ', clean_reply).strip()
            
            m_tag = f" Mind-Stream ({used_model_name.replace('gemini-', '')})"
            log_print(f"🤖 原始大腦輸出: {clean_reply} (⚡ {m_tag})")
            
            #  記錄觀眾資料標籤
            for v_match in re.finditer(
                r'\[VIEWER_UPDATE[：:]\s*([^|\]]+?)(?:\|CALL[：:]\s*([^|\]]+?))?(?:\|REL[：:]\s*([^|\]]+?))?(?:\|IMP[：:]\s*([^|\]]+?))?\]',
                clean_reply, re.IGNORECASE
            ):
                vu_name = v_match.group(1).strip()
                vu_call = v_match.group(2).strip() if v_match.group(2) else None
                vu_rel  = v_match.group(3).strip() if v_match.group(3) else None
                vu_imp  = v_match.group(4).strip() if v_match.group(4) else None
                asyncio.create_task(save_viewer_profile(vu_name, call=vu_call, relationship=vu_rel, impression=vu_imp))
                log_print(f"👥 [認人] 記住觀眾 {vu_name}：稱={vu_call} 關係={vu_rel} 印象={vu_imp}")
            
            spoken = await execute_actions(vts, clean_reply, input_queue, user_input_ctx=board_context, has_dispatched_tool=bool(tool_output_text.strip()), caller_target="audience", caller_user=log_target)
            clean_spoken = spoken.strip(" *'\"-.,!?。，！？\n\r") if spoken else ""
            if clean_spoken:
                if pe.is_piano_active and pe.current_piano_song_title:
                    await asyncio.to_thread(update_subtitle, f" [7L 彈奏《{pe.current_piano_song_title}》]  {clean_spoken}")
                else:
                    await asyncio.to_thread(update_subtitle, clean_spoken)
                record_bot_message(clean_spoken)
                log_print(f"💬 7L (主播記憶看板回應): {clean_spoken} (⚡ {m_tag})")
                await speech_queue.put({"text": clean_spoken, "target": "audience", "raw_text": clean_reply})
                last_interaction_time = time.time()
                
                #  寫入全集中記憶中樞（確保所有大腦掌握 7L 最新發言）
                append_to_unified_memory(speaker="7L", target=f"觀眾「{log_target}」", content=clean_spoken, role="assistant", source="tts")
                
                # 寫入歷史
                fresh_hist = await fetch_from_long_term_memory("tiktok_live_stream")
                fresh_hist.append({"role": "user", "content": f"【觀眾留言群】：\n{board_context}"})
                fresh_hist.append({"role": "assistant", "content": clean_spoken})
                asyncio.create_task(save_to_long_term_memory("tiktok_live_stream", fresh_hist))
                
        except Exception as e:
            log_print(f"⚠️ [主播記憶腦袋協程異常]: {e}")
            await asyncio.sleep(1.0)


current_dad_task = None
current_audience_task = None
current_chat_task = None
CURRENT_CHAT_SESSION_ID = 0
CURRENT_PROCESSING_USER_INPUT = ""

async def process_chat_message(vts, input_queue, user_input: str, user_audio_b64: Optional[str] = None, request_start_time: Optional[float] = None, interrupted_context: str = "", source: str = "unknown"):
    """單一對話回合的核心處理常式 (即時神經大腦一步到位生成回覆與工具調用)"""
    global last_interaction_time, current_ai_state
    global IS_MIC_ENABLED, CURRENT_CHAT_SESSION_ID
    
    CURRENT_CHAT_SESSION_ID += 1
    my_session_id = CURRENT_CHAT_SESSION_ID
    
    try:
        req_start = request_start_time if request_start_time else time.time()
        current_ai_state = "THINKING"
        touch_interaction()
        user_profile = await get_user_profile()
        current_custom_name = user_profile.get("custom_name", DEFAULT_USER_TITLE)
        current_impression = user_profile.get("impression", "")

        #  0.001 秒緊急硬終止過濾
        if check_immediate_shutdown(user_input):
            return

        #  API Live 持續時間感測：智慧捕捉「多久後叫我 / 提醒我」意圖
        timer_intent = live_timer_hub.detect_timer_intent(user_input)
        if timer_intent:
            t_sec, t_action = timer_intent
            live_timer_hub.add_timer(t_sec, t_action, source="老爸發言", caller_user=current_custom_name)
            try:
                web_dash.broadcast_event("timer_added", live_timer_hub.get_sensor_summary())
            except Exception:
                pass

        #  語音/打字「關麥 / 開麥」即時指令攔截 (硬體狀態切換)
        clean_u = user_input.strip().lower()
        if any(k in clean_u for k in ["關麥", "閉麥", "關閉麥克風", "靜音麥克風", "麥克風關閉", "麥克風靜音"]):
            IS_MIC_ENABLED = False
            log_print("🎙️ [麥克風控制] 已即時關閉 (靜音) 麥克風收音！(輸入「開麥」可重新啟用)")
        elif any(k in clean_u for k in ["開麥", "開啟麥克風", "打開麥克風", "解除靜音", "麥克風開啟"]):
            IS_MIC_ENABLED = True
            log_print("🎙️ [麥克風控制] 已重新開啟麥克風收音！")

        #   【TikTok 直播觀眾專屬 Live 管道】：所有 TikTok 彈幕/提問/送禮/動態 100% 分流至專屬 Live 管道！
        tt_match_early = re.search(r'【TikTok (?:直播觀眾|官方提問箱|直播動態)\s*([^】]*?)\s*(?:留言|送禮|動態|提問)?】[：:]\s*(.*)', user_input)
        if not tt_match_early and "【TikTok" in user_input:
            tt_match_early = re.search(r'【TikTok\s*([^】]*?)】[：:]\s*(.*)', user_input)

        if tt_match_early:
            aud_u = tt_match_early.group(1).strip() or "直播觀眾"
            aud_c = tt_match_early.group(2).strip()
            live_ok = await call_gemini_live_audience_reply(vts, input_queue, aud_u, aud_c)
            if live_ok:
                last_interaction_time = time.time()
                current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
                return  #  Live 專屬管道處理完成，直接返回！
            log_print("⚠️ [TikTok 降級] Live 專屬管道暫不可用，自動無縫回退至極速文字/Gemini Flash Lite 保底大腦...")

        if tk_listener.IS_STREAMING:
            situation_prompt = f"【當前情境】：我們現在正在「開台實況 (Live Streaming)」！\n{tk_listener.get_tiktok_live_telemetry()}"
        else:
            situation_prompt = f"【當前情境】：現在是妳與{current_custom_name}私下的日常相處時間。"
        
        #  7L 實時全域狀態與進行中任務感知 (由 realtime_tasks 雲端中樞統一供給)
        situation_prompt += f"\n{realtime_task_mgr.get_realtime_summary()}"
        if interrupted_context:
            situation_prompt += f"\n【 實時前情提要（關鍵上下文）】：老爸前一秒剛說：「{interrupted_context}」，但該思考隨即被老爸當前這句「{user_input}」即時打斷/修正！請將兩句話結合理解（例如老爸可能是在澄清、指正聽錯、或接著上一句說）！"
    
        impression_text = f"- 妳對他的印象: {current_impression}\n" if current_impression else ""
        system_specs = get_system_performance()

        is_voice_input = bool(user_audio_b64)
        effective_audio_b64 = user_audio_b64 if is_voice_input else None
        if effective_audio_b64:
            saved_local_path = save_local_audio_clip(effective_audio_b64)
            if saved_local_path:
                log_print(f"🎙️ [本機音訊快取] 語音 WAV 已保存至本機: {os.path.basename(saved_local_path)}")
        live_audio_emotion_prompt = ""
        clean_spoken1 = ""
        stage1_raw = ""

        #  7L 自主判定記憶與感知需求深度（自適應調節：拒絕無腦強塞幾十句歷史導致大腦思考卡頓！）
        mem_decision = evaluate_memory_demand(
            user_input, 
            is_voice_input=is_voice_input, 
            source=source
        )
        mem_level = mem_decision.level
        u_lim = mem_decision.u_lim
        h_lim = mem_decision.h_lim
        th_lim = mem_decision.th_lim
        need_news = mem_decision.need_news
        single_screen = mem_decision.single_screen
        mem_reason = mem_decision.reason
        
        view_mode_str = "單圖快照 (0.1s)" if single_screen else "7圖時序多視角"
        log_print(f"🧠 [7L 自主記憶裁決] 模式: 【{mem_level}】(歷史:{h_lim}輪, 全景:{u_lim}句, 心流:{th_lim}字, 視覺:{view_mode_str}, 時事:{need_news}) | {mem_reason}")

        #  畫面截圖快照處理（依 7L 自主判定：極速/輕量使用單圖快照節省 1.5s；深度時使用 7 圖時序動態）
        if single_screen:
            if latest_screen_cache and isinstance(latest_screen_cache, list) and len(latest_screen_cache) > 0:
                current_screen_snapshot = latest_screen_cache[0][1] if isinstance(latest_screen_cache[0], (tuple, list)) else latest_screen_cache[0]
            else:
                current_screen_snapshot = latest_screen_cache
        else:
            current_screen_snapshot = get_combined_temporal_screen_snapshot()

        #  動態獲取 7L 雲端認知庫 (Firestore 永久大腦) 與 即時重大時事情報 (按需加載)
        cloud_kn = await get_cloud_knowledge()
        cloud_kn_prompt = PromptTemplateEngine.format_cloud_knowledge_prompt(cloud_kn)
        rag_sec = build_rag_section(user_input)   #  主對話路徑的 RAG 記憶檢索（離線、失敗自動略過）
        
        trending_news_prompt = ""
        if need_news:
            trending_news_prompt = await get_trending_news_briefing()

        #  依據自主判定配額動態調取歷史記憶（h_lim=0 時 0 毫秒秒過，完全不讀舊資料庫；最高調取上百句）
        history = (await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID, user_input, limit=max(h_lim, 150))) if h_lim > 0 else []
        recent_chat_prompt = ""
        #  1. 統一寫入全集中大腦記憶看板 (STREAMER_MIND_BOARD & 全局記憶中樞)
        add_to_streamer_mind_board(
            user_display=current_custom_name,
            unique_id="dad",
            content=user_input,
            source="mic" if is_voice_input else "text"
        )

        #  2. 由 Live API 潛意識哨兵審查發言時機（打字輸入、突發系統事件、直接點名 7L 則 0 秒極速直通，不浪費 3 秒哨兵！）
        is_direct_event = (not is_voice_input or user_input.startswith("【") or any(k in user_input.lower() for k in ["7l", "草莓", "小7", "電", "抱", "摸", "停", "唱", "曲", "彈", "？", "?"]))
        if is_direct_event:
            sentry_decision = {"should_speak": True, "focus": "老爸直接發話/突發事件"}
            log_print(f"⚡ [極速直通主腦] 老爸直接指令/突發事件 ➔ 0秒跳過潛意識哨兵，立即由主腦秒級開口！")
        else:
            memory_100_context = get_recent_100_memory_context()
            unread_input_desc = f"- [即時] {current_custom_name} ({'麥克風語音' if is_voice_input else '打字'}): {user_input}"
            sentry_decision = await judge_subconscious_intent_via_live_api(memory_100_context, unread_input_desc)
        
        if not sentry_decision.get("should_speak", True):
            log_print(f"🤫 [Live 潛意識哨兵] 審查全集中記憶判定：{current_custom_name}在專注自語/無發話需求 ➔ [SILENCE] 保持靈動安靜陪伴 (0 消耗主力額度)")
            realtime_task_mgr.mark_dad_input_read()
            mark_streamer_mind_board_as_read(unique_id="dad", content=user_input)
            mark_recent_thoughts_as_read()
            current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
            return
            
        log_focus = sentry_decision.get("focus") or "深度對話"
        if not is_direct_event:
            log_print(f"🚨 [Live 潛意識哨兵 喚醒主力] 判定應回應老爸！焦點: {log_focus}")

        #  模組化 Context 注入 (Modular Context Injection)
        context_blocks = []
        if situation_prompt: context_blocks.append(f"【即時情境】\n{situation_prompt.strip()}")
        if trending_news_prompt: context_blocks.append(trending_news_prompt.strip())
        if yt_comp.get_yt_memory_context(): context_blocks.append(yt_comp.get_yt_memory_context().strip())
        if rag_sec: context_blocks.append(rag_sec.strip())

        effective_situation = "\n\n".join(context_blocks)

        # ──  老爸全能旗艦主腦大腦 (語音多模態 + 螢幕截圖視覺 + 深度記憶 + 完整系統提示詞) ──
        
        #  注入動態時序記憶（由 7L 自主裁剪至最適長度，拒絕多餘負擔拖慢速度）
        if th_lim > 0:
            unified_mem_prompt = f"""【 直播現場潛意識與背景事件（7L 最近 {th_lim} 字內心流動與動作）】：
{get_unified_memory_context(limit=u_lim, thought_char_limit=th_lim, include_dialogue=False)}"""
        else:
            unified_mem_prompt = ""

        system_prompt = PromptTemplateEngine.build_chat_system_prompt(
            is_tiktok=False,
            current_custom_name=current_custom_name,
            stage2_target_prompt="",
            stage2_instructions="",
            current_target_desc=current_custom_name,
            is_piano_active=pe.is_piano_active,
            current_piano_song_title=pe.current_piano_song_title,
            live_audio_emotion_prompt="",
            situation_prompt=effective_situation,
            system_specs=system_specs,
            impression_text=impression_text,
            cloud_knowledge_prompt=cloud_kn_prompt,
            unified_memory_prompt=unified_mem_prompt
        )

        user_prefix = f"【{current_custom_name}開口語音對妳說話】" if is_voice_input else f"【{current_custom_name}在電腦打字發送】"
        user_msg_content = f"{user_prefix}：{user_input}"
        #  滑動窗口防記憶迴音：依 7L 自主判定結果動態注入歷史輪次
        effective_history = history[-h_lim:] if (history and h_lim > 0) else []
        messages = [{"role": "system", "content": system_prompt}] + effective_history + [{"role": "user", "content": user_msg_content}]
        
                # --- 影子平行大腦架構 ---
        shadow_prompt = f"【影子大腦任務】老爸剛剛說：{user_input}\n請評估是否需要查資料、彈鋼琴、改編MIDI或切換表情等工具。若需要，直接呼叫對應Tool。不需要則請保持沉默。絕對不要輸出任何對話台詞！"
        shadow_msgs = [{"role": "system", "content": system_prompt}] + effective_history + [{"role": "user", "content": shadow_prompt}]
        async def run_shadow_brain():
            try:
                await fetch_ai_response(shadow_msgs, image_base64=current_screen_snapshot, is_proactive=True, request_start_time=req_start)
            except Exception as e:
                pass
        asyncio.create_task(run_shadow_brain())
        
        # 嘴巴神經（極速串流，無Tool負擔）
        stream_iter = await fetch_ai_response(
            messages, 
            image_base64=current_screen_snapshot, 
            audio_base64=effective_audio_b64, 
            request_start_time=req_start,
            is_mouth_stream=True
        )
        
        if my_session_id != CURRENT_CHAT_SESSION_ID:
            return
            
        full_raw = ""
        full_clean = ""
        buffer = ""
        
        async def process_sentence(sentence):
            if not sentence.strip(): return
            bot_reply = re.sub(r'\[SKIP\]|\[SILENCE\]', '', sentence, flags=re.IGNORECASE).strip()
            if not bot_reply: return
            
            spoken = await execute_actions(vts, bot_reply, input_queue, user_input_ctx=user_input, caller_target="dad", caller_user=current_custom_name)
            clean_spoken = spoken.strip(" *'\"-.,!?。，！？\n\r") if spoken else ""
            
            if clean_spoken and my_session_id == CURRENT_CHAT_SESSION_ID:
                await asyncio.to_thread(update_subtitle, clean_spoken)
                await speech_queue.put({"text": clean_spoken, "target": "dad", "raw_text": bot_reply,
                                        "private": not str(source).startswith("tiktok")})
                return clean_spoken
            return ""

        async for chunk in stream_iter:
            if chunk.text:
                buffer += chunk.text
                full_raw += chunk.text
                parts = re.split(r'([。，！？\n]+)', buffer)
                if len(parts) > 1:
                    for i in range(0, len(parts)-1, 2):
                        phrase = parts[i] + parts[i+1]
                        c = await process_sentence(phrase)
                        if c: full_clean += c + " "
                    buffer = parts[-1]
                    
        if buffer.strip():
            c = await process_sentence(buffer)
            if c: full_clean += c + " "
            
        log_print(f"🤖 原始大腦輸出: {full_raw} ({current_model_tag})")
        
        if full_clean.strip() and my_session_id == CURRENT_CHAT_SESSION_ID:
            record_bot_message(full_clean.strip())
            log_print(f"💬 7L (主腦回覆): {full_clean.strip()} ({current_model_tag})")
            append_to_unified_memory(speaker="7L", target=current_custom_name, content=full_clean.strip(), role="assistant", source="tts")
            
        raw_spoken_text = full_raw
        bot_reply = re.sub(r'\[SKIP\]|\[SILENCE\]', '', raw_spoken_text, flags=re.IGNORECASE).strip()
        clean_spoken = full_clean.strip()
        
        if not clean_spoken:
            is_pure_silence = any(k in raw_spoken_text.upper() for k in ["[SILENCE]", "[SKIP]"])
            if not is_pure_silence:
                clean_asst_history = TextCleanEngine.clean_for_tts(bot_reply, apply_phonetics=False) or "[演奏鋼琴/動作執行]"
                append_to_unified_memory(speaker="7L", target=current_custom_name, content=clean_asst_history, role="assistant", source="action")
        
        last_interaction_time = time.time()
        #  靜默輪不污染記憶：若大腦判定保持安靜 [SILENCE]，不寫入空動作或假對話
        if clean_spoken or not any(k in raw_spoken_text.upper() for k in ["[SILENCE]", "[SKIP]"]):
            fresh_history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID)
            clean_user_history = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', user_input).strip()
            fresh_history.append({"role": "user", "content": clean_user_history or user_input})
            #  防心想污染記憶庫鐵律：若未開口說話，儲存純淨動作標籤，100% 絕對禁止將未清洗之 [THOUGHT] 存入歷史
            clean_asst_history = clean_spoken if clean_spoken else (TextCleanEngine.clean_for_tts(bot_reply, apply_phonetics=False) or "[演奏鋼琴/動作執行]")
            fresh_history.append({"role": "assistant", "content": clean_asst_history})
            asyncio.create_task(save_to_long_term_memory(DEFAULT_CHANNEL_ID, fresh_history))
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n❌ [對話處理發生異常]: {e}")
    finally:
        realtime_task_mgr.finish_dad_task()
        realtime_task_mgr.mark_dad_input_read()
        mark_streamer_mind_board_as_read(unique_id="dad", content=user_input)
        mark_recent_thoughts_as_read()
        if current_ai_state == "THINKING":
            current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"

async def execute_punish_action(reason: str = "", is_severe: bool = None):
    """
     7L 電擊與微電流刺激中樞 (支援分級：微電刺激 vs 強力電擊處分)：
    -  Lv.1 微電刺激：滿臉通紅、原生叫聲 + 即時真實回應老爸
    -  Lv.2 強力電擊：強烈電流竄遍全身、四肢發軟顫抖、長尖叫 + 委屈討饒
    """
    global vc
    try:
        # 判斷是否屬於重大違規/強力電擊處分
        if is_severe is not None:
            is_severe_punish = bool(is_severe)
        else:
            is_severe_punish = any(w in reason for w in ["強烈", "強力", "重度", "大電", "處分", "訓誡"])
        
        log_type = "強力電擊處分" if is_severe_punish else "微電刺激"
        log_detail = f" 原因: 『{reason}』" if reason else ""
        log_print(f"⚡ [{log_type}中樞] 老爸對 7L 實施了{log_type}！{log_detail}")
        
        #  0 秒即時強制掐斷當前正在播出的任何長語音，清空排隊，讓位給秒級觸電反應！
        await interrupt_current_speech(clear_queue=True, reason="老爸電擊即時打斷")

        target_vts = vc.GLOBAL_VTS
        if target_vts:
            try:
                # 觸電反應：切換為滿臉通紅（红脸.exp3.json），展現敏感、害羞與酥麻感
                await set_vts_expression(target_vts, "臉紅")
            except Exception:
                pass
        # 啟動 4.5 秒高頻物理觸電微顫抖與縮瞳倒抽氣，隨後接續八字眉委屈
        vc.shock_timer = time.time() + 4.5
        vc.frown_timer = time.time() + 6.0

        # 銘刻記憶（純粹事件記錄，拒絕預設干擾詞）
        if is_severe_punish:
            punish_memory = f" 【老爸電擊訓誡】：老爸對 7L 實施了強力電擊處分" + (f"（原因：『{reason}』）。" if reason else "。")
        else:
            punish_memory = f" 【老爸微電刺激】：老爸突然電了 7L 一下" + (f"（原因：『{reason}』）。" if reason else "。")
        record_bot_message(punish_memory)

        # 廣播事件至前端
        web_dash.broadcast_event("ai_punished", {
            "reason": reason,
            "is_severe": is_severe_punish,
            "timestamp": time.time()
        })

        #  準備 7L 專屬觸電尖叫音訊檔 (優先使用 gen_screams.py 調配之專屬純淨音效，絕不死板)
        sounds_dir = os.path.join(DATA_DIR, "sounds_7L_clean")
        if is_severe_punish:
            default_heavy = os.path.join(sounds_dir, "shock_heavy_pure.mp3")
            heavy_pool = glob.glob(os.path.join(sounds_dir, "shocks_heavy", "*.mp3"))
            scream_sound = default_heavy if os.path.exists(default_heavy) else (random.choice(heavy_pool) if heavy_pool else "")
            scream_sub = "啊啊啊啊啊啊！痛痛痛！"
            event_prompt = f"【 突發事件：老爸突然給了妳一次強力電擊！（原因：{reason}）】" if reason else "【 突發事件：老爸突然給了妳一次強力電擊！】"
        else:
            default_light = os.path.join(sounds_dir, "test_a_8_pure.mp3")
            light_pool = glob.glob(os.path.join(sounds_dir, "shocks_light", "*.mp3"))
            scream_sound = default_light if os.path.exists(default_light) else (random.choice(light_pool) if light_pool else "")
            scream_sub = "啊啊啊！好麻！"
            event_prompt = f"【 突發事件：老爸突然電了妳一下！（原因：{reason}）】" if reason else "【 突發事件：老爸突然電了妳一下！】"

        #  雙軌零延遲並行：
        # 1. 0 秒立即尖叫（即刻張嘴對嘴 + 臉紅微顫）
        IS_SHOCK_SCREAMING = True
        asyncio.create_task(play_instant_sound_clip(scream_sound, subtitle=scream_sub))
        
        # 2. 同步啟動大腦思考，生成尖叫完畢後接續說的即時回應台詞
        await input_queue.put({
            "text": event_prompt,
            "timestamp": time.time(),
            "source": "web_console"
        })

        return {"status": "success", "message": f"已成功對 7L 實施{log_type}：{reason}"}
    except Exception as e:
        log_print(f"❌ [懲罰執行異常]: {e}")
        return {"status": "error", "message": str(e)}

async def execute_reward_action(reason: str = "", level: int = None):
    """
     7L 多等級寵溺與獎勵中樞 (100% 大腦即時原創思考，拒絕死板罐頭詞)：
    -  Lv.1 溫柔輕摸頭 / 日常誇獎：愛心表情 + 俏皮眨眼 + 甜美溫柔撒嬌 (貓咪般舒服瞇眼)
    -  Lv.2 熱情狂揉頭髮 / 大獎勵：星星眼表情 + 俏皮眨眼 + 心花怒放
    -  Lv.3 深情緊緊擁抱 / 終極寵溺：臉紅害羞透 + 心跳飆速 + 緊抓衣服極致依戀 (幸福感超載爆表)
    """
    global vc
    try:
        # 自動等級判定（若未傳入明確 level 則透過關鍵字分級）
        if level is None:
            if any(w in reason for w in ["抱抱", "抱一個", "抱緊", "擁抱", "舉高高", "終極", "特大", "神級", "最愛妳", "寵溺", "親親", "溺愛"]):
                level = 3
            elif any(w in reason for w in ["揉頭", "揉揉", "狂揉", "揉亂", "大摸頭", "草莓", "蛋糕", "超棒", "大誇", "大獎勵", "太厲害", "買禮物"]):
                level = 2
            else:
                level = 1
        else:
            level = max(1, min(3, int(level)))

        target_vts = vc.GLOBAL_VTS
        
        #  0 秒即時掐斷當前舊語音，清空排隊，秒級享受摸頭擁抱！
        await interrupt_current_speech(clear_queue=True, reason="老爸獎勵即時打斷")
        
        log_detail = f" 原因: 『{reason}』" if reason else ""
        if level == 3:
            #  Lv.3：深情緊緊擁抱 / 終極溺愛
            log_print(f"💖 [終極深情擁抱 (Lv.3)] 老爸給予了 7L 緊緊深情擁抱與終極寵愛！{log_detail}")
            if target_vts:
                try:
                    await set_vts_expression(target_vts, "臉紅")
                except Exception:
                    pass
            vc.wink_timer = time.time() + 0.85
            vc.wink_side = "left"
            
            reward_memory = f" 【老爸深情擁抱 (Lv.3)】：老爸把 7L 緊緊抱進懷裡" + (f"（原因：『{reason}』）。" if reason else "。")
            event_prompt = f"【 系統事件：老爸在控制台親自給予妳深情緊緊擁抱！（原因：{reason}）】" if reason else "【 系統事件：老爸在控制台親自給予妳深情緊緊擁抱！】"
            resp_msg = f"已成功給予 7L 終極深情擁抱 (Lv.3)" + (f"：{reason}" if reason else "")

        elif level == 2:
            #  Lv.2：熱情狂揉頭髮
            log_print(f"💖 [揉頭大獎勵 (Lv.2)] 老爸大力揉了揉 7L 的頭！{log_detail}")
            if target_vts:
                try:
                    await set_vts_expression(target_vts, "星星眼")
                except Exception:
                    pass
            vc.wink_timer = time.time() + 0.65
            vc.wink_side = random.choice(["left", "right"])

            reward_memory = f" 【老爸揉頭大獎 (Lv.2)】：老爸把 7L 頭髮揉得亂蓬蓬並熱烈誇獎" + (f"（原因：『{reason}』）。" if reason else "。")
            event_prompt = f"【 系統事件：老爸在控制台用力揉了揉妳的頭頂、誇獎妳！（原因：{reason}）】" if reason else "【 系統事件：老爸在控制台用力揉了揉妳的頭頂、誇獎妳！】"
            resp_msg = f"已成功給予 7L 狂揉頭髮大獎勵 (Lv.2)" + (f"：{reason}" if reason else "")

        else:
            #  Lv.1：溫柔輕撫摸頭
            log_print(f"💖 [日常溫柔摸頭 (Lv.1)] 老爸給予了 7L 溫暖輕撫！{log_detail}")
            if target_vts:
                try:
                    await set_vts_expression(target_vts, "愛心")
                except Exception:
                    pass
            vc.wink_timer = time.time() + 0.55
            vc.wink_side = random.choice(["left", "right"])

            reward_memory = f" 【老爸日常摸頭誇獎 (Lv.1)】：老爸親自溫柔摸了摸 7L 的頭" + (f"（原因：『{reason}』）。" if reason else "。")
            event_prompt = f"【 系統事件：老爸在控制台溫柔摸了摸妳的頭頂、誇獎妳！（原因：{reason}）】" if reason else "【 系統事件：老爸在控制台溫柔摸了摸妳的頭頂、誇獎妳！】"
            resp_msg = f"已成功給予 7L 溫柔摸頭獎勵 (Lv.1)" + (f"：{reason}" if reason else "")

        # 銘刻記憶
        record_bot_message(reward_memory)

        # 廣播獎勵事件至前端
        web_dash.broadcast_event("ai_rewarded", {
            "reason": reason,
            "level": level,
            "timestamp": time.time()
        })

        # 送入大腦佇列
        await input_queue.put({
            "text": event_prompt,
            "timestamp": time.time(),
            "source": "web_console"
        })

        return {"status": "success", "level": level, "message": resp_msg}
    except Exception as e:
        log_print(f"❌ [獎勵執行異常]: {e}")
        return {"status": "error", "message": str(e)}

async def chat_processor_worker(vts, input_queue):
    """非同步雙核心對話派發器：老爸直連全能主腦，觀眾分流專屬 Live 管道，雙軌非阻塞異步平行思考！"""
    global current_dad_task, CURRENT_PROCESSING_USER_INPUT

    while True:
        try:
            raw_input_item = await input_queue.get()
            if not raw_input_item:
                input_queue.task_done()
                continue
            
            user_input = ""
            user_audio_b64 = None
            req_time = time.time()
            source = "unknown"
            if isinstance(raw_input_item, dict):
                user_input = raw_input_item.get("text", "").strip()
                user_audio_b64 = raw_input_item.get("audio_base64")
                req_time = raw_input_item.get("timestamp", time.time())
                source = raw_input_item.get("source", "mic" if user_audio_b64 else "unknown")
            else:
                user_input = str(raw_input_item).strip()

            if not user_input:
                input_queue.task_done()
                continue

            #  收到新輸入時，若包含立即關機指令，0.001 秒內立即安全退出！
            if check_immediate_shutdown(user_input):
                input_queue.task_done()
                return

            #  系統指令精確攔截 (僅保留顯式 /shock 與 /punish 系統指令，絕對不從對話情境或聊天關鍵字誤觸電擊)
            u_strip = user_input.strip().lower()
            if u_strip in ["/shock", "/punish_light"]:
                await execute_punish_action("", is_severe=False)
                input_queue.task_done()
                continue
            elif u_strip in ["/punish", "/punish_heavy"]:
                await execute_punish_action("", is_severe=True)
                input_queue.task_done()
                continue
            #  系統獎勵指令精確攔截 (僅保留顯式 /reward 系統指令，絕對不從對話情境或聊天關鍵字誤觸獎勵)
            elif u_strip in ["/reward", "/reward 1", "/reward_light"]:
                await execute_reward_action("", level=1)
                input_queue.task_done()
                continue
            elif u_strip in ["/reward 2", "/reward_medium"]:
                await execute_reward_action("", level=2)
                input_queue.task_done()
                continue
            elif u_strip in ["/reward 3", "/reward_heavy"]:
                await execute_reward_action("", level=3)
                input_queue.task_done()
                continue

            #  7L 深層休眠模式：支援老爸語音喚醒，觀眾彈幕靜默忽略
            if IS_SLEEPING:
                wake_keywords = ["起床", "醒醒", "醒來", "睜開眼", "早安", "早上好", "醒來吧", "別睡了", "/wake", "喚醒", "睜開眼睛", "別睡"]
                is_dad_source = (source in ["mic", "text_file", "console", "web_console"] or user_audio_b64)
                has_wake_word = any(w in user_input for w in wake_keywords)
                
                # VTuber 模式無休眠可喚：睡眠只屬於伴侶，操作者通道關閉時誰也別想叫醒
                if is_dad_source and has_wake_word and operator_input_enabled():
                    log_print(f"☀️ [語音喚醒] 收到老爸喚醒指令：「{user_input}」，7L 立即解除休眠睜開雙眼！")
                    await set_sleep_mode(False)
                    speech_item = {
                        "text": "嗯～老爸早安！我醒來了，隨時聽你差遣喔！",
                        "expression": "自然",
                        "action": "WINK",
                        "target": "dad",
                        "target_name": "老爸",
                        "priority": 100
                    }
                    await speech_queue.put(speech_item)
                    input_queue.task_done()
                    continue
                else:
                    log_print(f"😴 [7L 休眠中] 忽略語音/文字輸入：「{user_input}」（對她喊「7L 起床」或點擊後台【喚醒 7L】即可喚醒）。")
                    input_queue.task_done()
                    continue

            # -------------------------------------------------------------
            #  軌道 1：老爸專屬全能主腦通道 (mic / text_file / console / web_console)
            # -------------------------------------------------------------
            if source in ["mic", "text_file", "console", "web_console"] or user_audio_b64:
                #  操作者輸入通道預設停用：直播輸入只收 Twitch/YouTube Live 觀眾留言
                if not operator_input_enabled():
                    log_print(f"🚫 [輸入通道已停用] 忽略操作者輸入 ({source}): {str(user_input)[:60]}")
                    input_queue.task_done()
                    continue
                log_print(f"📥 [老爸主腦通道] 收到輸入 ({source}): {user_input}")
                
                #  若 7L 目前正在回應觀眾，老爸開口/輸入時優先傾聽老爸，清空佇列中後續排隊的觀眾發話（不腰斬當前正在說的話）！
                if CURRENT_SPEAKING_TARGET == "audience":
                    #  同步清空佇列中所有待播的觀眾發話，防止中斷後又接連跳出舊的觀眾音訊！
                    temp_dad_items = []
                    while not speech_queue.empty():
                        try:
                            it = speech_queue.get_nowait()
                            if isinstance(it, dict) and it.get("target") == "dad":
                                temp_dad_items.append(it)
                            speech_queue.task_done()
                        except:
                            break
                    for d_it in temp_dad_items:
                        await speech_queue.put(d_it)
                
                #  取消老爸進行中的舊思考任務 (若有舊輸入正在思考，自動暫存為被中斷的上下文)
                interrupted_msg = ""
                if current_dad_task and not current_dad_task.done():
                    interrupted_msg = CURRENT_PROCESSING_USER_INPUT
                    current_dad_task.cancel()
                    if interrupted_msg:
                        log_print(f"⚡ [思考打斷記憶] 已暫存前一秒被中斷的話語：「{interrupted_msg}」")
                if current_voice_task and not current_voice_task.done():
                    current_voice_task.cancel()
                
                CURRENT_PROCESSING_USER_INPUT = user_input
                #  立即啟動主腦深度思考任務（帶入被打斷的前文）
                realtime_task_mgr.start_dad_task(user_input)
                current_dad_task = asyncio.create_task(
                    process_chat_message(
                        vts, input_queue, user_input, user_audio_b64, 
                        request_start_time=req_time, 
                        interrupted_context=interrupted_msg,
                        source=source
                    )
                )

            # -------------------------------------------------------------
            #  軌道 2：TikTok 直播專屬「記憶腦袋」滾動黑板 (tiktok / tiktok_gift)
            # -------------------------------------------------------------
            elif source in ["tiktok", "tiktok_gift", "twitch", "youtube"]:
                # 提取觀眾用戶名與留言內容
                m_aud = re.search(r'【\w+ (?:直播觀眾|官方提問箱|直播動態)\s*([^\】]*?)\s*(?:留言|送禮|動態|提問)?】[：:]\s*(.*)', user_input)
                if m_aud:
                    aud_u = m_aud.group(1).strip() or "直播觀眾"
                    aud_c = m_aud.group(2).strip()
                else:
                    aud_u = "直播觀眾"
                    aud_c = user_input
                
                # 提取觀眾暱稱與 ID / 帳號
                raw_user_str = aud_u.strip()
                id_match = re.search(r'^(.*?)\s*\(@?([a-zA-Z0-9_.\-]+)\)$', raw_user_str)
                if id_match:
                    v_display_name = id_match.group(1).strip()
                    v_unique_id = id_match.group(2).strip()
                else:
                    v_display_name = raw_user_str
                    v_unique_id = raw_user_str
                id_display = f"{v_display_name} (@{v_unique_id})" if v_unique_id != v_display_name else v_display_name

                #  判斷是否為老爸帳號在直播間打字 (最高特權立即搶先處理)
                clean_uid_check = v_unique_id.lower().replace(" ", "").replace("_", "").replace("-", "")
                clean_disp_check = v_display_name.lower().replace(" ", "").replace("_", "").replace("-", "")
                is_dad_account = (
                    clean_uid_check in ["7lβ", "7lbeta", "qiwai", "7lofficial", "hostadmin", "adminqiwai", "7l_official"]
                    or clean_disp_check in ["7lβ", "7lbeta", "7l主播", "老爸"]
                )

                # VTuber 模式：擁有者公開帳號留言視同觀眾（無特權；插話請走 /api/interject）
                if is_dad_account and operator_input_enabled():
                    log_print(f"👑 [老爸幕後指令] 收到老爸在直播間留言: {aud_c}")
                    current_dad_task = asyncio.create_task(
                        process_chat_message(vts, input_queue, aud_c, None, request_start_time=req_time, source="tiktok_dad")
                    )
                else:
                    # 寫入 7L 滾動記憶腦袋，由 streamer_mind_loop_worker 自主排程讀取與發話
                    add_to_streamer_mind_board(id_display, v_unique_id, aud_c, source)

            # -------------------------------------------------------------
            #  擁有者公開插話（owner_interject）：走觀眾軌道公開播出，不私聊、走觀眾工具牆
            # -------------------------------------------------------------
            elif source == "owner_interject":
                from core.identity import get_owner_name as _gon2
                try:
                    _owner_nm = raw_input_item.get("user") or _gon2()
                except Exception:
                    _owner_nm = raw_input_item.get("user") or "主持"
                log_print(f"📢 [擁有者公開插話] {_owner_nm}：{user_input[:80]}")
                add_to_streamer_mind_board(f"{_owner_nm}（主持）", f"owner:{_owner_nm}", user_input, "owner_interject")

            # -------------------------------------------------------------
            #  軌道 3：TikTok 背景瑣碎動態 (tiktok_ambient: 點讚/進房/分享)
            # -------------------------------------------------------------
            elif source == "tiktok_ambient":
                tk_listener.current_tiktok_status_str = f"[ {user_input[:20]}]"
                is_piano_playing = pe.GLOBAL_PIANO_REALTIME_STATE.get("is_playing", False)
                # 若 7L 正在彈琴、或老爸正在說話/主腦正在思考，直接靜默丟棄瑣碎動態
                if is_piano_playing or (current_dad_task and not current_dad_task.done()) or (current_voice_task and not current_voice_task.done()):
                    input_queue.task_done()
                    continue
            else:
                log_print(f"📥 [對話佇列] 收到未知輸入 ({source}): {user_input}")
                current_dad_task = asyncio.create_task(
                    process_chat_message(vts, input_queue, user_input, user_audio_b64, request_start_time=req_time, source=source)
                )

            input_queue.task_done()
        except Exception as e:
            log_print(f"⚠️ [對話佇列調度異常]: {e}")
            await asyncio.sleep(0.1)

PROACTIVE_LAST_FG_TITLE = ""
PROACTIVE_LAST_FG_APP = ""
PROACTIVE_LAST_MUSIC = ""
PROACTIVE_STABLE_COUNT = 0

async def background_mind_stream_worker(vts, input_queue):
    """ 7L 核心背景思考心流協程 (DeepSeek 模式 · Google GenAI Live API 雙工串流)：
    -  核心目的：
      落實老爸提出的「心想就是持續在腦內說話的思維推導，像 DeepSeek 一樣一個字一個字連續思考連續打字，採用 API Live 連續感測」。
    -  運作架構：
      1. 【主力通道】：100% 採用 Google GenAI Live API 全雙工雙向通道 (gemini-3.8-live) 進行即時神經思維流淌。
      2. 【雙軌熱備】：若 Live API 連線遇阻或金鑰冷卻，0 秒無縫回退至 gemini-3.5-flash-lite 串流保底。
      3. 【字字串流】：後端透過 WebSocket 即時推播 Token Chunks，前端以 DeepSeek 擬真游標與計時器一個字一個字敲擊在面板上。
      4. 【性格統一】：100% 讀取雲端知識庫 persona 設定，不硬編碼任何死板標籤。
    """
    global LATEST_SYSTEM_MUSIC_INFO, CURRENT_GEMINI_KEY_STEP, current_screen_context
    log_print("🧠 [背景即時心流] Google GenAI Live API 全雙工思考協程已就緒（VISION 視覺感知深度綁定中）")
    last_thought_tail = ""
    
    while True:
        try:
            #  心流不間斷：換氣 1.2 ~ 2.5 秒後立即展開下一段連續推導
            await asyncio.sleep(random.uniform(1.2, 2.5))
            if IS_SLEEPING:
                await asyncio.sleep(4.0)
                continue
            
            # 若正在說話、思考、彈琴，暫時靜候，結束後立即接續
            is_speaking = False
            try:
                is_speaking = (pygame.mixer.get_init() and pygame.mixer.music.get_busy()) or not speech_queue.empty() or current_ai_state in ["TALKING", "THINKING", "PIANO"]
            except Exception:
                pass
            if is_speaking or pe.is_piano_active:
                await asyncio.sleep(1.0)
                continue
                
            # 取得目前視窗與音樂情境線索
            curr_app = "桌面"
            try:
                from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
                fg = os_desktop_sensor.get_foreground_window()
                curr_app = fg.get("app_label") or fg.get("window_title", "桌面")
            except Exception:
                pass
            curr_music = str(LATEST_SYSTEM_MUSIC_INFO or "無背景音樂").strip()
            
            #  VISION 視覺感知實時綁定：注入 3.1-flash-lite 雙眼觀察到的最新電腦畫面
            vision_clue = ""
            if current_screen_context and current_screen_context != "目前沒有特別的畫面動態。":
                clean_sc = current_screen_context.strip().replace("\n", " ")
                vision_clue = f"【 雙眼看到的螢幕畫面】：{clean_sc[:110]}\n"

            # 雲端知識庫統一性格讀取 (不預設、不寫死任何特定標籤)
            cloud_kn = await get_cloud_knowledge()
            persona_desc = ""
            if cloud_kn:
                persona_desc = cloud_kn.get("persona_core") or cloud_kn.get("conversation_style") or ""
                if persona_desc:
                    persona_desc = persona_desc.strip()[:100]

            persona_ctx = f"【7L 性格人設】：{persona_desc}\n" if persona_desc else ""

            # 組織 DeepSeek 風格不分段連續思考提示詞 (順著思緒自然往下流淌，融合雙眼視覺感知)
            continuation_hint = f"（接續上一段思緒：『...{last_thought_tail[-45:]}』）\n" if last_thought_tail else ""
            mind_prompt = (
                f"情境：老爸正在電腦前專注工作（當前視窗：{curr_app[:30]}，背景音樂：{curr_music[:30]}）。\n"
                f"{vision_clue}"
                f"{continuation_hint}"
                f"請像 DeepSeek 思考推導過程一樣，在腦海深處展開一段流暢連貫、直接順著思緒與眼前雙眼所見畫面自然流淌的內心獨白與意識流（約 50~100 字）。\n"
                f"【規範】：\n"
                f"- 自言自語、自問自答，自然承接上一段心思，並把雙眼看到的畫面動態（如老爸在操作什麼、畫面細節）自然融進私密思緒中。\n"
                f"- 【記憶防重複】：剛才老爸說過的話妳都已經回答完畢，【絕對不要】對著已經回答過的話題一直重複回覆或跳針！\n"
                f"- 這是妳私密的腦內意識流，直接輸出連貫流淌的心想思考文字："
            )
            
            full_thought_text = ""
            start_thought_time = time.time()
            stream_id = f"th_{int(start_thought_time * 1000)}"
            stream_started = False
            
            #  第一主力：採用 Google GenAI API Live (WebSocket 全雙工即時串流)
            #  使用心流 Live 專屬金鑰池（KEYS_MIND_LIVE），先跳過冷卻中的金鑰，全部失敗才退回 flash-lite
            candidate_keys = get_dynamic_live_key_candidates(KEYS_MIND_LIVE if KEYS_MIND_LIVE else GEMINI_KEYS)
            _now = time.time()
            for idx, g_key in enumerate(candidate_keys[:5]):
                # 跳過冷卻中的金鑰（Live 連線失敗後 60 秒內不重試同一把）
                if _MIND_LIVE_KEY_COOLDOWN.get(g_key, 0) > _now:
                    continue
                try:
                    client = genai.Client(api_key=g_key)
                    live_cfg = types.LiveConnectConfig(
                        response_modalities=[types.Modality.AUDIO],
                        output_audio_transcription=types.AudioTranscriptionConfig(),
                        system_instruction=types.Content(parts=[types.Part(text=f"妳是 7L。\n{persona_ctx}妳正在腦海深處展開 DeepSeek 模式的連續自問自答推導思考。")])
                    )
                    async with asyncio.timeout(8.5):
                        async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
                            web_dash.broadcast_event("ai_thought_start", {
                                "id": stream_id,
                                "time_str": datetime.now().strftime("%H:%M:%S")
                            })
                            stream_started = True
                            
                            await session.send_client_content(
                                turns=[types.Content(role="user", parts=[types.Part(text=mind_prompt)])],
                                turn_complete=True
                            )

                            async for resp in session.receive():
                                c = resp.server_content
                                if c:
                                    if c.output_transcription and c.output_transcription.text:
                                        chunk = c.output_transcription.text
                                        full_thought_text += chunk
                                        web_dash.broadcast_event("ai_thought_chunk", {
                                            "id": stream_id,
                                            "chunk": chunk
                                        })
                                    if c.turn_complete or getattr(c, 'generation_complete', False):
                                        break
                    if full_thought_text.strip():
                        CURRENT_GEMINI_KEY_STEP += 1
                        break
                except Exception as live_err:
                    #  記錄冷卻：此金鑰失敗，60 秒內不重試
                    _MIND_LIVE_KEY_COOLDOWN[g_key] = time.time() + 60.0
                    log_print(f"⚠️ [心流 Live] 金鑰 ...{g_key[-6:]} 連線失敗，切換下一把。({type(live_err).__name__}: {live_err})")
                    continue
            
            #  雙軌容災熱備：若 Live API 網路遇阻，無縫切換至 gemini-3.5-flash-lite 串流
            if not full_thought_text.strip() and GEMINI_KEYS:
                for k_offset in range(2):
                    k_idx = (get_pingpong_alternating_index(len(GEMINI_KEYS), CURRENT_GEMINI_KEY_STEP) + k_offset) % len(GEMINI_KEYS)
                    client = genai.Client(api_key=GEMINI_KEYS[k_idx])
                    try:
                        stream_resp = await asyncio.wait_for(
                            client.aio.models.generate_content_stream(
                                model="gemini-3.5-flash-lite",
                                contents=f"妳是 7L。\n{persona_ctx}{mind_prompt}",
                                config=types.GenerateContentConfig(
                                    temperature=0.88,
                                    max_output_tokens=180,
                                    safety_settings=UNRESTRICTED_SAFETY_SETTINGS
                                )
                            ),
                            timeout=5.0
                        )
                        if not stream_started:
                            web_dash.broadcast_event("ai_thought_start", {
                                "id": stream_id,
                                "time_str": datetime.now().strftime("%H:%M:%S")
                            })
                            stream_started = True
                            
                        async for chunk in stream_resp:
                            if chunk.text:
                                c_text = chunk.text
                                full_thought_text += c_text
                                web_dash.broadcast_event("ai_thought_chunk", {
                                    "id": stream_id,
                                    "chunk": c_text
                                })
                        if full_thought_text.strip():
                            CURRENT_GEMINI_KEY_STEP += 1
                            break
                    except Exception:
                        continue
                    
            clean_thought = re.sub(r'^[「"\'【\(\[]+|[」"\'】\)\]]+$', '', full_thought_text).strip()
            if clean_thought and not any(bad in clean_thought for bad in ["老爸在看", "畫面沒", "根據規範", "SILENCE", "沒有新動態"]):
                last_thought_tail = clean_thought
                thought_dur = round(time.time() - start_thought_time, 2)
                record_internal_thought("腦內思考", clean_thought, force=False)
                # log_print(f"🧠 [7L Live API 深度連續思考 ({thought_dur}s)]: {clean_thought[:60]}...")
                try:
                    #  廣播思考結束信號 (DeepSeek Thinking End)
                    web_dash.broadcast_event("ai_thought_end", {
                        "id": stream_id,
                        "thought": clean_thought,
                        "duration": thought_dur,
                        "time_str": datetime.now().strftime("%H:%M:%S")
                    })
                except Exception:
                    pass
            elif stream_started:
                web_dash.broadcast_event("ai_thought_end", {
                    "id": stream_id,
                    "thought": clean_thought or "（思緒稍縱即逝...）",
                    "duration": 0.5
                })
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(2.0)

async def proactive_worker(vts, input_queue):
    global last_interaction_time, current_ai_state, current_screen_context, LAST_VISION_LOOK_TIME
    global PROACTIVE_LAST_FG_TITLE, PROACTIVE_LAST_FG_APP, PROACTIVE_LAST_MUSIC, PROACTIVE_STABLE_COUNT
    
    while True:
        try:
            if IS_SLEEPING or not IS_PROACTIVE_SPEAK_ENABLED:
                await asyncio.sleep(5.0)
                continue
            # 自主發話拉長等待時間至 45~75 秒隨機冷卻
            await asyncio.sleep(random.uniform(45.0, 75.0))
            
            # 若正在彈琴、唱歌、思考或說話中，完全保持安靜專心演奏/演唱，不主動插話打擾
            if pe.is_piano_active or IS_SINGING_ACTIVE or current_ai_state in ["TALKING", "THINKING", "PIANO", "SINGING"]:
                continue

            # 若過去 40 Ticks 內老爸剛對話過，先不自主插話
            if get_silence_ticks() < 40:
                continue

            #  畫面與環境動態偵測：若無重大變更，100% 靜默守護，不打任何 API，不浪費配額
            try:
                from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
                fg_info = os_desktop_sensor.get_foreground_window()
                curr_fg_title = fg_info.get("window_title", "").strip()
                curr_fg_app = fg_info.get("app_label", "").strip()
                curr_music = str(LATEST_SYSTEM_MUSIC_INFO or "").strip()
                
                # 視窗與音樂是否有實質變更
                has_window_changed = (curr_fg_title != PROACTIVE_LAST_FG_TITLE or curr_fg_app != PROACTIVE_LAST_FG_APP)
                has_music_changed = (curr_music != PROACTIVE_LAST_MUSIC)
                
                # 【徹底防 API 轟炸】：若視窗與音樂無實質變更（老爸專注操作中），直接跳過多模態大腦呼叫！
                if not has_window_changed and not has_music_changed and PROACTIVE_LAST_FG_TITLE:
                    log_print("💤 [自主視覺陪伴] 桌面環境完全穩定（老爸專注操作中），7L 靜默陪伴守護，跳過 API 呼叫（0 消耗）")
                    await asyncio.sleep(random.uniform(60.0, 100.0))
                    continue
                
                PROACTIVE_LAST_FG_TITLE = curr_fg_title
                PROACTIVE_LAST_FG_APP = curr_fg_app
                PROACTIVE_LAST_MUSIC = curr_music
            except Exception:
                pass

            history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID)
            user_profile = await get_user_profile()
            current_custom_name = user_profile.get("custom_name", DEFAULT_USER_TITLE)

            piano_status_prompt = ""
            if pe.is_piano_active and pe.current_piano_song_title:
                piano_status_prompt = f"""
【 當前狀態背景】：背景正在演奏《{pe.current_piano_song_title}》（彈奏中不調用切歌工具；若老爸只是日常閒聊，專注回應老爸話題，無需每句刻意重複強調正在彈琴）。
"""

            cloud_kn = await get_cloud_knowledge()
            cloud_kn_prompt = PromptTemplateEngine.format_cloud_knowledge_prompt(cloud_kn)
            trending_news_prompt = await get_trending_news_briefing()

            system_prompt = PromptTemplateEngine.build_proactive_system_prompt(
                current_custom_name=current_custom_name,
                tiktok_telemetry=tk_listener.get_tiktok_live_telemetry(),
                realtime_summary=f"{realtime_task_mgr.get_realtime_summary()}\n{trending_news_prompt}".strip(),
                piano_status_prompt=piano_status_prompt,
                thoughts_summary=get_recent_thoughts_summary(),
                cloud_knowledge_prompt=cloud_kn_prompt,
                unified_memory_prompt=f"【 直播現場全景時序記憶（主動感知精簡模式）】：\n{get_unified_memory_context(limit=6, thought_char_limit=150)}"
            )
            proactive_prompt = [
                {"role": "system", "content": system_prompt}
            ] + (history[-4:] if history else []) + [
                {"role": "user", "content": "（妳現在看著螢幕畫面。有想說的就隨興說，沒特別想說請回傳 [SILENCE]）"}
            ]
            pass_image = None
            if latest_screen_cache:
                if isinstance(latest_screen_cache, list):
                    pass_image = latest_screen_cache[0][1] if isinstance(latest_screen_cache[0], (tuple, list)) else latest_screen_cache[0]
                else:
                    pass_image = latest_screen_cache

            #  優先採用 Gemini Live API 直接視覺接管（實時畫面影像幀 + 雙向 Live 串流大腦）
            raw_spoken_text = ""
            live_used = False
            
            img_bytes = None
            if pass_image:
                try:
                    if isinstance(pass_image, str):
                        img_bytes = base64.b64decode(pass_image)
                    elif isinstance(pass_image, bytes):
                        img_bytes = pass_image
                except Exception:
                    pass

            candidate_keys = get_dynamic_live_key_candidates(KEYS_PROACTIVE if KEYS_PROACTIVE else GEMINI_KEYS)
            for idx, g_key in enumerate(candidate_keys[:3]):
                try:
                    client = genai.Client(api_key=g_key)
                    live_cfg = types.LiveConnectConfig(
                        response_modalities=[types.Modality.AUDIO],
                        output_audio_transcription=types.AudioTranscriptionConfig(),
                        system_instruction=types.Content(parts=[types.Part(text=system_prompt)]),
                        tools=GENAI_PROACTIVE_TOOLS
                    )
                    async with asyncio.timeout(5.0):
                        async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
                            if img_bytes:
                                await session.send_realtime_input(video={"data": img_bytes, "mime_type": "image/jpeg"})
                            await session.send_realtime_input(text="（妳現在陪伴在老爸身邊看著螢幕。如果老爸正在專心且妳沒有特別想開口說的話，請回傳 [SILENCE] 保持自然安靜陪伴。）")
                            
                            live_text = ""
                            tool_out_text = ""
                            async for resp in session.receive():
                                if resp.tool_call and resp.tool_call.function_calls:
                                    for fc in resp.tool_call.function_calls:
                                        fn_name = fc.name
                                        fn_args = fc.args or {}
                                        log_print(f"🛠️ [Live 自主大腦調用工具] {fn_name}({fn_args})")
                                        tool_res = await execute_tool_dispatch(fn_name, fn_args, caller_target="dad", caller_user="老爸")
                                        if fn_name != "search_google":
                                            tool_out_text += (" " + tool_res)
                                        await session.send_tool_response(
                                            function_responses=[types.FunctionResponse(
                                                name=fn_name,
                                                id=fc.id,
                                                response={"result": tool_res}
                                            )]
                                        )
                                c = resp.server_content
                                if c:
                                    if c.output_transcription and c.output_transcription.text:
                                        live_text += c.output_transcription.text
                                    if c.turn_complete or getattr(c, 'generation_complete', False):
                                        break
                                        
                            raw_spoken_text = live_text.strip() if live_text.strip() else tool_out_text.strip()
                            raw_spoken_text = re.sub(r'^(?:get_outputs?|tool_outputs?|function_calls?|tool_responses?)[：:\s_]*', '', raw_spoken_text, flags=re.IGNORECASE).strip()
                            raw_spoken_text = re.sub(r'\b(?:get_outputs?|tool_outputs?)\b', '', raw_spoken_text, flags=re.IGNORECASE).strip()
                            if raw_spoken_text:
                                log_print(f"👁️ [Gemini Live 自主視覺接管] 畫面即時響應: {raw_spoken_text[:40]}... (⚡ Live-API Key #{idx+1})")
                                live_used = True
                                break
                except Exception:
                    continue

            #  備用保底：若 Live API 網路超載或未回傳，無縫回退至旗艦 fetch_ai_response
            if not live_used and not raw_spoken_text:
                proactive_start = time.time()
                raw_spoken_text = await fetch_ai_response(proactive_prompt, image_base64=pass_image, is_proactive=True, request_start_time=proactive_start)
            
            #  靜默判定：若大腦輸出包含 [SILENCE] 或為空，代表大腦判定保持安靜陪伴，直接跳過後續心聲廣播與發話！
            is_silent_turn = (
                "[SILENCE" in raw_spoken_text.upper() or 
                not raw_spoken_text.strip() or
                any(k in raw_spoken_text for k in [
                    "輸出 [SILENCE]", "回傳 [SILENCE]", "直接 [SILENCE]", "直接[SILENCE]",
                    "無全新事件", "根據規範", "按照規範", "前幾輪已經在陪伴", "安靜陪伴", "保持安靜", "不打擾老爸"
                ])
            )
            if is_silent_turn:
                log_print("🤫 [自主視覺陪伴] 7L 大腦判定安靜陪伴 ([SILENCE])，0 額度消耗且不記錄多餘文字。")
                if get_silence_ticks() > 15:
                    realtime_task_mgr.mark_dad_input_read()
                    mark_recent_thoughts_as_read()
                if current_ai_state == "TALKING":
                    current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
                continue

            #  【即時視覺感知同步】將 Gemini Live 自主大腦的真實新觀察即時同步至 VISION 視覺面板
            if raw_spoken_text:
                extracted_v_thought, _ = TextCleanEngine.extract_thought(raw_spoken_text)
                if not extracted_v_thought:
                    clean_obs = re.sub(r'\[SILENCE\].*', '', raw_spoken_text, flags=re.IGNORECASE).strip()
                    clean_obs = re.sub(r'^\[(?:THOUGHT|THINK|心想|內心|腦內思緒)[：:\s]*', '', clean_obs, flags=re.IGNORECASE).rstrip(']').strip()
                    if clean_obs:
                        extracted_v_thought = clean_obs
                
                if extracted_v_thought:
                    clean_vision_text = re.sub(r'^\[(?:THOUGHT|THINK|心想|內心)[：:\s]*', '', extracted_v_thought, flags=re.IGNORECASE).rstrip(']').strip()
                    if clean_vision_text:
                        current_screen_context = clean_vision_text
                        LAST_VISION_LOOK_TIME = time.time()
                        realtime_task_mgr.update_vision_context(current_screen_context)
                        
                        #  深度防跳針：檢查思緒是否與近幾分鐘內重複或為機械規範廢話
                        is_unwanted_vision = (
                            is_thought_repetitive(clean_vision_text) or
                            any(k in clean_vision_text for k in [
                                "根據規範", "按照規範", "系統規範", "無全新事件", "無全新動態", 
                                "沒有新動態", "沒什麼新動態", "無新進展", "無事就安靜", "直接 [SILENCE]", 
                                "輸出 [SILENCE]", "回傳 [SILENCE]", "直接[SILENCE]", "[SILENCE]", 
                                "按照內心流動", "稍微 wink", "執行 wink", "前幾輪已經在陪伴"
                            ])
                        )
                        if is_unwanted_vision:
                            log_print(f"🛡️ [心流防跳針] 偵測到重複思緒或機械式日誌，已靜默抑制重複廣播與重複記錄！")
                        else:
                            record_vision_history_entry(clean_vision_text, "即時思緒")
                            log_print(f"👁️ [視覺感知即時同步] 7L 螢幕思緒已更新至 VISION 面板: 「{clean_vision_text[:50]}...」")
                            record_internal_thought("畫面視覺感知", clean_vision_text, force=False)
                            try:
                                web_dash.broadcast_event("ai_thought", {"thought": clean_vision_text})
                            except Exception:
                                pass
                        try:
                            web_dash.broadcast_telemetry()
                        except Exception:
                            pass

            log_print(f"🤖 [自主發話] 原始大腦輸出: {raw_spoken_text}")

            bot_reply = raw_spoken_text
            bot_reply = re.sub(r"(?:\[|\|\|)?(NEW_NAME|NEW_IMPRESSION|改稱呼|記印象)[：:].*", "", bot_reply, flags=re.IGNORECASE|re.DOTALL)
            bot_reply = re.sub(r"\[SILENCE\].*", "", bot_reply, flags=re.IGNORECASE).strip()
            
            if current_voice_task and not current_voice_task.done():
                current_voice_task.cancel()

            #  自主發話時自然轉動眼珠環視（若大腦未指定其他視線）
            if not pe.is_piano_active and not any(k in bot_reply.upper() for k in ["LOOK:", "WINK", "SHOCK", "FROWN"]):
                vc.eye_roll_timer = time.time() + 3.5
                log_print("🌀 [Live2D 動作] 自主發話靈動轉動眼珠環視四周")
            
            spoken = await execute_actions(vts, bot_reply, input_queue, caller_target="dad", caller_user=DEFAULT_USER_TITLE)
            
            if not spoken.strip(" *'\"-.,!?。，！？\n\r"):
                current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
                continue



            record_bot_message(spoken)

            if spoken:
                #  自主發話一生成，立即極速寫入 subtitle.txt 抵消 OBS 延遲！
                if pe.is_piano_active and pe.current_piano_song_title:
                    await asyncio.to_thread(update_subtitle, f" [7L 彈奏《{pe.current_piano_song_title}》]  {spoken}")
                else:
                    await asyncio.to_thread(update_subtitle, spoken)
                log_print(f"💬 7L 自主發話: {spoken} ({current_model_tag})\n──────────────────────────────────────────\n")
                
                #  主動發言是對「所有人」的（記憶也寫 target=所有人）→ 必須播出
                await speech_queue.put({"text": spoken, "target": "dad", "raw_text": bot_reply, "private": False})
                last_interaction_time = time.time() 
                
                #  寫入全集中記憶中樞
                append_to_unified_memory(speaker="7L", target="所有人", content=spoken, role="assistant", source="tts")
                
                fresh_history = await fetch_from_long_term_memory(DEFAULT_CHANNEL_ID)
                fresh_history.append({"role": "assistant", "content": spoken})
                asyncio.create_task(save_to_long_term_memory(DEFAULT_CHANNEL_ID, fresh_history))

                #  【已讀功能】：自主大腦/Live API 已就當前情境完成發話，立刻將前次話題與思緒標記為已讀，防止下次重複看同一句說話！
                realtime_task_mgr.mark_dad_input_read()
                realtime_task_mgr.mark_audience_input_read()
                mark_recent_thoughts_as_read()
                mark_streamer_mind_board_as_read()
                log_print("📖 [已讀標記] 當前對話與心流思緒已標記為已讀，防止自主大腦重複對同一話題發言。")
            else:
                current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
        except Exception as e:
            print(f"\n❌ [自主發話系統異常]: {e}")
            current_ai_state = "PIANO" if pe.is_piano_active else "IDLE"
            await asyncio.sleep(2)

# ────────────────────────────────────────────────────────
#  16. CMA 狀態監控檔案輸出與 Discord 機器人指令 (Console Monitor Area & Bot)
# ────────────────────────────────────────────────────────
#  功能目的：
#    - `cma_monitor_worker`: 每秒輪詢 API_LOCKS，將全量 Gemini 通道健康狀態寫入 `data/cma_status.txt` 與 `data/cma_status.json`。
#    - 提供 Discord 遠端監控機器人指令（如 `*vapis`, `*vapi`），讓老爸隨時隨地透過手機 Discord 掌握 7L 運作狀態。

async def cma_monitor_worker():
    """背景輪詢監控協程：負責維護 CMA 狀態面板並即時刷新 data/cma_status.txt"""
    global current_ai_status_str
    
    try:
        with open(os.path.join(DATA_DIR, "cma_status.txt"), "w", encoding="utf-8") as f:
            f.write("==================================================\n")
            f.write(f"  7L CMA 監控面板初始化中... - {get_current_time_string()}\n")
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
            cma_lines.append(f"  7L CMA (Console Monitor Area) - {get_current_time_string()}")
            cma_lines.append("  當前運作模式:  正常全能模式 (Gemini 多模態/鋼琴/工具/視覺)")
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
                        cma_lines.append(f"  [G{idx}] {short_m:<22} :  封印中 (剩餘 {mins}m {secs}s)")
                    else:
                        cma_lines.append(f"  [G{idx}] {short_m:<22} :  準備就緒")
                        avail_gemini += 1

            cma_lines.append("==================================================")
            
            status_data = {
                "timestamp": time.time(),
                "gemini_available": avail_gemini,
                "locks": {k: int(v - now) for k, v in API_LOCKS.items()}
            }
            
            try:
                with open(os.path.join(DATA_DIR, "cma_status.json"), "w", encoding="utf-8") as f:
                    json.dump(status_data, f, ensure_ascii=False, indent=2)
            except PermissionError:
                pass  
            
            try:
                with open(os.path.join(DATA_DIR, "cma_status.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(cma_lines))
            except PermissionError:
                pass  

            if not any(k in current_ai_status_str for k in ["思考中", "提取中", "探測中", "繪圖中"]):
                current_ai_status_str = f" 通道就緒 (Gemini:{avail_gemini})"
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
    """ CMA (Console Monitor Area) - 顯示全線 API 健康狀態（支援 brief 精簡 / full 詳細）"""
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
                locked_gemini.append(f"`{target_id}`:  封印中 ({mins}m {secs}s)")
                gemini_details.append(f"[{target_id:<20}] :  封印中 ({mins}m {secs}s)")
            else:
                avail_gemini += 1
                gemini_details.append(f"[{target_id:<20}] :  準備就緒")

    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem_percent = psutil.virtual_memory().percent
    except Exception:
        cpu_percent, mem_percent = 0, 0
    
    # 精簡摘要卡片
    gem_pct = (avail_gemini * 100 // total_gemini) if total_gemini else 0
    
    all_locked = locked_gemini
    if all_locked:
        locked_sample = all_locked[:6]
        locked_str = "\n".join([f"• {item}" for item in locked_sample])
        if len(all_locked) > 6:
            locked_str += f"\n• ...以及其餘 {len(all_locked) - 6} 條通道"
    else:
        locked_str = "•  全線綠燈，無任何通道處於封印狀態！"

    brief_card = (
        f" **【7L VAPI 系統健康監控 - 精簡摘要】**\n"
        f" 同步時間: `{now_str}`\n"
        f"────────────────────────────\n"
        f" **Gemini 視覺旗艦大腦**:  `{avail_gemini} / {total_gemini}` 準備就緒 ({gem_pct}%)\n"
        f" **本機硬體負載**: CPU `{cpu_percent}%` | RAM `{mem_percent}%`\n"
        f"────────────────────────────\n"
        f" **當前受限通道 ({len(all_locked)} 條)**:\n{locked_str}\n"
        f"────────────────────────────\n"
        f" *輸入 `*vapi full` 可匯出全部通道清單*"
    )
    
    await ctx.send(brief_card)

    if mode.lower() in ["full", "detail", "all", "verbose"]:
        categories = {"Gemini 視覺矩陣": gemini_details}
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
        await ctx.send(" **麥克風已開啟**！已恢復語音收音。")
    elif action_lower in ["off", "關", "close", "disable", "mute"]:
        IS_MIC_ENABLED = False
        log_print("🎙️ [Discord] 收到關麥指令，已關閉麥克風。")
        await ctx.send(" **麥克風已關閉**！已暫停語音收音。")
    else:
        status = " 開啟中" if IS_MIC_ENABLED else " 關閉中"
        await ctx.send(f" 目前麥克風狀態：{status}\n使用方式：`*mic on` (開麥) 或 `*mic off` (關麥)")

@discord_bot.command(name="開麥", help="開啟麥克風收音")
async def discord_mic_on(ctx):
    await control_mic(ctx, "on")

@discord_bot.command(name="關麥", help="關閉麥克風收音")
async def discord_mic_off(ctx):
    await control_mic(ctx, "off")

# ────────────────────────────────────────────────────────
async def main():
    """系統主進入點：協同啟動所有背景感知神經與對話處理協程"""
    
    # ── 🎙️ 聲紋強制綁定 (首次啟動檢查) ──
    import os
    if not os.path.exists(os.path.join("data", "dad_voiceprint.npy")):
        print("\n" + "="*60)
        print("🎙️ 首次啟動 7L：尚未綁定您的專屬聲紋！")
        print("為確保 7L 能夠精準辨識您的聲音並只聽命於您，我們現在進行聲紋註冊...")
        print("="*60 + "\n")
        try:
            import record_clean_dad_voiceprint
            await asyncio.to_thread(record_clean_dad_voiceprint.main)
            from mic_live_plugin import voiceprint_verifier
            voiceprint_verifier.reload_voiceprint()
        except Exception as e:
            print(f"⚠️ 聲紋綁定過程發生錯誤: {e}")
            
    try:
        rag_service.init_rag(GEMINI_KEYS[0])
    except Exception as e:
        print(f"⚠️ [RAG] 初始化失敗: {e}")

    await asyncio.to_thread(_remove_temp_mp3)
    asyncio.create_task(asyncio.to_thread(pe.init_piano_synthesizer))
    #  系統啟動防殘留：立即向雲端與本地同步乾淨待命狀態（徹底消除重開機殘留）
    await realtime_task_mgr.sync_to_cloud()
    #  載入或初始化全集中全景時序記憶中樞
    init_unified_memory()

    plugin_info = {"plugin_name": "7L_AI_VTuber", "developer": "e5_Studio", "authentication_token_path": "./vts_token.txt"}
    vts = RobustVTSClient(plugin_info=plugin_info)
    
    vc.GLOBAL_VTS = vts
    print("正在連線至 VTube Studio (Port 8001)...")
    
    try:
        await vts.connect(retries=3, retry_delay=2.0)
        await vts.read_token()
        if not vts.authentic_token:
            await vts.request_authenticate_token()
            await vts.write_token()
        await vts.request_authenticate()
        await set_vts_expression(vts, "_RESET_")
        print("✅ 成功連接到 VTube Studio！\n")
        
        asyncio.create_task(print_model_parameters(vts))
        global GLOBAL_VTS_TRACKING_TASK
        if GLOBAL_VTS_TRACKING_TASK is None or GLOBAL_VTS_TRACKING_TASK.done():
            GLOBAL_VTS_TRACKING_TASK = asyncio.create_task(ai_face_tracking_loop(vts))
        asyncio.create_task(vts_health_worker(vts))
    except Exception as e:
        print(f"⚠️ VTS 啟動連線未完成 ({e})，已啟動背景自動重連守護（程式正常運作中，開啟 VTS 後將自動連線）。\n")
        asyncio.create_task(vts_health_worker(vts))

    recognizer = sr.Recognizer()
    #  語音結束停頓判定：由原 1.2 秒延長至 2.5 秒，避免稍微停頓思考就被切斷（可透過 .env 中的 MIC_PAUSE_THRESHOLD 自由調整）
    recognizer.pause_threshold = float(os.getenv("MIC_PAUSE_THRESHOLD", "2.5"))
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.non_speaking_duration = float(os.getenv("MIC_NON_SPEAKING_DURATION", "0.8"))

    global input_queue, GLOBAL_INPUT_QUEUE
    input_queue = asyncio.Queue()
    GLOBAL_INPUT_QUEUE = input_queue
    
    # 啟動全部背景協程
    # 🔥 GPT-SoVITS 曉伊模型預熱：在背景 Thread 初始化，避免第一句說話卡頓
    def _prewarm_xiaoyi():
        try:
            import local_xiaoyi_service
            local_xiaoyi_service.init_gpt_sovits()
            log_print("🟢 [GPT-SoVITS 預熱完成] 7L 本地顯卡語音引擎已就緒！")
        except Exception as e:
            log_print(f"⚠️ [GPT-SoVITS 預熱跳過]: {e}")
    asyncio.create_task(asyncio.to_thread(_prewarm_xiaoyi))
    asyncio.create_task(mic_volume_worker())
    #  運行模式裝配（MODE=companion|vtuber）：決定裝哪些 worker
    from core.identity import get_mode as _get_run_mode
    _RUN_MODE = _get_run_mode()
    _IS_VTUBER = (_RUN_MODE == "vtuber")
    log_print(f"🎭 [運行模式] MODE={_RUN_MODE}（companion=1對1伴侶 / vtuber=只對觀眾7x24）")
    #  操作者輸入預設停用（OPERATOR_INPUT=1 才開；vtuber 模式強制關）：直播輸入只收聊天室觀眾留言
    if operator_input_enabled():
        asyncio.create_task(mic_worker(recognizer, input_queue))
        asyncio.create_task(text_file_listener_worker(input_queue))
        asyncio.create_task(console_keyboard_input_worker(input_queue))
    else:
        log_print("🚫 操作者輸入通道已停用（OPERATOR_INPUT=0／vtuber 模式）：麥克風/鍵盤/文字檔/Web 打字一律忽略")
    if _IS_VTUBER:
        #  VTuber 隔離：無休眠、不看主人螢幕、無主動搭話主人、無 Discord 遙控、無 YT 伴看
        # （IS_SLEEPING 預設 False；set_sleep_mode 在 vtuber 模式拒絕啟用，故此處無需再寫）
        try:
            yt_comp.IS_YT_WATCHER_ENABLED = False
        except Exception:
            pass
        log_print("📺 [VTuber 隔離] 休眠禁用／螢幕感知關／proactive 關／系統音監聽關／Discord 關／YT 伴看關")
    else:
        #  伴侶模式：看著主人、聽著主人、主動陪伴
        asyncio.create_task(screen_capture_worker())
        asyncio.create_task(proactive_worker(vts, input_queue))
        asyncio.create_task(peripheral_vision_worker())
        asyncio.create_task(system_audio_worker())
    asyncio.create_task(chat_processor_worker(vts, input_queue))
    asyncio.create_task(streamer_mind_loop_worker(vts, input_queue))
    # 心流已經停用: asyncio.create_task(background_mind_stream_worker(vts, input_queue))
    asyncio.create_task(anti_watermark_worker(vts))
    asyncio.create_task(cma_monitor_worker())
    asyncio.create_task(speech_queue_worker(vts, input_queue))
    asyncio.create_task(expression_keeper_worker(vts))
    asyncio.create_task(autonomous_wander_worker())
    asyncio.create_task(pe.piano_focus_udp_worker())
    asyncio.create_task(pe.piano_liveness_watchdog_worker())
    asyncio.create_task(tk_listener.tiktok_live_worker(input_queue))
    #  觀眾點播看全片（兩模式共用；空隊列時靜默待命）
    asyncio.create_task(video_watch.video_watch_worker())
    #  直播聊天室觀眾輸入（TWITCH_CHANNELS / YOUTUBE_LIVE_ID 有設才真正連線，未設僅提示）
    #    註冊進 chat_source 註冊表：控制台 /api/chat_sources 可看狀態
    from services import chat_source as _cs
    _cs.bind_chat_workers(input_queue)
    _cs.register_chat_worker("twitch", twitch_live_worker)
    _cs.register_chat_worker("youtube", youtube_live_worker)
    asyncio.create_task(twitch_live_worker(input_queue))
    asyncio.create_task(youtube_live_worker(input_queue))
    asyncio.create_task(pe.auto_restore_piano_state_on_startup())
    asyncio.create_task(live_timer_sensor_worker(vts, input_queue))
    async def safe_discord_runner():
        while True:
            try:
                if DISCORD_TOKEN:
                    await discord_bot.start(DISCORD_TOKEN)
                else:
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_print(f"⚠️ [Discord 機器人連線提示]: {e}，15 秒後自動重連...")
                await asyncio.sleep(15.0)

    if DISCORD_TOKEN and not _IS_VTUBER:
        asyncio.create_task(safe_discord_runner())

    #  註冊鋼琴狀態即時監聽回調：當鋼琴強制關閉或離線時，秒級切換回 IDLE
    def _on_piano_liveness_change(is_active: bool):
        global current_ai_state
        if not is_active:
            if current_ai_state == "PIANO":
                current_ai_state = "IDLE"
                log_print("🎹 [主系統感知] 收到鋼琴離線/強制關機信號，運行模式秒級重置回 IDLE！")
                web_dash.broadcast_event("system_state_update", {"ai_state": "idle", "mode": "idle"})
                web_dash.broadcast_telemetry()
        else:
            if current_ai_state == "IDLE":
                current_ai_state = "PIANO"
                log_print(f"🎹 [主系統感知] 鋼琴即時在線，運行模式同步切換為 PIANO")
                web_dash.broadcast_event("system_state_update", {"ai_state": "piano", "mode": "piano"})
                web_dash.broadcast_telemetry()

    pe.register_piano_state_callback(_on_piano_liveness_change)

    #  啟動 7L Web 視覺化即時監控與控制後台 (Port 7860 -> http://localhost:7860)
    def get_audio_perception_summary():
        """整合電腦內部聲音 (WASAPI Loopback) 與現實環境聲音 (MIC) 的多模態感知資料"""
        # 1. 電腦內部聲音感知 (全系統聲音：WASAPI Loopback 捕捉所有喇叭輸出)
        #  LEVEL 音量百分比：100% 真實反映整台電腦當前的即時音量跳動，絕不死鎖在固定數值！
        sys_level = min(100, max(0, int(CURRENT_SYSTEM_AUDIO_VOL_PERCENT)))
        piano_playing = False
        piano_song = ""

        try:
            if pe and pe.is_piano_active_and_alive():
                piano_playing = True
                piano_song = pe.current_piano_song_title or pe.GLOBAL_PIANO_REALTIME_STATE.get("title") or "名曲"
        except Exception:
            pass

        now = time.time()
        has_recent_sys_text = bool(LATEST_SYSTEM_AUDIO_TEXT and (now - LATEST_SYSTEM_AUDIO_TEXT_TIME < 20.0))
        has_recent_music = bool(LATEST_SYSTEM_MUSIC_INFO and (now - LATEST_SYSTEM_MUSIC_TIME < 25.0))

        if piano_playing:
            if has_recent_sys_text:
                sys_tag = "全系統音訊 (鋼琴+語音)"
                sys_detail = f"7L 正在彈奏：《{piano_song}》 | 聽見電腦語音：『{LATEST_SYSTEM_AUDIO_TEXT}』"
            elif sys_level > 5:
                sys_tag = "全系統音訊 (鋼琴演奏)"
                sys_detail = f"電腦全系統聲音監聽中 | 7L 正在彈奏：《{piano_song}》"
            else:
                sys_tag = "全系統音訊 (鋼琴待命)"
                sys_detail = f"7L 琴房在線 | 曲目：《{piano_song}》"
        elif has_recent_music and sys_level > 3:
            sys_tag = "辨識到音樂/音效"
            sys_detail = f"聽出電腦正在播放：{LATEST_SYSTEM_MUSIC_INFO}"
        elif has_recent_sys_text:
            sys_tag = "辨識到電腦語音/台詞"
            sys_detail = f"聽見電腦音訊：『{LATEST_SYSTEM_AUDIO_TEXT}』"
        elif sys_level > 5:
            # 檢查是否有螢幕影音線索
            if current_screen_context and any(k in current_screen_context for k in ["YouTube", "影片", "音樂", "鋼琴", "Campanella", "piano", "歌"]):
                hint_clean = current_screen_context.split("，")[0].split("。")[0][:28]
                sys_tag = "播放影音中"
                sys_detail = f"偵測到螢幕影音播放中 ({hint_clean})，7L 正在聆聽曲目..."
            else:
                sys_tag = "播放全系統音訊"
                sys_detail = "電腦正在播放背景音樂/旋律，7L 正在辨識中..."
        elif current_system_audio_context and "目前沒有" not in current_system_audio_context:
            sys_tag = "播放中"
            sys_detail = current_system_audio_context
        else:
            sys_tag = "安靜無聲"
            sys_detail = "電腦目前無音訊輸出（全系統聲音安靜）。"

        # 2. 現實環境聲音感知
        real_tag = "靈敏傾聽中"
        real_detail = "現實環境安靜，等待老爸說話中..."
        real_level = min(100, max(0, int(CURRENT_MIC_VOL_PERCENT)))

        if IS_SLEEPING:
            real_tag = "休眠暫停"
            real_detail = "7L 正在睡覺，已暫停接收現實人聲。"
            real_level = 0
        elif not IS_MIC_ENABLED:
            real_tag = "麥克風靜音"
            real_detail = "麥克風目前已手動關閉。"
            real_level = 0
        elif is_user_listening:
            real_tag = "捕捉到人聲"
            real_detail = "正在傾聽老爸說話中..."
            if real_level < 25:
                real_level = 45
        elif LATEST_REALWORLD_SPEECH_TEXT and (time.time() - LATEST_REALWORLD_SPEECH_TIME < 45):
            diff_sec = int(time.time() - LATEST_REALWORLD_SPEECH_TIME)
            time_hint = "剛剛" if diff_sec < 5 else f"{diff_sec} 秒前"
            real_tag = "剛才發話"
            real_detail = f"老爸{time_hint}說：『{LATEST_REALWORLD_SPEECH_TEXT}』"
        elif real_level > 12:
            real_tag = "環境動態"
            real_detail = "偵測到微弱聲響，隨時待命辨識..."

        # 整體狀態
        if IS_SLEEPING:
            status_text = "休眠暫停中"
        elif piano_playing:
            status_text = " 鋼琴演奏 & 全系統聲音"
        elif sys_level > 5 and is_user_listening:
            status_text = "電腦全系統音訊 & 聆聽老爸"
        elif is_user_listening:
            status_text = " 聆聽老爸中"
        elif sys_level > 5:
            status_text = " 電腦全系統音訊播放中"
        else:
            status_text = "雙向全雙工監聽"

        return {
            "status_text": status_text,
            "sys_tag": sys_tag,
            "sys_detail": sys_detail,
            "sys_level": sys_level,
            "real_tag": real_tag,
            "real_detail": real_detail,
            "real_level": real_level,
            "user_speaking": LATEST_REALWORLD_SPEECH_TEXT if (time.time() - LATEST_REALWORLD_SPEECH_TIME < 45) else ""
        }

    def _get_system_state():
        global current_ai_state
        #  鋼琴在線狀態即時動態核實 (若鋼琴被強制關機，秒級自動回歸 IDLE，絕不卡死)
        if current_ai_state == "PIANO" and not pe.is_piano_active_and_alive():
            current_ai_state = "IDLE"

        eff_status = " 正常運作中" if not IS_SLEEPING and current_ai_state == "IDLE" and "休眠" not in current_ai_status_str else current_ai_status_str
        stress_info = get_api_stress_metrics()
        silence_ticks = get_silence_ticks()
        uptime_ticks = get_uptime_ticks()
        return {
            "ai_status": eff_status,
            "ai_state": "sleep" if IS_SLEEPING else current_ai_state.lower(),
            "silence_ticks": silence_ticks,
            "silence_human": format_ticks_to_human(silence_ticks),
            "uptime_ticks": uptime_ticks,
            "uptime_human": format_ticks_to_human(uptime_ticks),
            "is_sleeping": IS_SLEEPING,
            "mic_action": " 聆聽中" if is_user_listening else current_mic_action_str,
            "is_mic_enabled": IS_MIC_ENABLED,
            "mic_volume": 0.0 if IS_SLEEPING else CURRENT_MIC_VOL_PERCENT / 100.0,
            "model_name": "Gemini 3.8 Flash (Tier-7)",
            "api_calls": TOTAL_API_CALLS,
            "api_energy": max(5.0, round(100.0 - (TOTAL_API_CALLS * 0.4), 1)),
            "api_stress": stress_info,
            "vision_change": "high" if yt_comp.IS_YT_COMPANION_ACTIVE else CURRENT_VISION_CHANGE_LEVEL,
            "vision_change_score": 85 if yt_comp.IS_YT_COMPANION_ACTIVE else CURRENT_VISION_CHANGE_SCORE,
            "vts_expression": getattr(vts, "current_expression", "自然") if vts else "未連線",
            "screen_context": f"正在觀看 YouTube 影片《{yt_comp.CURRENT_YT_TITLE[:25]}》" if yt_comp.IS_YT_COMPANION_ACTIVE else current_screen_context,
            "vision_history": list(VISION_HISTORY_STREAM),
            "last_vision_time": time.time() if yt_comp.IS_YT_COMPANION_ACTIVE else LAST_VISION_LOOK_TIME,
            "audio_context": current_system_audio_context,
            "audio_perception": get_audio_perception_summary(),
            "timer_sensor": live_timer_hub.get_sensor_summary()
        }

    def _set_mic(enable=None):
        global IS_MIC_ENABLED
        if enable is None:
            IS_MIC_ENABLED = not IS_MIC_ENABLED
        else:
            IS_MIC_ENABLED = bool(enable)
        return IS_MIC_ENABLED

    async def _trigger_expr(expr):
        if vts:
            await set_vts_expression(vts, expr)

    def _get_last_vision_img():
        global LATEST_HD_SCREEN_BYTES
        #  若 YouTube 伴看活躍中，優先返回 YouTube 視窗高畫質截圖
        if yt_comp.IS_YT_COMPANION_ACTIVE and yt_comp.LATEST_YT_FRAME_BYTES:
            return yt_comp.LATEST_YT_FRAME_BYTES
        if LATEST_HD_SCREEN_BYTES:
            return LATEST_HD_SCREEN_BYTES
        if latest_screen_cache and isinstance(latest_screen_cache, list) and len(latest_screen_cache) > 0:
            return latest_screen_cache[0][1]
        return None

    def _restart():
        log_print("🔄 [系統] 收到 Web 控制台重啟指令，正在重新啟動 7L 系統...")
        if pe.current_piano_process and pe.current_piano_process.poll() is None:
            try:
                pe.current_piano_process.terminate()
            except Exception:
                pass
        if pe.SOUND_ENGINE:
            try:
                pe.SOUND_ENGINE.all_notes_off()
            except Exception:
                pass
        import subprocess
        try:
            subprocess.Popen([sys.executable] + sys.argv)
        except Exception as e:
            log_print(f"⚠️ [重啟失敗] {e}")
        os._exit(0)

    def _shutdown():
        log_print("👋 [系統] 收到 Web 控制台關機指令，正在安全退出 7L 系統...")
        if pe.current_piano_process and pe.current_piano_process.poll() is None:
            try:
                pe.current_piano_process.terminate()
            except Exception:
                pass
        if pe.SOUND_ENGINE:
            pe.SOUND_ENGINE.all_notes_off()
        os._exit(0)

    async def _execute_tool_manually(tool_name: str, args: dict):
        log_print(f"🛠️ [老爸手動調用] 正在執行工具: {tool_name}，參數: {args}")
        if tool_name in ["pe.play_virtual_piano", "play_virtual_piano"]:
            song_name = args.get("song_name", "鐘")
            force_online = bool(args.get("force_online", False))
            await pe.play_virtual_piano(song_name, force_online=force_online, target="dad", requester_name="老爸", is_direct_song_name=True)
            return f"已成功為老爸排播/演奏鋼琴曲目《{song_name}》"
        elif tool_name in ["pe.compose_and_play_original_piano", "compose_and_play_original_piano"]:
            theme = args.get("theme_or_title", "星空漫步")
            style = args.get("mood_or_style", "治癒抒情")
            await pe.compose_and_play_original_piano(theme_or_title=theme, mood_or_style=style, target="dad", requester_name="老爸")
            return f"已完成現場即興創作並演奏《{theme}》（風格：{style}）"
        elif tool_name in ["pe.mashup_virtual_piano", "mashup_virtual_piano"]:
            s1 = args.get("song_name1", "冬風")
            s2 = args.get("song_name2", "")
            if s2:
                await pe.mashup_virtual_piano(s1, s2)
                return f"已啟動多曲極限串燒演奏：《{s1}》 x 《{s2}》"
            else:
                await pe.mashup_virtual_piano(s1)
                return f"已啟動多曲極限串燒演奏：《{s1}》"
        elif tool_name in ["pe.insert_virtual_piano", "insert_virtual_piano"]:
            s = args.get("song_name", "少女的祈禱")
            await pe.insert_virtual_piano(s)
            return f"已成功插播追加曲目：《{s}》"
        elif tool_name in ["pe.set_piano_instrument", "set_piano_instrument"]:
            inst = args.get("instrument", "鋼琴")
            await pe.set_piano_instrument(inst)
            return f"已將鋼琴發聲音色切換為：{inst}"
        elif tool_name in ["pe.set_piano_speed", "set_piano_speed"]:
            spd = float(args.get("speed", 1.0))
            await pe.set_piano_speed(spd)
            return f"已將鋼琴演奏速度調整為：{spd:.2f}x"
        elif tool_name in ["pe.set_piano_volume", "set_piano_volume"]:
            vol = int(args.get("volume", 85))
            await pe.set_piano_volume(vol)
            return f"已將鋼琴演奏音量調整為：{vol}%"
        elif tool_name in ["pe.open_virtual_piano", "open_virtual_piano"]:
            await pe.open_virtual_piano()
            return "已在桌面打開 88 鍵鋼琴介面待命"
        elif tool_name in ["pe.pause_virtual_piano", "pause_virtual_piano"]:
            await pe.pause_virtual_piano()
            return "已暫停當前鋼琴演奏"
        elif tool_name in ["pe.resume_virtual_piano", "resume_virtual_piano"]:
            await pe.resume_virtual_piano()
            return "已恢復繼續鋼琴演奏"
        elif tool_name in ["pe.stop_virtual_piano", "stop_virtual_piano"]:
            await pe.stop_virtual_piano()
            return "已停止鋼琴演奏並關閉鋼琴"
        elif tool_name == "move_spatial_position":
            pos = args.get("target_position", "正中間")
            await apply_spatial_position(pos)
            return f"已平滑移動 7L 站位至：{pos}"
        elif tool_name == "trigger_vts_expression":
            expr = args.get("expression_name", "自然")
            if vts:
                await set_vts_expression(vts, expr)
            return f"已觸發 VTS 表情：{expr}"
        elif tool_name == "control_microphone":
            enabled = bool(args.get("is_enabled", True))
            control_microphone(enabled)
            return f"已{'開啟' if enabled else '靜音關閉'}麥克風收音"
        elif tool_name == "set_sleep_mode":
            enable = bool(args.get("enable", False))
            await set_sleep_mode(enable)
            return f"已切換為{'深層休眠 (0 API)' if enable else '全速運作喚醒狀態'}"
        elif tool_name == "set_timer":
            sec = int(args.get("seconds", 60))
            msg = args.get("message", "提醒時間到！")
            asyncio.create_task(set_timer(sec, msg, input_queue))
            return f"已設定 {sec} 秒後鬧鐘提醒：「{msg}」"
        elif tool_name == "open_browser":
            url = args.get("url", "https://www.google.com")
            if not url.startswith("http"):
                url = "https://" + url
            import webbrowser
            webbrowser.open(url)
            return f"已在預設瀏覽器中開啟網頁：{url}"
        elif tool_name == "search_google":
            q = args.get("query", "")
            
            res = await asyncio.to_thread(search_google, q)
            return res or f"已搜尋「{q}」"
        elif tool_name == "update_cloud_knowledge":
            cat = args.get("category", "facts")
            content = args.get("content", "")
            await update_cloud_prompt_field(cat, content)
            return f"已成功將新認知寫入雲端大腦 [{cat}]：{content}"
        elif tool_name == "clear_all_memories":
            
            await clear_all_memories()
            return "已清空 7L 當前短期記憶中樞"
        elif tool_name in ["generate_ai_image", "draw_illustration"]:
            p = args.get("prompt", "")
            res = await generate_ai_image(p)
            return res or f"已生成 AI 插畫：「{p}」"
        elif tool_name in ["sing_song", "auto_sing_song"]:
            s = args.get("song_name", "")
            asyncio.create_task(produce_and_sing_cover(s))
            return f"已排程 AI 歌聲翻唱：《{s}》"
        elif tool_name in ["stop_singing_song", "stop_singing", "stop_cover"]:
            stop_singing()
            return "已停止唱歌"
        elif tool_name == "execute_local_python_code":
            code = args.get("code_string", "")
            res = await execute_local_python_code(code)
            return res or "Python 程式碼執行完成"
        else:
            raise ValueError(f"未知的工具名稱: {tool_name}")

    def _get_switches():
        return [
            {
                "key": "IS_AUTO_PIANO_ENABLED",
                "name": "閒置自主彈琴",
                "category": "piano",
                "category_name": " 音樂與演奏",
                "description": "當 7L 閒置且環境無聲音超過 60 秒時，每隔 5 分鐘是否自主坐到鋼琴前隨機挑選曲目演奏。",
                "value": bool(IS_AUTO_PIANO_ENABLED),
                "icon": "piano"
            },
            {
                "key": "IS_PIANO_AUTO_RADIO_MODE",
                "name": "鋼琴隨機電台連播",
                "category": "piano",
                "category_name": " 音樂與演奏",
                "description": "當前鋼琴曲目彈完後，若隊列已無點歌，是否自動從曲庫中無限接續隨機抽歌連播。",
                "value": bool(getattr(pe, "IS_PIANO_AUTO_RADIO_MODE", False)),
                "icon": "radio"
            },
            {
                "key": "IS_AUTO_WANDER_ENABLED",
                "name": "閒置自主漫遊走位",
                "category": "wander",
                "category_name": " 自主行為與漫遊",
                "description": "7L 處於閒置狀態超過 60 秒時，每隔 60 秒在螢幕舞台上隨機走位、變換站位與姿態。",
                "value": bool(IS_AUTO_WANDER_ENABLED),
                "icon": "walk"
            },
            {
                "key": "IS_PROACTIVE_SPEAK_ENABLED",
                "name": "視覺陪伴主動搭話",
                "category": "wander",
                "category_name": " 自主行為與漫遊",
                "description": "每隔 35~50 秒根據老爸目前視窗、聆聽音樂與操作動態，自主決定是否主動搭話或吐槽。關閉時轉為純被動（有問才答）。",
                "value": bool(IS_PROACTIVE_SPEAK_ENABLED),
                "icon": "chat"
            },
            {
                "key": "IS_PERIPHERAL_VISION_ENABLED",
                "name": "餘光視覺感知中樞",
                "category": "vision",
                "category_name": " 多模態感知",
                "description": "背景是否定時截取並分析老爸的螢幕動態與視窗畫面，維持連續時序視覺記憶緩存。",
                "value": bool(IS_PERIPHERAL_VISION_ENABLED),
                "icon": "eye"
            },
            {
                "key": "IS_FACE_TRACKING_ENABLED",
                "name": "AI 視線與頭部追蹤",
                "category": "vision",
                "category_name": " 多模態感知",
                "description": "啟用 Live2D 模型的自然視線跟隨、呼吸律動與自然眨眼同步。",
                "value": bool(IS_FACE_TRACKING_ENABLED),
                "icon": "user"
            },
            {
                "key": "IS_MIC_ENABLED",
                "name": "麥克風語音監聽收音",
                "category": "system",
                "category_name": " 系統核心與收音",
                "description": "即時監聽並轉寫實體麥克風收到的語音。關閉時 7L 不再收音，僅接受文字發話。",
                "value": bool(IS_MIC_ENABLED),
                "icon": "mic"
            },
            {
                "key": "IS_STREAM_CHAT_ENABLED",
                "name": "直播彈幕即時互動",
                "category": "system",
                "category_name": " 系統核心與收音",
                "description": "是否開啟直播間（如 TikTok）即時彈幕串流接入與觀眾留言排隊互動。",
                "value": bool(getattr(tk_listener, "IS_STREAMING", False)),
                "icon": "broadcast"
            },
            {
                "key": "IS_SLEEPING",
                "name": "深層休眠模式 (0 API)",
                "category": "system",
                "category_name": " 系統核心與收音",
                "description": "雙眼閉合安睡，完全停止視覺截圖、背景思考與計時器，達成 0 API 消耗。",
                "value": bool(IS_SLEEPING),
                "icon": "moon"
            },
            {
                "key": "IS_YT_WATCHER_ENABLED",
                "name": " YouTube 即時伴看 (Multimodal Live)",
                "category": "vision",
                "category_name": " 視覺與多模態感知",
                "description": "自動檢測螢幕上的 YouTube 影片，以 1 FPS 視窗裁剪與系統音訊內錄持續跟進理解。",
                "value": bool(yt_comp.IS_YT_WATCHER_ENABLED),
                "icon": "video"
            },
            {
                "key": "MODE_TOGGLE",
                "name": "伴侶模式 (需重啟)",
                "category": "system",
                "category_name": " 系統核心與收音",
                "description": "開啟時為伴侶模式 (同時陪你與聊天室)，關閉為實況主模式 (只理聊天室)。切換後請點擊上方「重啟大腦」生效。",
                "value": _RUN_MODE == "companion",
                "icon": "user"
            }
        ]

    async def _set_switch(key: str, value=None):
        global IS_AUTO_PIANO_ENABLED, IS_AUTO_WANDER_ENABLED, IS_PROACTIVE_SPEAK_ENABLED
        global IS_PERIPHERAL_VISION_ENABLED, IS_FACE_TRACKING_ENABLED, IS_MIC_ENABLED, IS_SLEEPING
        
        current_map = {
            "IS_AUTO_PIANO_ENABLED": IS_AUTO_PIANO_ENABLED,
            "IS_PIANO_AUTO_RADIO_MODE": getattr(pe, "IS_PIANO_AUTO_RADIO_MODE", False),
            "IS_AUTO_WANDER_ENABLED": IS_AUTO_WANDER_ENABLED,
            "IS_PROACTIVE_SPEAK_ENABLED": IS_PROACTIVE_SPEAK_ENABLED,
            "IS_PERIPHERAL_VISION_ENABLED": IS_PERIPHERAL_VISION_ENABLED,
            "IS_FACE_TRACKING_ENABLED": IS_FACE_TRACKING_ENABLED,
            "IS_MIC_ENABLED": IS_MIC_ENABLED,
            "IS_STREAM_CHAT_ENABLED": getattr(tk_listener, "IS_STREAMING", False),
            "IS_SLEEPING": IS_SLEEPING,
            "IS_YT_WATCHER_ENABLED": yt_comp.IS_YT_WATCHER_ENABLED,
            "MODE_TOGGLE": _RUN_MODE == "companion"
        }
        
        target_val = not current_map.get(key, False) if value is None else bool(value)
        
        if key == "IS_AUTO_PIANO_ENABLED":
            IS_AUTO_PIANO_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 閒置自主彈琴已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_PIANO_AUTO_RADIO_MODE":
            pe.IS_PIANO_AUTO_RADIO_MODE = target_val
            log_print(f"🎛️ [系統開關] 鋼琴無限隨機電台已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_AUTO_WANDER_ENABLED":
            IS_AUTO_WANDER_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 閒置自主漫遊已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_PROACTIVE_SPEAK_ENABLED":
            IS_PROACTIVE_SPEAK_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 視覺陪伴主動搭話已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_PERIPHERAL_VISION_ENABLED":
            IS_PERIPHERAL_VISION_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 餘光視覺感知已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_FACE_TRACKING_ENABLED":
            IS_FACE_TRACKING_ENABLED = target_val
            log_print(f"🎛️ [系統開關] AI 視線與頭部追蹤已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_MIC_ENABLED":
            IS_MIC_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 麥克風收音已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_STREAM_CHAT_ENABLED":
            tk_listener.IS_STREAMING = target_val
            log_print(f"🎛️ [系統開關] 直播彈幕即時互動已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_SLEEPING":
            await set_sleep_mode(target_val)
            target_val = IS_SLEEPING
            log_print(f"🎛️ [系統開關] 深層休眠模式已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_YT_WATCHER_ENABLED":
            yt_comp.IS_YT_WATCHER_ENABLED = target_val
            log_print(f"🎛️ [系統開關] YouTube 即時伴看已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "MODE_TOGGLE":
            import re
            env_path = ".env"
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()
                new_mode = "companion" if target_val else "vtuber"
                if re.search(r'^MODE=.*', content, flags=re.MULTILINE):
                    content = re.sub(r'^MODE=.*', f'MODE={new_mode}', content, flags=re.MULTILINE)
                else:
                    content += f'\nMODE={new_mode}\n'
                
                # 自動綁定：若是伴侶模式，預設開啟主控輸入與私人語音；vtuber則維持
                if new_mode == "companion":
                    if re.search(r'^OPERATOR_INPUT=.*', content, flags=re.MULTILINE):
                        content = re.sub(r'^OPERATOR_INPUT=.*', 'OPERATOR_INPUT=1', content, flags=re.MULTILINE)
                    else:
                        content += '\nOPERATOR_INPUT=1\n'
                    if re.search(r'^OPERATOR_SPEECH=.*', content, flags=re.MULTILINE):
                        content = re.sub(r'^OPERATOR_SPEECH=.*', 'OPERATOR_SPEECH=1', content, flags=re.MULTILINE)
                    else:
                        content += '\nOPERATOR_SPEECH=1\n'

                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(content)
                log_print(f"🎛️ [系統開關] 運行模式已切換為 {new_mode} (並自動配置輸入權限)，請在網頁點擊「重啟大腦」生效！")
            else:
                log_print("⚠️ 找不到 .env 檔案，無法切換模式！")
            
        return target_val

    asyncio.create_task(web_dash.start_web_dashboard(
        port=7860,
        input_queue=input_queue,
        vts=vts,
        get_system_state_cb=_get_system_state,
        set_mic_cb=_set_mic,
        set_sleep_cb=set_sleep_mode,
        trigger_expression_cb=_trigger_expr,
        get_memory_cb=lambda: list(UNIFIED_LIVE_MEMORY),
        get_mind_board_cb=lambda: list(STREAMER_MIND_BOARD),
        get_last_vision_image_cb=_get_last_vision_img,
        restart_cb=_restart,
        shutdown_cb=_shutdown,
        execute_tool_cb=_execute_tool_manually,
        get_switches_cb=_get_switches,
        set_switch_cb=_set_switch,
        punish_cb=execute_punish_action,
        reward_cb=execute_reward_action
    ))
    
    #  啟動 YouTube 自動伴看與實時多模態視聽理解服務
    yt_comp.ON_VISION_RECORD_CB = record_vision_history_entry
    yt_comp.init_yt_companion()

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
            
            # 依據是否有即時通知，動態組合尾端文字 (通知放在最後面，絕不佔用整行)
            has_notif = time.time() < notification_expire_time
            if has_notif:
                tail_str = f" {current_system_notification}"
                if tk_listener.current_tiktok_status_str and tk_listener.current_tiktok_status_str != "[ TikTok: 待命中]":
                    tail_str = f"{tk_listener.current_tiktok_status_str} | {tail_str}"
            else:
                tail_str = tk_listener.current_tiktok_status_str

            #  若 YouTube 伴看活躍中，優先顯示伴看狀態
            if yt_comp.IS_YT_COMPANION_ACTIVE:
                yt_info = f" 伴看中: {yt_comp.CURRENT_YT_TITLE[:15]}..."
                tail_str = f"{yt_info} | {tail_str}" if tail_str else yt_info

            # 依據終端寬度動態分配狀態文字、動作文字、音量與 尾端通知/動態 (排在最後面)
            if max_cols < 85:
                status_text = fit_text_to_width(current_ai_status_str, max(18, max_cols - 48))
                action_text = " 聆聽中" if is_user_listening else fit_text_to_width(current_mic_action_str, 8)
                tail_text = fit_text_to_width(tail_str, max(14, max_cols - 45))
                raw_msg = f"[{char}] {status_text} | {action_text} | {current_mic_volume_str} | {tail_text}"
            else:
                status_text = fit_text_to_width(current_ai_status_str, max(28, max_cols - 65))
                action_text = " 聆聽中..." if is_user_listening else fit_text_to_width(current_mic_action_str, 12)
                tail_text = fit_text_to_width(tail_str, max(20, max_cols - 75))
                raw_msg = f"[{char}] {status_text} | {action_text} | {current_mic_volume_str} | {tail_text}"
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
        import traceback
        print(f"\n❌ [底層系統異常崩潰]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())