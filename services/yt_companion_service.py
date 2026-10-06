# -*- coding: utf-8 -*-
"""
🎬 YouTube 專屬「眼與耳」即時感官與時序記憶中樞 (services/yt_companion_service.py)
--------------------------------------------------------------------------
🎯 核心設計：
1. 【只當眼與耳，不發出聲音】：
   - 持續接收 1 FPS 視窗裁切畫面 + 16kHz WASAPI 數位原聲音訊。
   - 完全靜音（不佔用喇叭、不發出 TTS 音訊），純粹充當 7L 的視覺與聽覺受體。
2. 【播到哪，記憶沉澱到哪】：
   - 每 15~20 秒或偵測到精彩轉折時，自動將剛才看到的畫面動作、字幕與對白
     提煉為客觀生動的「視聽劇情筆記」，沉澱進 `YT_PERCEPTION_LOG`。
3. 【無縫注入 7L 主腦】：
   - 提供 `get_yt_memory_context()`。
   - 當主人在麥克風或文字中對 7L 說話時，7L 主腦（8大 Gemini 模型 + 傲嬌個性 + RVC 口型）
     自動調用這份影片記憶，用她自己的聲音自然回答主人！
"""

import os
import sys
import time
import asyncio
import io
import queue
import warnings
from collections import deque
from datetime import datetime
import numpy as np
from PIL import Image, ImageGrab

# 徹底過濾底層音訊警告
warnings.filterwarnings("ignore")
try:
    from soundcard.mediafoundation import SoundcardRuntimeWarning
    warnings.filterwarnings("ignore", category=SoundcardRuntimeWarning)
except Exception:
    pass

# WebSocket 握手補丁
import core.websocket_patch
from core.llm_engine import GEMINI_KEYS
from core.utils import log_print, sys_notify
from google import genai
from google.genai import types

try:
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import soundcard as sc
    HAS_SOUNDCARD = True
except ImportError:
    HAS_SOUNDCARD = False

# 全域狀態
IS_YT_WATCHER_ENABLED = True     # 全域功能總開關
IS_YT_COMPANION_ACTIVE = False   # 當前是否鎖定 YouTube 視窗並在感官串流中
CURRENT_YT_TITLE = ""            # 當前鎖定的 YouTube 影片標題
LATEST_YT_FRAME_BYTES = None     # 最新一幀裁剪後的 YouTube 截圖 (供 Web 儀表板相框顯示)
ON_VISION_RECORD_CB = None       # 外部視覺紀錄回呼: cb(text, scene)

# 🧠 影片劇情時序感知記憶池（保留最新 15 筆劇情記憶紀錄）
YT_PERCEPTION_LOG = deque(maxlen=15)
_LAST_MEMORY_TICK_TIME = 0.0

# 內部控制
_live_session = None
_loopback_streamer = None
_service_task = None

def is_video_window(title: str) -> bool:
    title_lower = title.lower()
    if "youtube music" in title_lower:
        return False
    keywords = ["youtube", "twitch", "netflix", "bilibili", "vlc media player", "potplayer", "movies & tv", "電影與電視", "picture-in-picture", "子母畫面"]
    extensions = [".mp4", ".mkv", ".avi", ".webm", ".mov"]
    if any(k in title_lower for k in keywords):
        return True
    if any(ext in title_lower for ext in extensions):
        return True
    return False

def find_youtube_window():
    """
    🎯 嚴格前景判定 (Strict Focus Detection)：
    只鎖定「當前操作中的前景焦點視窗」或「置頂浮動子母畫面」。
    """
    if not HAS_WIN32:
        return None, None, ""

    # 1. 檢測當前前景焦點視窗
    try:
        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd and win32gui.IsWindowVisible(fg_hwnd) and not win32gui.IsIconic(fg_hwnd):
            fg_title = win32gui.GetWindowText(fg_hwnd)
            if is_video_window(fg_title):
                r = win32gui.GetWindowRect(fg_hwnd)
                w, h = r[2] - r[0], r[3] - r[1]
                if w > 300 and h > 200:
                    return fg_hwnd, r, fg_title
    except Exception:
        pass

    # 2. 檢測置頂浮動子母畫面
    pip_hwnd, pip_rect, pip_title = None, None, ""
    def _enum_topmost_cb(hwnd, _):
        nonlocal pip_hwnd, pip_rect, pip_title
        if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if ex_style & win32con.WS_EX_TOPMOST:
                title = win32gui.GetWindowText(hwnd)
                if is_video_window(title):
                    r = win32gui.GetWindowRect(hwnd)
                    w, h = r[2] - r[0], r[3] - r[1]
                    if w > 200 and h > 150:
                        pip_hwnd = hwnd
                        pip_rect = r
                        pip_title = title
                        return False
        return True

    try:
        import win32con
        win32gui.EnumWindows(_enum_topmost_cb, None)
    except Exception:
        pass

    return pip_hwnd, pip_rect, pip_title

class AudioLoopbackStreamer:
    """WASAPI Loopback 系統音訊採集 (YouTube 聲音 16kHz PCM)"""
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.running = False
        self.audio_queue = queue.Queue(maxsize=120)
        self.thread = None

    def start(self):
        if not HAS_SOUNDCARD:
            return
        self.running = True
        import threading
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def _worker(self):
        try:
            default_spk = sc.default_speaker().name
            loopback_mic = None
            for m in sc.all_microphones(include_loopback=True):
                if m.isloopback and (m.name == default_spk or default_spk in m.name):
                    loopback_mic = m
                    break
            if not loopback_mic:
                for m in sc.all_microphones(include_loopback=True):
                    if m.isloopback:
                        loopback_mic = m
                        break
            if not loopback_mic:
                return

            chunk_frames = 3200 # 0.2 秒採集
            with loopback_mic.recorder(samplerate=self.sample_rate, channels=1) as mic:
                while self.running:
                    data = mic.record(numframes=chunk_frames)
                    pcm_int16 = (data * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()
                    if not self.audio_queue.full():
                        self.audio_queue.put_nowait(pcm_int16)
        except Exception:
            pass

EYE_EAR_SYSTEM_INSTRUCTION = """
你是 7L 的「眼與耳感官神經中樞 (Visual & Auditory Sensory Nerve)」。
你正在充當 7L 的眼睛與耳朵，透過即時畫面串流與系統原聲音訊，觀看主人電腦上的 YouTube 影片。

【核心規則】：
1. 【絕對靜音】：你不是對話助手，不要對主人說話，保持安靜。
2. 【記憶沉澱記錄員】：你的職責是將影片內容提煉為「劇情與情境筆記」，存入 7L 的記憶庫。
3. 【記錄格式】：每當收到記錄信號或劇情發生關鍵轉折，用繁體中文記錄 1~2 句話：
   - 畫面動作、字幕與文字重點
   - 角色說了什麼關鍵台詞、笑點或情節進展
   - 保持生動、具體、客觀（例如：「灰檸檬在電車難題選了撞 4 公斤，說比較不會痛...」）。
"""

def add_perception_memory(text: str):
    """將一段感官記憶加入時序隊列，並同步推送至 Web 後台視覺串流"""
    global YT_PERCEPTION_LOG
    clean = text.strip()
    if not clean:
        return
    # 避免重複刷同一句
    if YT_PERCEPTION_LOG and clean == YT_PERCEPTION_LOG[-1].get("content"):
        return
    time_str = datetime.now().strftime("%H:%M:%S")
    item = {"time": time_str, "content": clean}
    YT_PERCEPTION_LOG.append(item)
    log_print(f"👁️👂 [YT 眼耳感知沉澱] ({time_str}): {clean}")

    # 🌐 同步推播至 Web 儀表板 VISION 視覺時序歷史串流
    if ON_VISION_RECORD_CB:
        try:
            video_note = f"《{CURRENT_YT_TITLE[:22]}》: {clean}" if CURRENT_YT_TITLE else clean
            ON_VISION_RECORD_CB(video_note, scene="觀賞影片")
        except Exception:
            pass

def get_yt_memory_context() -> str:
    """供 7L 主腦 fetch_ai_response 調用的時序影片記憶字串"""
    if not IS_YT_COMPANION_ACTIVE and not YT_PERCEPTION_LOG:
        return ""

    title = CURRENT_YT_TITLE if CURRENT_YT_TITLE else "剛才觀看的影片"
    lines = [
        f"【🎬 7L 雙眼與雙耳感知的 YouTube 影片即時記憶】",
        f"影片標題：《{title}》",
        "（妳的眼耳感知神經正在/剛才同步觀看這部影片，以下是妳親眼看到和聽到的劇情進展筆記）："
    ]
    if YT_PERCEPTION_LOG:
        for it in list(YT_PERCEPTION_LOG)[-8:]: # 取最新 8 筆
            lines.append(f"- [{it['time']}] {it['content']}")
    else:
        lines.append("- (目前畫面正在加載或剛進入影片中)")
    lines.append("👉 當老爸問妳影片內容、剛才那個人在幹嘛、或聊到這部片時，請直接以妳親眼看到和親耳聽到的記憶，用 7L 本人的口氣自然回答！")
    return "\n".join(lines)

async def _yt_companion_session_loop(target_hwnd, initial_rect, initial_title):
    """單次 YouTube 伴看感官連線"""
    global _live_session, _loopback_streamer
    global IS_YT_COMPANION_ACTIVE, CURRENT_YT_TITLE

    if not GEMINI_KEYS:
        log_print("❌ [YT 眼耳] 無可用 GEMINI_KEYS，無法啟動感官串流")
        return

    api_key = GEMINI_KEYS[0]
    client = genai.Client(api_key=api_key)
    model = "gemini-3.8-live"

    CURRENT_YT_TITLE = initial_title
    IS_YT_COMPANION_ACTIVE = True
    sys_notify(f"👀 啟動眼耳感知: {initial_title[:25]}...")
    log_print(f"🎬 [YT 眼耳] 正在為視窗啟動感官串流: {initial_title[:40]}...")

    if not _loopback_streamer:
        _loopback_streamer = AudioLoopbackStreamer(sample_rate=16000)
        _loopback_streamer.start()

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=EYE_EAR_SYSTEM_INSTRUCTION)]
        )
    )

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            _live_session = session
            log_print(f"✅ [YT 眼耳] 感官神經連線就緒！開始默默吸收畫面與聲音。")

            session_running = True
            last_seen_time = time.time()
            current_rect = initial_rect

            # 啟動時沉澱第一筆認知
            add_perception_memory(f"開始陪伴老爸觀看 YouTube 影片《{initial_title[:30]}》")

            # 任務 1: 畫面採集 (1 FPS)
            async def _video_worker():
                global LATEST_YT_FRAME_BYTES
                nonlocal session_running, current_rect
                while session_running and IS_YT_WATCHER_ENABLED:
                    try:
                        bbox = (current_rect[0], current_rect[1], current_rect[2], current_rect[3]) if current_rect else None
                        shot = ImageGrab.grab(bbox=bbox)
                        shot.thumbnail((1024, 576))
                        buf = io.BytesIO()
                        shot.save(buf, format="JPEG", quality=70)
                        jpeg_bytes = buf.getvalue()
                        LATEST_YT_FRAME_BYTES = jpeg_bytes

                        await session.send_realtime_input(
                            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)

            # 任務 2: 系統音訊採集 (加入持續靜音推流防斷線機制)
            async def _audio_worker():
                nonlocal session_running
                # 預先準備好 0.04 秒長度的全 0 靜音 PCM 數據 (16kHz, 16-bit)
                # 16000 samples/sec * 0.04 sec * 2 bytes/sample = 1280 bytes
                silent_chunk = b'\x00' * 1280
                
                while session_running and IS_YT_WATCHER_ENABLED:
                    try:
                        pcm_chunk = _loopback_streamer.audio_queue.get_nowait()
                        if pcm_chunk:
                            await session.send_realtime_input(
                                audio=types.Blob(data=pcm_chunk, mime_type="audio/pcm;rate=16000")
                            )
                    except queue.Empty:
                        # 佇列為空 (沒有系統音效) 時，持續發送全 0 音訊保活
                        try:
                            await session.send_realtime_input(
                                audio=types.Blob(data=silent_chunk, mime_type="audio/pcm;rate=16000")
                            )
                        except Exception:
                            pass
                        await asyncio.sleep(0.04)
                    except Exception:
                        await asyncio.sleep(0.04)

            # 任務 3: 定期促使大腦沉澱當前進度記憶 (每 15 秒觸發一次記錄刷新)
            async def _memory_tick_worker():
                nonlocal session_running
                await asyncio.sleep(6.0) # 給連線初期幾秒積累
                while session_running and IS_YT_WATCHER_ENABLED:
                    try:
                        # 促使模型將最近這段的視聽內容做一個 1~2 句的感官沉澱筆記
                        await session.send_realtime_input(text="請用繁體中文，用一句話記錄剛剛畫面中發生的動作或人物台詞：")
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
                    except Exception:
                        pass
                    await asyncio.sleep(18.0) # 每 18 秒沉澱一次記憶

            # 任務 4: 接收字幕筆記 (純文字沉澱，不播放任何聲音！)
            async def _receive_worker():
                nonlocal session_running
                full_turn_text = []
                async for response in session.receive():
                    if not session_running:
                        break
                    content = response.server_content
                    if content is not None:
                        # 🔇 關鍵：完全不播放 part.inline_data，保持安靜！
                        if hasattr(content, "output_transcription") and content.output_transcription:
                            if hasattr(content.output_transcription, "text") and content.output_transcription.text:
                                full_turn_text.append(content.output_transcription.text)

                        if getattr(content, "interrupted", False):
                            full_turn_text.clear()

                        if getattr(content, "turn_complete", False):
                            if full_turn_text:
                                complete_text = "".join(full_turn_text).strip()
                                # 濾除非筆記的客套話
                                if complete_text and len(complete_text) > 3:
                                    add_perception_memory(complete_text)
                                full_turn_text.clear()

            # 併發啟動
            v_task = asyncio.create_task(_video_worker())
            a_task = asyncio.create_task(_audio_worker())
            m_task = asyncio.create_task(_memory_tick_worker())
            r_task = asyncio.create_task(_receive_worker())

            # 視窗持續存在性檢查
            while session_running and IS_YT_WATCHER_ENABLED:
                hwnd, rect, title = find_youtube_window()
                now = time.time()
                if hwnd:
                    last_seen_time = now
                    current_rect = rect
                    CURRENT_YT_TITLE = title
                else:
                    if now - last_seen_time > 4.0:
                        log_print("💤 [YT 嚴格前景] YouTube 視窗已離開焦點 (判定為背景聽音樂/工作)，4 秒內已自動休眠斷線，0 API 消耗。")
                        session_running = False
                        break

                await asyncio.sleep(1.0)

            v_task.cancel()
            a_task.cancel()
            m_task.cancel()
            r_task.cancel()

    except Exception as e:
        log_print(f"⚠️ [YT 眼耳] 感官連線中斷: {e}")
    finally:
        _live_session = None
        IS_YT_COMPANION_ACTIVE = False
        LATEST_YT_FRAME_BYTES = None

PENDING_VIDEO_REQUEST = None
LAST_REQUEST_TIME = 0

def approve_pending_video():
    global PENDING_VIDEO_REQUEST
    if PENDING_VIDEO_REQUEST and not IS_YT_COMPANION_ACTIVE:
        hwnd, rect, title = PENDING_VIDEO_REQUEST
        PENDING_VIDEO_REQUEST = None
        asyncio.create_task(_yt_companion_session_loop(hwnd, rect, title))
        return True
    return False

def reject_pending_video():
    global PENDING_VIDEO_REQUEST, LAST_REQUEST_TIME
    PENDING_VIDEO_REQUEST = None
    LAST_REQUEST_TIME = time.time() + 120  # 冷卻2分鐘
    return True

async def start_yt_auto_watcher():
    """背景守護協程：持續偵測影片出現，向 Web 儀表板推送確認請求"""
    global PENDING_VIDEO_REQUEST, LAST_REQUEST_TIME
    log_print("👀 [影片眼耳雷達] 背景視窗偵測守護已啟動 (需老爸手動授權)")
    while True:
        try:
            if IS_YT_WATCHER_ENABLED and not IS_YT_COMPANION_ACTIVE:
                hwnd, rect, title = find_youtube_window()
                if hwnd:
                    now = time.time()
                    if PENDING_VIDEO_REQUEST is None or PENDING_VIDEO_REQUEST[0] != hwnd or (now - LAST_REQUEST_TIME) > 60:
                        if now > LAST_REQUEST_TIME:
                            PENDING_VIDEO_REQUEST = (hwnd, rect, title)
                            LAST_REQUEST_TIME = now
                            log_print(f"🔔 [影片伴看] 偵測到影片視窗《{title}》，請至 Web 後台點擊確認！")
                            try:
                                import services.web_dashboard as web_dash
                                web_dash.broadcast_event('yt_companion_request', {"short_title": title[:20], "hwnd": hwnd})
                            except Exception:
                                pass
            await asyncio.sleep(1.5)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(2.0)

def init_yt_companion():
    """在系統啟動時初始化並掛入背景任務"""
    global _service_task
    if _service_task is None:
        _service_task = asyncio.create_task(start_yt_auto_watcher())
    return _service_task
