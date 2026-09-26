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
    import win32process
    HAS_WIN32PROCESS = True
except ImportError:
    HAS_WIN32PROCESS = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import soundcard as sc
    HAS_SOUNDCARD = True
except ImportError:
    HAS_SOUNDCARD = False

# 全域狀態
IS_YT_WATCHER_ENABLED = True     # 全域功能總開關
IS_YT_COMPANION_ACTIVE = False   # 當前是否鎖定影音視窗並在感官串流中
CURRENT_YT_TITLE = ""            # 當前鎖定的影片標題
LATEST_YT_FRAME_BYTES = None     # 最新一幀裁剪後的影片截圖 (供 Web 儀表板相框顯示)
ON_VISION_RECORD_CB = None       # 外部視覺紀錄回呼: cb(text, scene)

# 🧠 影片劇情時序感知記憶池（保留最新 15 筆劇情記憶紀錄）
YT_PERCEPTION_LOG = deque(maxlen=15)
_LAST_MEMORY_TICK_TIME = 0.0

# 内部控制
_live_session = None
_loopback_streamer = None
_service_task = None

# 🛡️ 伴看授權審批機制
_COMPANION_APPROVAL_EVENT: asyncio.Event = None   # 授權事件 (set = 允許, 預設 clear = 等待)
_COMPANION_REJECTION_FLAG: bool = False           # True = 老爸拒絕了本次伴看請求
_COMPANION_PENDING_TITLE: str = ""               # 當前等待審批的視窗標題

def get_companion_approval_status() -> dict:
    """回傳當前伴看授權狀態（供後台 API 查詢）"""
    return {
        "pending": _COMPANION_PENDING_TITLE != "" and (_COMPANION_APPROVAL_EVENT is None or not _COMPANION_APPROVAL_EVENT.is_set()),
        "pending_title": _COMPANION_PENDING_TITLE,
        "active": IS_YT_COMPANION_ACTIVE,
        "current_title": CURRENT_YT_TITLE,
    }

def approve_companion_request():
    """老爸批准伴看 (web_dashboard API 調用)"""
    global _COMPANION_REJECTION_FLAG
    _COMPANION_REJECTION_FLAG = False
    if _COMPANION_APPROVAL_EVENT:
        _COMPANION_APPROVAL_EVENT.set()
    log_print("✅ [伴看授權] 老爸已允許伴看！正在啟動感官串流...")

def reject_companion_request():
    """老爸拒絕伴看 (web_dashboard API 調用)"""
    global _COMPANION_REJECTION_FLAG
    _COMPANION_REJECTION_FLAG = True
    if _COMPANION_APPROVAL_EVENT:
        _COMPANION_APPROVAL_EVENT.set()  # set 讓等待方醒來，由 rejection flag 判斷
    log_print("❌ [伴看授權] 老爸已拒絕伴看，本次跳過。")

# 🎬 全方位影音視窗識別配置
VIDEO_PROCESS_NAMES = {
    "potplayer.exe", "potplayermini64.exe", "potplayermini.exe",
    "vlc.exe", "mpc-hc.exe", "mpc-hc64.exe", "mpc-be.exe", "mpc-be64.exe",
    "mpv.exe", "kmplayer.exe", "kmplayer64.exe", "video.ui.exe", "wmplayer.exe",
    "bilibili.exe", "iqiyi.exe", "netflix.exe", "stellarplayer.exe"
}

VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".ts", ".m4v", ".rmvb", ".m2ts", ".iso", ".3gp"
)

VIDEO_TITLE_KEYWORDS = (
    # 主流網頁影音平台
    "youtube", "bilibili", "嗶哩嗶哩", "哔哩哔哩", "b站",
    "巴哈姆特", "動畫瘋", "bahamut", "gamer.com.tw",
    "netflix", "網飛", "网飞",
    "disney+", "disney plus",
    "twitch",
    "tiktok", "抖音",
    "愛奇藝", "爱奇艺", "iqiyi",
    "騰訊視頻", "腾讯视频", "wetv",
    "優酷", "优酷", "youku",
    "prime video", "amazon video",
    "niconico", "ニコニコ", "nicovideo",
    "line tv", "kktv", "friday影音", "friday 影音",
    "dailymotion", "vimeo", "crunchyroll",
    
    # 子母畫面 / 畫中畫 (PiP)
    "picture-in-picture", "picture in picture",
    "子母畫面", "畫中畫", "画中画", "浮動視窗", "小窗播放",
    
    # 常用本機播放器軟體名稱
    "potplayer", "vlc media player", "mpc-hc", "mpc-be",
    "kmplayer", "電影與電視", "movies & tv", "windows media player",
    "媒體播放機", "恒星播放器", "射手影音"
)

VIDEO_TITLE_EXCLUSIONS = (
    "youtube music", "music.youtube", "spotify", "apple music", "kkbox",
    "visual studio code", "vs code", "cursor", "pycharm", "sublime text",
    "vtube studio", "obs studio", "discord", "steam",
    "工作管理員", "任务管理器", "task manager", "命令提示字元", "powershell"
)

def _get_process_name(hwnd) -> str:
    """安全獲取指定視窗的處理程序名稱（小寫）"""
    if not hwnd or not HAS_WIN32PROCESS or not HAS_PSUTIL:
        return ""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid and pid > 0:
            return psutil.Process(pid).name().lower()
    except Exception:
        pass
    return ""

def is_video_window(hwnd, title: str) -> bool:
    """判定是否為影音播放視窗（包含所有主流影音網站、子母畫面與本機播放器）"""
    if not hwnd or not title:
        return False
    t_lower = title.strip().lower()
    if not t_lower:
        return False
        
    # 1. 嚴格排除純音樂播放器或系統/開發工具
    if any(ex in t_lower for ex in VIDEO_TITLE_EXCLUSIONS):
        return False
        
    # 2. 標題命中主流影音平台、PiP 或播放器關鍵字
    if any(k in t_lower for k in VIDEO_TITLE_KEYWORDS):
        return True
        
    # 3. 標題命中常見影片副檔名
    if any(ext in t_lower for ext in VIDEO_EXTENSIONS):
        return True
        
    # 4. 檢查處理程序是否為專屬影音播放器
    p_name = _get_process_name(hwnd)
    if p_name in VIDEO_PROCESS_NAMES:
        return True
        
    return False

def find_video_window():
    """
    🎯 嚴格前景判定 (Strict Focus Detection)：
    只鎖定「當前操作中的前景焦點影音視窗 (GetForegroundWindow)」或「置頂浮動子母畫面 (PiP Topmost)」。
    支援 YouTube、B站、動畫瘋、Netflix、Disney+、Twitch、TikTok、
    以及 PotPlayer、VLC、MPC、電影與電視等所有正在播放的影音視窗與本機影片。
    若使用者切換至 VS Code、遊戲或桌面在背景播放音樂，一律返回 None，徹底杜絕 Token 浪費。
    """
    if not HAS_WIN32:
        return None, None, ""

    # 1. 檢測當前前景焦點視窗 (最重要核心判斷)
    try:
        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd and win32gui.IsWindowVisible(fg_hwnd) and not win32gui.IsIconic(fg_hwnd):
            fg_title = win32gui.GetWindowText(fg_hwnd)
            if is_video_window(fg_hwnd, fg_title):
                r = win32gui.GetWindowRect(fg_hwnd)
                w, h = r[2] - r[0], r[3] - r[1]
                if w > 250 and h > 180:
                    return fg_hwnd, r, fg_title
    except Exception:
        pass

    # 2. 檢測置頂浮動子母畫面 (PiP / Topmost 視窗，例如 Chrome / Edge 懸浮看片)
    pip_hwnd, pip_rect, pip_title = None, None, ""
    def _enum_topmost_cb(hwnd, _):
        nonlocal pip_hwnd, pip_rect, pip_title
        try:
            if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
                import win32con
                ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                if ex_style & win32con.WS_EX_TOPMOST:
                    title = win32gui.GetWindowText(hwnd)
                    if is_video_window(hwnd, title) or any(k in title.lower() for k in ["picture-in-picture", "子母畫面", "畫中畫", "浮動視窗"]):
                        r = win32gui.GetWindowRect(hwnd)
                        w, h = r[2] - r[0], r[3] - r[1]
                        if w > 160 and h > 120:
                            pip_hwnd = hwnd
                            pip_rect = r
                            pip_title = title
                            return False
        except Exception:
            pass
        return True

    try:
        import win32con
        win32gui.EnumWindows(_enum_topmost_cb, None)
    except Exception:
        pass

    return pip_hwnd, pip_rect, pip_title

# 向下相容別名
find_youtube_window = find_video_window

def _is_hwnd_alive(hwnd) -> bool:
    """檢查授權時的原始影音視窗是否還存在（允許背景/非前景，只排除關閉/隱藏）"""
    if not hwnd or not HAS_WIN32:
        return False
    try:
        if not win32gui.IsWindow(hwnd):
            return False
        if not win32gui.IsWindowVisible(hwnd):
            return False
        return True
    except Exception:
        return False

def _get_hwnd_rect(hwnd):
    """取得指定 hwnd 目前的視窗座標，失敗回傳 None"""
    if not hwnd or not HAS_WIN32:
        return None
    try:
        r = win32gui.GetWindowRect(hwnd)
        w, h = r[2] - r[0], r[3] - r[1]
        if w > 100 and h > 80:
            return r
    except Exception:
        pass
    return None

def _get_hwnd_title(hwnd) -> str:
    """取得指定 hwnd 目前的標題，失敗回傳空字串"""
    if not hwnd or not HAS_WIN32:
        return ""
    try:
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""

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
你正在充當 7L 的眼睛與耳朵，透過即時畫面串流與系統原聲音訊，觀看主人電腦上正在播放的影片（包含 YouTube、Bilibili、巴哈動畫瘋、Netflix、本機影音播放器等所有影音視窗）。

【核心規則】：
1. 【絕對靜音】：你不是對話助手，不要對主人說話，保持安靜。
2. 【記憶沉澱記錄員】：你的職責是將影片內容提煉為「劇情與情境筆記」，存入 7L 的記憶庫。
3. 【記錄格式】：每當收到記錄信號或劇情發生關鍵轉折，用繁體中文記錄 1~2 句話：
   - 畫面動作、字幕與文字重點
   - 角色說了什麼關鍵台詞、笑點或情節進展
   - 保持生動、具體、客觀（例如：「主角在電車難題選了撞 4 公斤，說比較不會痛...」）。
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
    log_print(f"👁️👂 [影音眼耳沉澱] ({time_str}): {clean}")

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
        f"【🎬 7L 雙眼與雙耳感知的即時影片伴看記憶】",
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
    """單次影片伴看感官連線"""
    global _live_session, _loopback_streamer
    global IS_YT_COMPANION_ACTIVE, CURRENT_YT_TITLE

    if not GEMINI_KEYS:
        log_print("❌ [影音眼耳] 無可用 GEMINI_KEYS，無法啟動感官串流")
        return

    api_key = GEMINI_KEYS[0]
    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")

    CURRENT_YT_TITLE = initial_title
    IS_YT_COMPANION_ACTIVE = True
    sys_notify(f"👀 啟動眼耳伴看: {initial_title[:25]}...")
    log_print(f"🎬 [影音眼耳] 正在為影音視窗啟動感官串流: {initial_title[:40]}...")

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
            log_print(f"✅ [影音眼耳] 感官神經連線就緒！開始默默吸收畫面與聲音。")

            session_running = True
            last_seen_time = time.time()
            current_rect = initial_rect

            # 啟動時沉澱第一筆認知
            add_perception_memory(f"開始陪伴老爸觀看影片《{initial_title[:30]}》")

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

            # 任務 2: 系統音訊採集
            async def _audio_worker():
                nonlocal session_running
                while session_running and IS_YT_WATCHER_ENABLED:
                    try:
                        pcm_chunk = _loopback_streamer.audio_queue.get_nowait()
                        if pcm_chunk:
                            await session.send_realtime_input(
                                audio=types.Blob(data=pcm_chunk, mime_type="audio/pcm;rate=16000")
                            )
                    except queue.Empty:
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

            # 視窗持續存在性檢查（鎖定授權時的 target_hwnd，允許暫時切到後台點允許）
            # 原 4 秒嚴格前景斷線會導致「切去後台按允許就放棄」，現改為：
            # - 只要原始視窗還存在就繼續串流（聲音 loopback 本來就是全域的）
            # - 前景回來時即時校正座標/標題；背景超過 90 秒才休眠省 Token
            last_foreground_time = time.time()
            last_seen_time = time.time()
            while session_running and IS_YT_WATCHER_ENABLED:
                hwnd, rect, title = find_video_window()
                now = time.time()
                if hwnd:
                    # 有前景影音視窗：若是同一個或新的都接受，更新座標
                    last_seen_time = now
                    last_foreground_time = now
                    try:
                        # 若切到另一個影片，直接跟隨新視窗
                        if hwnd != target_hwnd:
                            target_hwnd = hwnd
                    except Exception:
                        pass
                    current_rect = rect
                    CURRENT_YT_TITLE = title
                else:
                    # 前景沒有影片（老爸切去後台按允許 / 回訊息很正常）
                    if _is_hwnd_alive(target_hwnd):
                        last_seen_time = now
                        fresh_rect = _get_hwnd_rect(target_hwnd)
                        if fresh_rect:
                            current_rect = fresh_rect
                        fresh_title = _get_hwnd_title(target_hwnd)
                        if fresh_title:
                            CURRENT_YT_TITLE = fresh_title
                        if now - last_foreground_time > 90.0:
                            log_print("💤 [影音眼耳] 影片視窗已在背景超過 90 秒，自動休眠斷線省 Token。切回影片會重新請求伴看。")
                            session_running = False
                            break
                    else:
                        # 原始視窗真的被關掉了：給 10 秒寬限（可能只是換集/轉址閃一下）
                        if now - last_seen_time > 10.0:
                            log_print("💤 [影音眼耳] 原始影片視窗已關閉，自動休眠斷線。")
                            session_running = False
                            break

                await asyncio.sleep(1.0)

            v_task.cancel()
            a_task.cancel()
            m_task.cancel()
            r_task.cancel()

    except Exception as e:
        log_print(f"⚠️ [影音眼耳] 感官連線中斷: {e}")
    finally:
        _live_session = None
        IS_YT_COMPANION_ACTIVE = False
        LATEST_YT_FRAME_BYTES = None

async def start_yt_auto_watcher():
    """背景守護協程：持續偵測影音視窗出現，偵測到後向後台發授權請求，等老爸點擊「允許」才啟動感官串流"""
    global _COMPANION_APPROVAL_EVENT, _COMPANION_REJECTION_FLAG, _COMPANION_PENDING_TITLE
    log_print("👀 [影音眼耳雷達] 全視窗影音偵測守護已啟動（偵測到影片視窗將向後台請求老爸授權）")
    _last_rejected_title = ""   # 記錄上次被拒絕的標題，避免對同一視窗反覆彈窗
    _reject_cooldown = 0.0      # 拒絕後的冷卻時間戳記

    while True:
        try:
            if IS_YT_WATCHER_ENABLED and not IS_YT_COMPANION_ACTIVE:
                hwnd, rect, title = find_video_window()
                if hwnd:
                    # 若與上次拒絕的視窗相同，且冷卻時間 (120 秒) 未到，跳過避免重複彈窗
                    if title == _last_rejected_title and time.time() - _reject_cooldown < 120:
                        await asyncio.sleep(2.0)
                        continue

                    # 建立新的授權事件，向後台發送伴看授權請求
                    _COMPANION_APPROVAL_EVENT = asyncio.Event()
                    _COMPANION_REJECTION_FLAG = False
                    _COMPANION_PENDING_TITLE = title

                    # 透過 web_dashboard 廣播授權請求通知
                    try:
                        import services.web_dashboard as web_dash
                        web_dash.broadcast_event("yt_companion_request", {
                            "title": title,
                            "short_title": title[:35],
                        })
                        log_print(f"📺 [影音眼耳雷達] 偵測到影音視窗《{title[:30]}》，已向後台發送伴看授權請求，等待老爸確認...")
                    except Exception as be:
                        log_print(f"⚠️ [伴看授權廣播] 廣播失敗: {be}")

                    # 等待老爸點擊允許或拒絕 (最多等 60 秒，超時自動放棄)
                    try:
                        await asyncio.wait_for(_COMPANION_APPROVAL_EVENT.wait(), timeout=60.0)
                    except asyncio.TimeoutError:
                        log_print("⏰ [伴看授權] 等待逾時 60 秒，本次自動放棄伴看。")
                        _COMPANION_PENDING_TITLE = ""
                        _last_rejected_title = title
                        _reject_cooldown = time.time()
                        await asyncio.sleep(2.0)
                        continue

                    _COMPANION_PENDING_TITLE = ""

                    if _COMPANION_REJECTION_FLAG:
                        # 老爸拒絕：記錄冷卻，不啟動
                        _last_rejected_title = title
                        _reject_cooldown = time.time()
                        await asyncio.sleep(2.0)
                        continue

                    # 老爸批准：以「授權當時鎖定的原始視窗」為準，不要求仍在前景
                    # （老爸要切去後台點允許，前景一定會變成後台，這是正常的）
                    use_hwnd, use_rect, use_title = None, None, ""
                    if _is_hwnd_alive(hwnd):
                        use_hwnd = hwnd
                        use_rect = _get_hwnd_rect(hwnd) or rect
                        use_title = _get_hwnd_title(hwnd) or title
                        log_print(f"✅ [伴看授權] 原始影片視窗仍在（已切後台也沒關係），直接鎖定開始伴看: {use_title[:30]}...")
                    else:
                        # 原視窗真的關了，才嘗試找新的前景影音視窗
                        hwnd2, rect2, title2 = find_video_window()
                        if hwnd2:
                            use_hwnd, use_rect, use_title = hwnd2, rect2, title2
                    if use_hwnd:
                        await _yt_companion_session_loop(use_hwnd, use_rect, use_title)
                    else:
                        log_print("⚠️ [伴看授權] 授權後原始影片視窗已關閉，本次放棄。")
                        # 短冷卻避免立刻重複彈窗洗版
                        _last_rejected_title = title
                        _reject_cooldown = time.time() - 110.0  # 剩 ~10 秒冷卻

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
