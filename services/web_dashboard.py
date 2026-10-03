import asyncio
import base64
import json
import os
import time
import re
from typing import Set, Dict, Any, Optional
from aiohttp import web
import services.tiktok_listener as tk_listener

from datetime import datetime
import logging
from core.utils import record_interaction_tick

# 🔇 關閉 aiohttp.access 日誌，避免輪詢視覺畫面或狀態時在終端洗版
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

# 📡 WebSocket 連線集與主執行緒 Event Loop
CONNECTED_CLIENTS: Set[web.WebSocketResponse] = set()
MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None

# 共享控制介面
INPUT_QUEUE: Optional[asyncio.Queue] = None
VTS_CLIENT: Any = None
GET_SYSTEM_STATE_CALLBACK = None
SET_MIC_CALLBACK = None
SET_SLEEP_CALLBACK = None
TRIGGER_EXPRESSION_CALLBACK = None
GET_RECENT_MEMORY_CALLBACK = None
GET_MIND_BOARD_CALLBACK = None
GET_LAST_VISION_IMAGE_CALLBACK = None
RESTART_CALLBACK = None
SHUTDOWN_CALLBACK = None
EXECUTE_TOOL_CALLBACK = None
GET_TOOLS_CALLBACK = None
GET_SWITCHES_CALLBACK = None
SET_SWITCH_CALLBACK = None
PUNISH_CALLBACK = None
REWARD_CALLBACK = None
APPROVE_YT_COMPANION_CALLBACK = None
REJECT_YT_COMPANION_CALLBACK = None

# 🛠️ 7L 工具調用紀錄隊列 (保持最近 200 筆)
TOOL_HISTORY: list = []

def record_tool_call(
    tool_name: str,
    args: Any = None,
    result: Any = None,
    caller: str = "7L",
    status: str = "success",
    duration_ms: float = 0.0,
    error: str = ""
) -> Dict[str, Any]:
    """登錄一筆工具調用紀錄，並即時向前端所有用戶端廣播"""
    global TOOL_HISTORY
    now = datetime.now()
    record = {
        "id": f"tc_{int(time.time() * 1000)}_{len(TOOL_HISTORY)}",
        "timestamp": time.time(),
        "time_str": now.strftime("%H:%M:%S"),
        "date_str": now.strftime("%Y-%m-%d"),
        "tool": tool_name,
        "args": args if isinstance(args, (dict, list)) else {"value": str(args) if args is not None else ""},
        "result": result,
        "caller": caller,
        "status": status,
        "duration_ms": round(duration_ms, 1),
        "error": str(error) if error else ""
    }
    TOOL_HISTORY.insert(0, record)
    if len(TOOL_HISTORY) > 200:
        TOOL_HISTORY.pop()
    broadcast_event("tool_call", record)
    return record

# 📦 內建可用工具目錄規格 (供老爸手動調用工作台使用)
DEFAULT_TOOLS_CATALOG = [
    {
        "name": "pe.play_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "演奏鋼琴曲目",
        "description": "讓 7L 坐到 88 鍵平台鋼琴前演奏指定曲目，支援本地 MIDI 與 YouTube 即時扒譜開彈。",
        "parameters": [
            {
                "name": "song_name",
                "label": "曲目名稱",
                "type": "string",
                "default": "鐘",
                "placeholder": "例如：鐘、卡農、幻想即興曲、神隱少女、Rush E",
                "required": True,
                "presets": ["鐘", "卡農", "幻想即興曲", "愛之夢", "月光奏鳴曲第三樂章", "Rush E", "千本櫻", "打上花火", "殘酷天使的行動綱領"]
            },
            {
                "name": "force_online",
                "label": "線上 YouTube 搜尋抓譜",
                "type": "boolean",
                "default": False,
                "description": "強制略過本地樂譜，直接向 YouTube 線上爬取演奏版本"
            }
        ]
    },
    {
        "name": "pe.compose_and_play_original_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "現場即興作曲演奏",
        "description": "7L 當場自主即興創作一首全新 88 鍵鋼琴原創曲目並即刻彈奏給老爸聽。",
        "parameters": [
            {
                "name": "theme_or_title",
                "label": "曲目主題 / 標題",
                "type": "string",
                "default": "星空漫步",
                "placeholder": "例如：給老爸的歌、深夜寫代碼、午後雨聲",
                "required": False,
                "presets": ["星空漫步", "給老爸的歌", "雨夜沉思", "賽博龐克之夢", "櫻花飄落時", "程式碼狂想曲"]
            },
            {
                "name": "mood_or_style",
                "label": "音樂風格 / 情緒",
                "type": "string",
                "default": "治癒抒情",
                "placeholder": "例如：治癒抒情、日系ACG、輕快俏皮、溫柔憂傷",
                "required": False,
                "presets": ["治癒抒情", "日系ACG", "輕快俏皮", "溫柔憂傷", "震撼史詩", "爵士狂想"]
            }
        ]
    },
    {
        "name": "pe.mashup_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "多曲極限串燒演奏",
        "description": "同時並發合體多首鋼琴曲目，多軌多色瀑布流極限演奏。",
        "parameters": [
            {
                "name": "song_name1",
                "label": "第一首曲目 / 複合歌名",
                "type": "string",
                "default": "冬風",
                "placeholder": "例如：冬風 或 冬風 x 月光 x 鐘",
                "required": True,
                "presets": ["冬風", "鐘", "月光第三樂章", "Rush E", "冬風 x 月光 x 鐘"]
            },
            {
                "name": "song_name2",
                "label": "第二首曲目 (可選)",
                "type": "string",
                "default": "月光第三樂章",
                "placeholder": "例如：月光第三樂章",
                "required": False,
                "presets": ["月光第三樂章", "鐘", "卡農", "野蜂飛舞"]
            }
        ]
    },
    {
        "name": "pe.insert_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "插播 / 追加曲目",
        "description": "在當前演奏中立即插播或加軌合奏指定曲目。",
        "parameters": [
            {
                "name": "song_name",
                "label": "追加曲目名稱",
                "type": "string",
                "default": "少女的祈禱",
                "required": True,
                "presets": ["少女的祈禱", "卡農", "夢中的婚禮", "野蜂飛舞"]
            }
        ]
    },
    {
        "name": "pe.set_piano_instrument",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "切換鋼琴發聲音色",
        "description": "即時更換虛擬鋼琴的聲音音色 (SoundFont 樂器)。",
        "parameters": [
            {
                "name": "instrument",
                "label": "發聲音色",
                "type": "select",
                "default": "鋼琴",
                "required": True,
                "options": ["鋼琴", "明亮鋼琴", "電鋼琴", "管風琴", "大鍵琴", "木琴", "手風琴", "吉他", "電吉他", "小提琴", "大提琴", "豎琴", "弦樂", "人聲合唱", "小號", "薩克斯風", "長笛", "合成器", "古箏", "卡林巴"]
            }
        ]
    },
    {
        "name": "pe.set_piano_speed",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "調整演奏速度",
        "description": "動態加快或減慢鋼琴演奏速度 (倍率 0.5x ~ 2.5x)。",
        "parameters": [
            {
                "name": "speed",
                "label": "演奏倍速",
                "type": "number",
                "default": 1.0,
                "min": 0.5,
                "max": 2.5,
                "step": 0.05,
                "presets": [0.75, 1.0, 1.25, 1.5, 2.0]
            }
        ]
    },
    {
        "name": "pe.set_piano_volume",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "調整演奏音量",
        "description": "調整 88 鍵虛擬鋼琴的輸出音量 (0 ~ 100)。",
        "parameters": [
            {
                "name": "volume",
                "label": "音量數值",
                "type": "number",
                "default": 85,
                "min": 0,
                "max": 100,
                "step": 5,
                "presets": [30, 60, 85, 100]
            }
        ]
    },
    {
        "name": "pe.open_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "打開鋼琴介面待命",
        "description": "在螢幕上召喚 88 鍵鋼琴並讓 7L 就位，不立即播放曲目。",
        "parameters": []
    },
    {
        "name": "pe.pause_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "暫停鋼琴演奏",
        "description": "暫停當前正在彈奏的曲目進度。",
        "parameters": []
    },
    {
        "name": "pe.resume_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "繼續鋼琴演奏",
        "description": "恢復剛才暫停的鋼琴演奏。",
        "parameters": []
    },
    {
        "name": "pe.stop_virtual_piano",
        "category": "piano",
        "category_name": "鋼琴演奏",
        "label": "停止演奏並收起鋼琴",
        "description": "停止所有鋼琴聲音並關閉鋼琴介面，7L 歸位。",
        "parameters": []
    },
    {
        "name": "move_spatial_position",
        "category": "live2d",
        "category_name": "Live2D 空間",
        "label": "空間站位移動",
        "description": "平滑移動 7L 模型在螢幕上的位置或縮放大小。",
        "parameters": [
            {
                "name": "target_position",
                "label": "目標站位",
                "type": "select",
                "default": "正中間",
                "required": True,
                "options": ["正中間", "鋼琴旁", "靠近", "躲角落", "左邊", "右邊", "原位", "放大+10", "縮小-5", "往上+5", "往下-10", "自由漫遊"]
            }
        ]
    },
    {
        "name": "trigger_vts_expression",
        "category": "live2d",
        "category_name": "Live2D 空間",
        "label": "切換 VTS 表情",
        "description": "切換 7L 臉部 Live2D 情感表情或重置為自然狀態。",
        "parameters": [
            {
                "name": "expression_name",
                "label": "表情名稱",
                "type": "select",
                "default": "自然",
                "required": True,
                "options": ["自然", "害羞臉紅", "愛心眼", "生氣嘟嘴", "流淚哭泣", "驚訝瞪大", "眩暈轉轉眼", "陰暗黑化", "閉眼安睡"]
            }
        ]
    },
    {
        "name": "control_microphone",
        "category": "system",
        "category_name": "系統與語音",
        "label": "麥克風收音開關",
        "description": "開啟或靜音 7L 對現實麥克風的聲音收音傾聽。",
        "parameters": [
            {
                "name": "is_enabled",
                "label": "開啟收音 (True=開, False=關)",
                "type": "boolean",
                "default": True
            }
        ]
    },
    {
        "name": "set_sleep_mode",
        "category": "system",
        "category_name": "系統與語音",
        "label": "深層休眠 / 喚醒模式",
        "description": "切換 7L 深層休眠 (0 API 額度消耗) 或喚醒狀態。",
        "parameters": [
            {
                "name": "enable",
                "label": "休眠狀態 (True=休眠, False=喚醒)",
                "type": "boolean",
                "default": False
            }
        ]
    },
    {
        "name": "set_timer",
        "category": "system",
        "category_name": "系統與語音",
        "label": "設定計時器 / 鬧鐘",
        "description": "設定定時器，倒數計時結束時 7L 將開口提醒老爸。",
        "parameters": [
            {
                "name": "seconds",
                "label": "倒數秒數",
                "type": "number",
                "default": 60,
                "min": 1,
                "max": 86400,
                "presets": [30, 60, 180, 300, 600, 1800]
            },
            {
                "name": "message",
                "label": "提醒內容",
                "type": "string",
                "default": "番茄鐘時間到！老爸該起來喝水休息一下囉～"
            }
        ]
    },
    {
        "name": "open_browser",
        "category": "system",
        "category_name": "系統與語音",
        "label": "開啟瀏覽器網頁",
        "description": "在老爸電腦的預設瀏覽器中開啟指定 URL 網址。",
        "parameters": [
            {
                "name": "url",
                "label": "網址 URL",
                "type": "string",
                "default": "https://www.google.com",
                "required": True,
                "placeholder": "https://..."
            }
        ]
    },
    {
        "name": "search_google",
        "category": "system",
        "category_name": "系統與語音",
        "label": "Google 聯網搜尋",
        "description": "透過 Google 搜尋即時時事、氣象、股市或百科資訊。",
        "parameters": [
            {
                "name": "query",
                "label": "搜尋關鍵字",
                "type": "string",
                "default": "台灣今天最新天氣",
                "required": True,
                "placeholder": "例如：台北即時天氣、科技新聞"
            }
        ]
    },
    {
        "name": "update_cloud_knowledge",
        "category": "mind",
        "category_name": "記憶與大腦",
        "label": "寫入雲端大腦認知",
        "description": "將新知識、老爸習慣或世界觀設定永久寫入 Firestore 雲端大腦。",
        "parameters": [
            {
                "name": "category",
                "label": "認知類別",
                "type": "select",
                "default": "facts",
                "required": True,
                "options": ["facts", "memes", "rules", "persona_core", "conversation_style", "streamer_bio", "banned_phrases"]
            },
            {
                "name": "content",
                "label": "內容描述",
                "type": "string",
                "default": "老爸今天在調整 7L 核心工作台",
                "required": True,
                "placeholder": "要寫入的認知事實或設定"
            }
        ]
    },
    {
        "name": "clear_all_memories",
        "category": "mind",
        "category_name": "記憶與大腦",
        "label": "清空短期記憶時間線",
        "description": "重置並清空 7L 當前對話歷史與看板暫存紀錄。",
        "parameters": []
    },
    {
        "name": "generate_ai_image",
        "category": "creative",
        "category_name": "多模態創作",
        "label": "AI 繪圖插畫生成",
        "description": "調用 Google Imagen 或繪圖模型生成 AI 插畫並展示在相框中。",
        "parameters": [
            {
                "name": "prompt",
                "label": "繪圖提示詞 (Prompt)",
                "type": "string",
                "default": "cute anime girl with silver hair playing grand piano in a neon glass cyberpunk room",
                "required": True,
                "placeholder": "輸入插畫場景描繪"
            }
        ]
    },
    {
        "name": "sing_song",
        "category": "creative",
        "category_name": "多模態創作",
        "label": "AI 翻唱歌手歌聲合成",
        "description": "啟動 AI 歌聲生成引擎翻唱指定歌曲並播放音訊。",
        "parameters": [
            {
                "name": "song_name",
                "label": "歌曲名稱",
                "type": "string",
                "default": "夜に駆ける",
                "required": True,
                "placeholder": "例如：Lemon, 勇者, 晴天"
            }
        ]
    }
]

# 最近廣播的事件緩存（讓剛開啟網頁的使用者能立即看到最近彈幕與發言）
RECENT_EVENTS = []

def broadcast_event(event_type: str, data: Dict[str, Any]):
    """向所有已連接的瀏覽器用戶端即時推送事件（支援跨線程調用）"""
    global RECENT_EVENTS, MAIN_EVENT_LOOP
    payload = {
        "type": event_type,
        "timestamp": time.time(),
        "data": data
    }
    RECENT_EVENTS.append(payload)
    if len(RECENT_EVENTS) > 60:
        RECENT_EVENTS.pop(0)

    if not CONNECTED_CLIENTS:
        return

    msg = json.dumps(payload, ensure_ascii=False)
    
    def _send_all():
        for ws in list(CONNECTED_CLIENTS):
            if not ws.closed:
                asyncio.create_task(_safe_send(ws, msg))

    try:
        current_loop = asyncio.get_running_loop()
        _send_all()
    except RuntimeError:
        # 當前處於背景 worker 線程（如 GPT-SoVITS 合成線程），轉交由主事件迴圈安全派發
        if MAIN_EVENT_LOOP and MAIN_EVENT_LOOP.is_running():
            MAIN_EVENT_LOOP.call_soon_threadsafe(_send_all)
        else:
            pass

def broadcast_telemetry():
    """向所有客戶端立即推送一次系統遙測快照"""
    async def _push():
        if CONNECTED_CLIENTS:
            data = await get_full_telemetry()
            msg = json.dumps({
                "type": "telemetry",
                "timestamp": time.time(),
                "data": data
            }, ensure_ascii=False)
            for ws in list(CONNECTED_CLIENTS):
                if not ws.closed:
                    await _safe_send(ws, msg)
    asyncio.create_task(_push())

async def _safe_send(ws: web.WebSocketResponse, msg: str):
    try:
        await ws.send_str(msg)
    except Exception:
        pass

async def ws_handler(request):
    """處理瀏覽器 WebSocket 即時連線"""
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    CONNECTED_CLIENTS.add(ws)

    # 首次連線發送初始狀態包 (包含完整 300 句全景記憶時間線)
    try:
        initial_state = await get_full_telemetry(include_full_memory=True)
        await ws.send_str(json.dumps({
            "type": "init",
            "timestamp": time.time(),
            "data": initial_state,
            "recent_events": RECENT_EVENTS[-20:],
            "tool_history": TOOL_HISTORY[:40]
        }, ensure_ascii=False))

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    action = data.get("action")
                    if action == "ping":
                        await ws.send_str(json.dumps({"type": "pong", "timestamp": time.time()}))
                    elif action == "send_chat":
                        text = data.get("text", "").strip()
                        if text and INPUT_QUEUE:
                            await INPUT_QUEUE.put({
                                "text": text,
                                "audio_base64": None,
                                "timestamp": time.time(),
                                "source": "web_console"
                            })
                            broadcast_event("chat_sent", {"text": text, "from": "老爸"})
                    elif action == "toggle_mic":
                        enable = data.get("enable")
                        if SET_MIC_CALLBACK:
                            new_state = SET_MIC_CALLBACK(enable)
                            broadcast_event("mic_changed", {"is_mic_enabled": new_state})
                    elif action == "set_sleep":
                        enable = bool(data.get("enable", True))
                        if SET_SLEEP_CALLBACK:
                            new_state = await SET_SLEEP_CALLBACK(enable)
                            broadcast_event("sleep_changed", {"is_sleeping": new_state})
                    elif action == "set_expression":
                        expr = data.get("expression")
                        if TRIGGER_EXPRESSION_CALLBACK and expr:
                            await TRIGGER_EXPRESSION_CALLBACK(expr)
                            broadcast_event("expression_changed", {"expression": expr})
                    elif action == "execute_tool":
                        tool_name = data.get("tool")
                        args = data.get("args", {})
                        t_start = time.time()
                        try:
                            if EXECUTE_TOOL_CALLBACK:
                                res = EXECUTE_TOOL_CALLBACK(tool_name, args)
                                if asyncio.iscoroutine(res):
                                    res = await res
                                dur = (time.time() - t_start) * 1000
                                rec = record_tool_call(tool_name, args, res, caller="老爸 (手動調用)", status="success", duration_ms=dur)
                                await ws.send_str(json.dumps({"type": "tool_executed", "data": {"ok": True, "record": rec}}, ensure_ascii=False))
                            else:
                                dur = (time.time() - t_start) * 1000
                                rec = record_tool_call(tool_name, args, None, caller="老爸 (手動調用)", status="error", duration_ms=dur, error="工具執行器未就緒")
                                await ws.send_str(json.dumps({"type": "tool_executed", "data": {"ok": False, "error": "工具執行器未就緒", "record": rec}}, ensure_ascii=False))
                        except Exception as err:
                            dur = (time.time() - t_start) * 1000
                            rec = record_tool_call(tool_name, args, None, caller="老爸 (手動調用)", status="error", duration_ms=dur, error=str(err))
                            await ws.send_str(json.dumps({"type": "tool_executed", "data": {"ok": False, "error": str(err), "record": rec}}, ensure_ascii=False))
                    elif action == "clear_tool_history":
                        TOOL_HISTORY.clear()
                        broadcast_event("tools_cleared", {})
                    elif action == "restart":
                        broadcast_event("system_restart", {"message": "7L 系統正在重新啟動中..."})
                        asyncio.create_task(perform_restart())
                    elif action == "shutdown":
                        broadcast_event("system_shutdown", {"message": "7L 系統正在安全關機退出..."})
                        asyncio.create_task(perform_shutdown())
                    elif action == "approve_yt_companion":
                        if APPROVE_YT_COMPANION_CALLBACK:
                            ok = bool(APPROVE_YT_COMPANION_CALLBACK())
                            await ws.send_str(json.dumps({"type": "yt_companion_status", "data": {"ok": ok}}, ensure_ascii=False))
                    elif action == "reject_yt_companion":
                        if REJECT_YT_COMPANION_CALLBACK:
                            REJECT_YT_COMPANION_CALLBACK()
                            await ws.send_str(json.dumps({"type": "yt_companion_status", "data": {"ok": True, "status": "rejected"}}, ensure_ascii=False))
                except Exception as ex:
                    print(f"⚠️ [Web後台 WS處理異常]: {ex}")
    finally:
        CONNECTED_CLIENTS.discard(ws)
    return ws

async def get_full_telemetry(include_full_memory: bool = False) -> Dict[str, Any]:
    """收集 7L 核心狀態與直播情報快照"""
    core_state = {}
    if GET_SYSTEM_STATE_CALLBACK:
        try:
            core_state = GET_SYSTEM_STATE_CALLBACK() or {}
        except Exception:
            pass

    # TikTok 直播間情報
    target_ids = tk_listener.get_target_tiktok_ids()
    active_id = getattr(tk_listener, "ACTIVE_TIKTOK_ID", "")
    is_streaming = getattr(tk_listener, "IS_STREAMING", False)
    v_cnt = getattr(tk_listener, "TIKTOK_VIEWER_COUNT", 0)
    l_cnt = getattr(tk_listener, "TIKTOK_LIKE_COUNT", 0)
    status_str = getattr(tk_listener, "current_tiktok_status_str", "[📱 TikTok: 待命中]")

    # 記憶與黑板
    mind_board = []
    if GET_MIND_BOARD_CALLBACK:
        try:
            mind_board = GET_MIND_BOARD_CALLBACK() or []
        except Exception:
            pass

    recent_memory = []
    if include_full_memory:
        if GET_RECENT_MEMORY_CALLBACK:
            try:
                recent_memory = GET_RECENT_MEMORY_CALLBACK() or []
            except Exception:
                pass
        if not recent_memory:
            try:
                _m = (os.getenv("MODE") or "vtuber").strip().lower()
                if _m not in ("companion", "vtuber"):
                    _m = "vtuber"
                mem_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", f"unified_memory_{_m}.json")
                if os.path.exists(mem_path):
                    with open(mem_path, "r", encoding="utf-8") as f:
                        recent_memory = json.load(f)
            except Exception:
                pass

    return {
        "core": core_state,
        # 🚦 系統開關旗標（前端用來提示：操作者輸入/發聲是否停用）
        "system_flags": {
            "operator_input": (os.getenv("OPERATOR_INPUT", "0") or "0").strip().lower() in ("1", "true", "yes"),
            "operator_speech": (os.getenv("OPERATOR_SPEECH", "0") or "0").strip().lower() in ("1", "true", "yes"),
        },
        "tiktok": {
            "is_streaming": is_streaming,
            "active_id": active_id,
            "target_ids": target_ids,
            "viewer_count": v_cnt,
            "like_count": l_cnt,
            "status_str": status_str,
            "telemetry_text": tk_listener.get_tiktok_live_telemetry()
        },
        "mind_board": mind_board[-10:] if isinstance(mind_board, list) else [],
        "recent_memory": recent_memory[-300:] if isinstance(recent_memory, list) else []
    }

async def api_status(request):
    """取得系統目前快照 (包含完整 300 句全景記憶)"""
    data = await get_full_telemetry(include_full_memory=True)
    return web.json_response(data)

async def api_get_memory(request):
    """取得 7L 全景記憶時間線 (最多 300 句完整對話歷史)"""
    recent_memory = []
    if GET_RECENT_MEMORY_CALLBACK:
        try:
            recent_memory = GET_RECENT_MEMORY_CALLBACK() or []
        except Exception:
            pass
    if not recent_memory:
        try:
            mem_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "unified_memory.json")
            if os.path.exists(mem_path):
                with open(mem_path, "r", encoding="utf-8") as f:
                    recent_memory = json.load(f)
        except Exception:
            pass

    memories = recent_memory[-300:] if isinstance(recent_memory, list) else []
    return web.json_response({
        "ok": True,
        "count": len(memories),
        "memories": memories
    })

async def api_get_memory_all(request):
    """取得 7L 全景記憶庫所有項目（帶全局唯一索引）"""
    from core.memory import get_all_unified_memories
    memories = get_all_unified_memories()
    return web.json_response({
        "ok": True,
        "count": len(memories),
        "memories": memories
    })

async def api_update_memory(request):
    """修改指定索引的記憶內容"""
    try:
        data = await request.json()
        idx = int(data.get("index", -1))
        content = str(data.get("content", "")).strip()
        speaker = data.get("speaker")
        role = data.get("role")
        if idx < 0 or not content:
            return web.json_response({"ok": False, "error": "參數不完整"}, status=400)
        from core.memory import update_unified_memory_item
        success = update_unified_memory_item(idx, content, speaker=speaker, role=role)
        return web.json_response({"ok": success})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_delete_memory(request):
    """刪除指定索引的記憶"""
    try:
        data = await request.json()
        idx = int(data.get("index", -1))
        if idx < 0:
            return web.json_response({"ok": False, "error": "無效的記憶索引"}, status=400)
        from core.memory import delete_unified_memory_item
        success = delete_unified_memory_item(idx)
        return web.json_response({"ok": success})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_add_memory(request):
    """手動新增一筆記憶至 7L 記憶庫"""
    try:
        data = await request.json()
        speaker = str(data.get("speaker", "老爸")).strip()
        content = str(data.get("content", "")).strip()
        role = str(data.get("role", "user")).strip()
        target = str(data.get("target", "7L")).strip()
        source = str(data.get("source", "dashboard_manual")).strip()
        if not content:
            return web.json_response({"ok": False, "error": "內容不能為空"}, status=400)
        from core.memory import append_to_unified_memory
        append_to_unified_memory(speaker=speaker, target=target, content=content, role=role, source=source)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_clean_duplicate_memories(request):
    """一鍵清理重複與跳針記憶"""
    try:
        from core.memory import clean_duplicate_unified_memories
        removed = clean_duplicate_unified_memories()
        return web.json_response({"ok": True, "removed_count": removed})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_clear_all_memories(request):
    """徹底清空 7L 的所有雲端與本地記憶"""
    try:
        from core.memory import clear_all_memories
        msg = await clear_all_memories()
        broadcast_event("memory_cleared", {"message": msg})
        return web.json_response({"ok": True, "message": msg})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_get_memory_capacity(request):
    """取得底層記憶池容量配置與即時數據"""
    try:
        from core.memory import get_memory_capacity_config
        res = get_memory_capacity_config()
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_set_memory_capacity(request):
    """設定底層記憶池容量（0 = 無上限）"""
    try:
        data = await request.json()
        capacity = int(data.get("capacity", 500))
        from core.memory import set_memory_capacity_config
        res = set_memory_capacity_config(capacity)
        broadcast_event("memory_capacity_updated", res)
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_get_settings(request):
    """控制台 .env 設定：讀取白名單表單（機密只回 secret_info，不回值）"""
    try:
        from core.env_config import read_settings
    except Exception as e:
        return web.json_response({"ok": False, "error": f"設定模組載入失敗: {e}"}, status=500)
    try:
        return web.json_response({"ok": True, "settings": read_settings()})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_save_settings(request):
    """控制台 .env 設定：寫入（動 .env 之前 update_settings 會自動備份上一版）"""
    try:
        body = await request.json()
        updates = body.get("settings") if isinstance(body, dict) and "settings" in body else body
        if not isinstance(updates, dict):
            return web.json_response({"ok": False, "error": "settings 必須是 {key: value} 物件"}, status=400)
        from core.env_config import update_settings
        applied, restart, errors = update_settings({str(k): ("" if v is None else str(v)) for k, v in updates.items()})
        if errors and not applied:
            return web.json_response({"ok": False, "applied": [], "restart": [], "errors": errors}, status=400)
        if restart:
            broadcast_event("settings_saved", {"applied": applied, "restart": restart,
                                               "message": "⚠️ 部分設定需重啟 V7 才生效"})
        return web.json_response({"ok": True, "applied": applied, "restart": restart, "errors": errors,
                                  "backup": ".env.backup"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_download_env_backup(request):
    """下載上一版 .env（寫入前的自動備份；不存在回 404）"""
    try:
        from core.env_config import ENV_PATH
        backup = ENV_PATH + ".backup"
        if not os.path.exists(backup):
            return web.json_response({"ok": False, "error": "尚無備份（改過一次設定才會有）"}, status=404)
        return web.FileResponse(backup, headers={"Content-Disposition": "attachment; filename=.env.backup"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_send_message(request):
    """手動發送訊息/指令給 7L"""
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "訊息內容不可為空"}, status=400)
        
        if INPUT_QUEUE:
            record_interaction_tick()
            await INPUT_QUEUE.put({
                "text": text,
                "audio_base64": None,
                "timestamp": time.time(),
                "source": "web_console"
            })
            broadcast_event("chat_sent", {"text": text, "from": "老爸 (Web後台)"})
            return web.json_response({"ok": True, "message": "已送入對話隊列"})
        return web.json_response({"ok": False, "error": "對話隊列尚未初始化"}, status=503)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_interject(request):
    """📢 擁有者公開插話：走觀眾軌道公開播出，不私聊、走觀眾工具牆（VTuber 模式唯一擁有者通道）"""
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "訊息內容不可為空"}, status=400)
        try:
            from core.identity import get_owner_name
            owner = body.get("user") or get_owner_name()
        except Exception:
            owner = body.get("user") or "主持"

        if INPUT_QUEUE:
            record_interaction_tick()
            await INPUT_QUEUE.put({
                "text": text,
                "audio_base64": None,
                "timestamp": time.time(),
                "source": "owner_interject",
                "user": owner,
            })
            broadcast_event("chat_sent", {"text": text, "from": f"{owner} (公開插話)"})
            return web.json_response({"ok": True, "message": "已送入觀眾軌道公開播出"})
        return web.json_response({"ok": False, "error": "對話隊列尚未初始化"}, status=503)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_chat_sources(request):
    """📺 直播聊天來源狀態（twitch/youtube worker 狀態＋目標頻道）"""
    try:
        from services import chat_source as cs
        return web.json_response({"ok": True, "sources": cs.chat_workers_status()})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_toggle_mic(request):
    """切換麥克風狀態"""
    try:
        body = await request.json()
        enable = body.get("enable", None)
        if SET_MIC_CALLBACK:
            new_state = SET_MIC_CALLBACK(enable)
            broadcast_event("mic_changed", {"is_mic_enabled": new_state})
            return web.json_response({"ok": True, "is_mic_enabled": new_state})
        return web.json_response({"ok": False, "error": "麥克風控制器未就緒"}, status=503)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_trigger_expression(request):
    """切換 VTS 表情"""
    try:
        body = await request.json()
        expr = body.get("expression", "").strip()
        if not expr:
            return web.json_response({"ok": False, "error": "表情名稱不可為空"}, status=400)
        
        if TRIGGER_EXPRESSION_CALLBACK:
            await TRIGGER_EXPRESSION_CALLBACK(expr)
            broadcast_event("expression_changed", {"expression": expr})
            return web.json_response({"ok": True, "expression": expr})
        return web.json_response({"ok": False, "error": "表情控制器未就緒"}, status=503)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_set_sleep(request):
    """切換 7L 睡眠模式 (0 API 消耗)"""
    try:
        body = await request.json()
        enable = bool(body.get("enable", True))
        if SET_SLEEP_CALLBACK:
            new_state = await SET_SLEEP_CALLBACK(enable)
            broadcast_event("sleep_changed", {"is_sleeping": new_state})
            return web.json_response({"ok": True, "is_sleeping": new_state})
        return web.json_response({"ok": False, "error": "睡眠控制器未就緒"}, status=503)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_punish_action(request):
    """⚡ 對 7L 實施電擊懲罰與訓誡"""
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        reason = body.get("reason", "老爸按下了微電流刺激")
        is_severe = body.get("is_severe", False)
        if PUNISH_CALLBACK:
            if asyncio.iscoroutinefunction(PUNISH_CALLBACK):
                res = await PUNISH_CALLBACK(reason, is_severe=is_severe)
            else:
                res = PUNISH_CALLBACK(reason, is_severe=is_severe)
            return web.json_response(res or {"status": "success", "message": "已執行電擊"})
        return web.json_response({"status": "error", "error": "懲罰回呼未就緒"}, status=503)
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def api_reward_action(request):
    """💖 給予 7L 摸頭獎勵與肯定"""
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        reason = body.get("reason", "表現優異 / 乖巧聽話")
        level = body.get("level", None)
        if REWARD_CALLBACK:
            if asyncio.iscoroutinefunction(REWARD_CALLBACK):
                res = await REWARD_CALLBACK(reason, level=level)
            else:
                res = REWARD_CALLBACK(reason, level=level)
            return web.json_response(res or {"status": "success", "message": "已給予獎勵"})
        return web.json_response({"status": "error", "error": "獎勵回呼未就緒"}, status=503)
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def api_get_switches(request):
    """獲取 7L 系統所有自主行為與功能開關狀態清單"""
    if GET_SWITCHES_CALLBACK:
        try:
            res = GET_SWITCHES_CALLBACK()
            if asyncio.iscoroutine(res):
                res = await res
            return web.json_response({"status": "ok", "switches": res})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)
    return web.json_response({"status": "ok", "switches": []})

async def api_toggle_switch(request):
    """切換或設置指定系統開關"""
    try:
        body = await request.json()
        key = body.get("key")
        val = body.get("value", None)
        if not key:
            return web.json_response({"status": "error", "error": "Missing switch key"}, status=400)
        if SET_SWITCH_CALLBACK:
            res = SET_SWITCH_CALLBACK(key, val)
            if asyncio.iscoroutine(res):
                res = await res
            all_switches = GET_SWITCHES_CALLBACK() if GET_SWITCHES_CALLBACK else []
            if asyncio.iscoroutine(all_switches):
                all_switches = await all_switches
            broadcast_event("switch_update", {"key": key, "value": res, "switches": all_switches})
            return web.json_response({"status": "ok", "key": key, "value": res, "switches": all_switches})
        return web.json_response({"status": "error", "error": "Switch callback not registered"}, status=503)
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def api_get_prompts(request):
    """獲取 7L 雲端大腦提示詞與認知庫 (Firestore 雲端直連)"""
    try:
        from core.memory import get_cloud_knowledge
        data = await get_cloud_knowledge()
        return web.json_response({"ok": True, "data": data})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_save_prompts(request):
    """儲存並即時同步 7L 雲端提示詞庫至 Firestore 與本地"""
    try:
        from core.memory import save_cloud_knowledge
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "資料格式錯誤"}, status=400)
        
        await save_cloud_knowledge(body)
        broadcast_event("prompts_updated", {"timestamp": time.time(), "last_updated": body.get("last_updated")})
        return web.json_response({"ok": True, "message": "雲端提示詞已成功同步至 Firestore 永久大腦！", "last_updated": body.get("last_updated")})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_reset_prompts(request):
    """恢復 7L 預設提示詞庫並同步至雲端"""
    try:
        from core.memory import DEFAULT_CLOUD_KNOWLEDGE, save_cloud_knowledge
        import copy
        default_kn = copy.deepcopy(DEFAULT_CLOUD_KNOWLEDGE)
        await save_cloud_knowledge(default_kn)
        broadcast_event("prompts_updated", {"timestamp": time.time(), "last_updated": default_kn.get("last_updated")})
        return web.json_response({"ok": True, "data": default_kn, "message": "已成功恢復為系統預設提示詞庫並同步至雲端！"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_get_tools(request):
    """取得 7L 可用工具目錄與參數清單"""
    try:
        if GET_TOOLS_CALLBACK:
            custom_catalog = GET_TOOLS_CALLBACK()
            if custom_catalog:
                return web.json_response({"ok": True, "tools": custom_catalog})
        return web.json_response({"ok": True, "tools": DEFAULT_TOOLS_CATALOG})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_get_tool_history(request):
    """取得工具調用紀錄"""
    try:
        return web.json_response({
            "ok": True,
            "total": len(TOOL_HISTORY),
            "history": TOOL_HISTORY[:100]
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_execute_tool(request):
    """老爸手動調用指定工具 API"""
    try:
        body = await request.json()
        tool_name = body.get("tool")
        args = body.get("args", {})
        if not tool_name:
            return web.json_response({"ok": False, "error": "工具名稱不可為空"}, status=400)
        
        t_start = time.time()
        if EXECUTE_TOOL_CALLBACK:
            res = EXECUTE_TOOL_CALLBACK(tool_name, args)
            if asyncio.iscoroutine(res):
                res = await res
            dur = (time.time() - t_start) * 1000
            rec = record_tool_call(tool_name, args, res, caller="老爸 (手動調用)", status="success", duration_ms=dur)
            return web.json_response({"ok": True, "result": res, "record": rec})
        else:
            dur = (time.time() - t_start) * 1000
            rec = record_tool_call(tool_name, args, None, caller="老爸 (手動調用)", status="error", duration_ms=dur, error="工具執行器未就緒")
            return web.json_response({"ok": False, "error": "工具執行器未就緒", "record": rec}, status=503)
    except Exception as e:
        dur = (time.time() - t_start) * 1000 if 't_start' in locals() else 0
        rec = record_tool_call(tool_name if 'tool_name' in locals() else "unknown", args if 'args' in locals() else {}, None, caller="老爸 (手動調用)", status="error", duration_ms=dur, error=str(e))
        return web.json_response({"ok": False, "error": str(e), "record": rec}, status=500)

async def api_clear_tool_history(request):
    """清空工具調用紀錄"""
    try:
        TOOL_HISTORY.clear()
        broadcast_event("tools_cleared", {})
        return web.json_response({"ok": True, "message": "工具調用紀錄已清空"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def perform_restart():
    """重新啟動 7L 系統核心 (安全結束子進程並重新啟動主程式)"""
    await asyncio.sleep(0.6)
    if RESTART_CALLBACK:
        try:
            res = RESTART_CALLBACK()
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            print(f"⚠️ [Web後台] 執行 RESTART_CALLBACK 失敗: {e}")
    try:
        import services.piano_engine as pe
        if pe.current_piano_process and pe.current_piano_process.poll() is None:
            pe.current_piano_process.terminate()
        if pe.SOUND_ENGINE:
            pe.SOUND_ENGINE.all_notes_off()
    except Exception:
        pass
    import subprocess
    import sys
    import os
    try:
        subprocess.Popen([sys.executable] + sys.argv)
    except Exception as e:
        print(f"⚠️ [Web後台] 重啟主進程失敗: {e}")
    os._exit(0)

async def api_restart(request):
    """重新啟動 7L 系統 API"""
    try:
        broadcast_event("system_restart", {"message": "7L 系統正在重新啟動中..."})
        asyncio.create_task(perform_restart())
        return web.json_response({"ok": True, "message": "7L 系統正在重新啟動中..."})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def perform_shutdown():
    """安全退出與清理工作"""
    await asyncio.sleep(0.6)
    if SHUTDOWN_CALLBACK:
        try:
            res = SHUTDOWN_CALLBACK()
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass
    try:
        import services.piano_engine as pe
        if pe.current_piano_process and pe.current_piano_process.poll() is None:
            pe.current_piano_process.terminate()
        if pe.SOUND_ENGINE:
            pe.SOUND_ENGINE.all_notes_off()
    except Exception:
        pass
    import os
    os._exit(0)

async def api_shutdown(request):
    """安全關閉 7L 系統 API"""
    try:
        broadcast_event("system_shutdown", {"message": "7L 系統正在安全關機退出..."})
        asyncio.create_task(perform_shutdown())
        return web.json_response({"ok": True, "message": "7L 系統正在安全關機退出..."})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_yt_companion_approve(request):
    if APPROVE_YT_COMPANION_CALLBACK:
        try:
            ok = bool(APPROVE_YT_COMPANION_CALLBACK())
            return web.json_response({"ok": ok})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    return web.json_response({"ok": False, "error": "Callback not initialized"}, status=500)

async def api_yt_companion_reject(request):
    if REJECT_YT_COMPANION_CALLBACK:
        try:
            REJECT_YT_COMPANION_CALLBACK()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    return web.json_response({"ok": False, "error": "Callback not initialized"}, status=500)

LAST_CACHED_IMG_HASH = None
LAST_CACHED_THUMB_BYTES = None

def get_optimized_thumbnail_bytes(raw_bytes: bytes, target_w: int = 720) -> bytes:
    """將畫面縮圖為高畫質清晰預覽圖，附帶 MD5 快取 (保留超高清細節，極速載入解碼)"""
    global LAST_CACHED_IMG_HASH, LAST_CACHED_THUMB_BYTES
    if not raw_bytes:
        return b""
    try:
        import hashlib
        raw_hash = hashlib.md5(raw_bytes[:4096]).hexdigest()
        if raw_hash == LAST_CACHED_IMG_HASH and LAST_CACHED_THUMB_BYTES:
            return LAST_CACHED_THUMB_BYTES

        from PIL import Image
        import io
        im = Image.open(io.BytesIO(raw_bytes))
        w, h = im.size
        # 預覽相框保持 720px 高畫質縮圖，減少 75% 傳輸量並消除前端解碼長任務卡頓
        if w > target_w:
            new_h = int(h * (target_w / w))
            im = im.resize((target_w, new_h), Image.Resampling.BILINEAR)
        out_buf = io.BytesIO()
        im.save(out_buf, format="JPEG", quality=75)
        thumb_bytes = out_buf.getvalue()
        LAST_CACHED_IMG_HASH = raw_hash
        LAST_CACHED_THUMB_BYTES = thumb_bytes
        return thumb_bytes
    except Exception:
        return raw_bytes

def grab_direct_screen_thumbnail(hd: bool = False) -> Optional[bytes]:
    """採用 Windows GDI BitBlt 直接抓取當前桌面真實原生畫面 (保底極速引擎)"""
    try:
        import ctypes
        from PIL import Image
        import io
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

        out_buf = io.BytesIO()
        screenshot.save(out_buf, format="JPEG", quality=90)
        return out_buf.getvalue()
    except Exception:
        return None

async def api_last_vision_image(request):
    """返回 7L 最後一眼看到的畫面圖片 (支援 hd=1 原生 4K/超高清原圖)"""
    is_hd = request.query.get("hd") in ("1", "true") or request.query.get("raw") in ("1", "true")
    img_bytes = None
    if GET_LAST_VISION_IMAGE_CALLBACK:
        try:
            img_data = GET_LAST_VISION_IMAGE_CALLBACK()
            if img_data:
                if isinstance(img_data, str):
                    img_bytes = base64.b64decode(img_data)
                elif isinstance(img_data, bytes):
                    img_bytes = img_data
        except Exception:
            pass

    # 若尚未有主程式截圖，嘗試 GDI 實時抓取目前桌面
    if not img_bytes:
        img_bytes = grab_direct_screen_thumbnail(hd=is_hd)

    # 檢查抓到的截圖是否全黑 (例如在無桌面 session 或鎖屏下)，如果是則讀取真實歷史畫面
    is_solid_black = False
    if img_bytes:
        try:
            from PIL import Image
            import io
            test_im = Image.open(io.BytesIO(img_bytes))
            extrema = test_im.getextrema()
            if extrema == ((0, 0), (0, 0), (0, 0)):
                is_solid_black = True
        except Exception:
            pass

    if not img_bytes or is_solid_black:
        # 從 data/last_vision_frame.jpg 載入真實感知畫面快取
        frame_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "last_vision_frame.jpg")
        if os.path.exists(frame_path):
            try:
                with open(frame_path, "rb") as f:
                    img_bytes = f.read()
            except Exception:
                pass

    if img_bytes:
        # 若老爸請求 HD/原圖（如燈箱放大檢視），直接回傳 100% 原生無損超高解析度
        if is_hd:
            resp_bytes = img_bytes
        else:
            resp_bytes = get_optimized_thumbnail_bytes(img_bytes, target_w=720)

        return web.Response(
            body=resp_bytes,
            content_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    return web.Response(status=404, text="No vision image available")

async def telemetry_broadcast_worker():
    """定期向前端推送全系統即時遙測 (每 0.8 秒一次，流暢且節省客戶端 CPU/GPU)"""
    while True:
        try:
            if CONNECTED_CLIENTS:
                data = await get_full_telemetry()
                msg = json.dumps({
                    "type": "telemetry",
                    "timestamp": time.time(),
                    "data": data
                }, ensure_ascii=False)
                for ws in list(CONNECTED_CLIENTS):
                    if not ws.closed:
                        asyncio.create_task(_safe_send(ws, msg))
            await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1.0)

async def start_web_dashboard(
    port: int = 7860,
    input_queue: Optional[asyncio.Queue] = None,
    vts: Any = None,
    get_system_state_cb = None,
    set_mic_cb = None,
    set_sleep_cb = None,
    trigger_expression_cb = None,
    get_memory_cb = None,
    get_mind_board_cb = None,
    get_last_vision_image_cb = None,
    restart_cb = None,
    shutdown_cb = None,
    execute_tool_cb = None,
    get_tools_cb = None,
    get_switches_cb = None,
    set_switch_cb = None,
    punish_cb = None,
    reward_cb = None
):
    """啟動 aiohttp 網頁伺服器"""
    global INPUT_QUEUE, VTS_CLIENT, GET_SYSTEM_STATE_CALLBACK, SET_MIC_CALLBACK, SET_SLEEP_CALLBACK, TRIGGER_EXPRESSION_CALLBACK, GET_RECENT_MEMORY_CALLBACK, GET_MIND_BOARD_CALLBACK, GET_LAST_VISION_IMAGE_CALLBACK, RESTART_CALLBACK, SHUTDOWN_CALLBACK, EXECUTE_TOOL_CALLBACK, GET_TOOLS_CALLBACK, GET_SWITCHES_CALLBACK, SET_SWITCH_CALLBACK, PUNISH_CALLBACK, REWARD_CALLBACK
    INPUT_QUEUE = input_queue
    VTS_CLIENT = vts
    GET_SYSTEM_STATE_CALLBACK = get_system_state_cb
    SET_MIC_CALLBACK = set_mic_cb
    SET_SLEEP_CALLBACK = set_sleep_cb
    TRIGGER_EXPRESSION_CALLBACK = trigger_expression_cb
    GET_RECENT_MEMORY_CALLBACK = get_memory_cb
    GET_MIND_BOARD_CALLBACK = get_mind_board_cb
    GET_LAST_VISION_IMAGE_CALLBACK = get_last_vision_image_cb
    RESTART_CALLBACK = restart_cb
    SHUTDOWN_CALLBACK = shutdown_cb
    EXECUTE_TOOL_CALLBACK = execute_tool_cb
    GET_TOOLS_CALLBACK = get_tools_cb
    GET_SWITCHES_CALLBACK = get_switches_cb
    SET_SWITCH_CALLBACK = set_switch_cb
    PUNISH_CALLBACK = punish_cb
    REWARD_CALLBACK = reward_cb
    
    global APPROVE_YT_COMPANION_CALLBACK, REJECT_YT_COMPANION_CALLBACK
    import services.yt_companion_service as yt_comp
    if hasattr(yt_comp, 'approve_pending_video'):
        APPROVE_YT_COMPANION_CALLBACK = yt_comp.approve_pending_video
    if hasattr(yt_comp, 'reject_pending_video'):
        REJECT_YT_COMPANION_CALLBACK = yt_comp.reject_pending_video

    app = web.Application()
    
    # 靜態資源目錄 (web/)
    web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    os.makedirs(web_dir, exist_ok=True)
    
    # 路由設置
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/switches", api_get_switches)
    app.router.add_post("/api/switches/toggle", api_toggle_switch)
    app.router.add_get("/api/memory", api_get_memory)
    app.router.add_get("/api/memory/all", api_get_memory_all)
    app.router.add_post("/api/memory/update", api_update_memory)
    app.router.add_post("/api/memory/delete", api_delete_memory)
    app.router.add_post("/api/memory/add", api_add_memory)
    app.router.add_post("/api/memory/clean_duplicates", api_clean_duplicate_memories)
    app.router.add_post("/api/memory/clear", api_clear_all_memories)
    app.router.add_get("/api/memory/capacity", api_get_memory_capacity)
    app.router.add_post("/api/memory/capacity", api_set_memory_capacity)
    app.router.add_get("/api/last_vision_image", api_last_vision_image)
    app.router.add_post("/api/send_message", api_send_message)
    app.router.add_post("/api/interject", api_interject)
    app.router.add_get("/api/chat_sources", api_chat_sources)
    app.router.add_post("/api/toggle_mic", api_toggle_mic)
    app.router.add_post("/api/set_sleep", api_set_sleep)
    app.router.add_post("/api/trigger_expression", api_trigger_expression)
    app.router.add_post("/api/action/punish", api_punish_action)
    app.router.add_post("/api/action/reward", api_reward_action)
    app.router.add_get("/api/prompts", api_get_prompts)
    app.router.add_post("/api/prompts", api_save_prompts)
    app.router.add_post("/api/prompts/reset", api_reset_prompts)
    app.router.add_get("/api/tools", api_get_tools)
    app.router.add_get("/api/tools/history", api_get_tool_history)
    app.router.add_post("/api/tools/execute", api_execute_tool)
    app.router.add_post("/api/tools/clear_history", api_clear_tool_history)
    app.router.add_get("/api/settings", api_get_settings)
    app.router.add_post("/api/settings", api_save_settings)
    app.router.add_get("/api/settings/backup", api_download_env_backup)
    app.router.add_post("/api/restart", api_restart)
    app.router.add_post("/api/shutdown", api_shutdown)
    app.router.add_post("/api/yt_companion/approve", api_yt_companion_approve)
    app.router.add_post("/api/yt_companion/reject", api_yt_companion_reject)

    async def index(request):
        index_file = os.path.join(web_dir, "index.html")
        if os.path.exists(index_file):
            return web.FileResponse(index_file)
        return web.Response(text="<h1>7L Web Dashboard Loading...</h1>", content_type="text/html")

    app.router.add_get("/", index)
    app.router.add_static("/static/", path=web_dir, name="static")

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()

    bind_port = port
    # 🛡️ 安全預設只綁本機回環：控制台有重啟/關機/執行工具/清空記憶等危險端點，
    #    綁 0.0.0.0 會讓同網段任何人操作。需要開放給其他機器時設 WEB_BIND_HOST=0.0.0.0。
    BIND_HOST = (os.getenv("WEB_BIND_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    global MAIN_EVENT_LOOP
    try:
        MAIN_EVENT_LOOP = asyncio.get_running_loop()
    except Exception:
        pass

    for attempt in range(3):
        try:
            site = web.TCPSite(runner, BIND_HOST, bind_port)
            await site.start()
            print(f"\n🌐 [7L Web 後台] 已成功在 http://127.0.0.1:{bind_port} 啟動！")
            print(f"👉 本機瀏覽器請開啟：http://localhost:{bind_port}\n")
            asyncio.create_task(telemetry_broadcast_worker())
            return
        except OSError as e:
            if getattr(e, 'errno', None) in (10048, 48, 98) or "10048" in str(e):
                if attempt < 2:
                    print(f"⚠️ [7L Web 後台] 連接埠 {bind_port} 正在釋放中，正在重試 ({attempt+1}/3)...")
                    await asyncio.sleep(1.2)
                    continue
                else:
                    # 自動切換備援連接埠 7861
                    bind_port = port + 1
                    try:
                        site = web.TCPSite(runner, BIND_HOST, bind_port)
                        await site.start()
                        print(f"\n🌐 [7L Web 後台] 連接埠 {port} 佔用，已自動切換至備援連接埠 http://127.0.0.1:{bind_port} 啟動！")
                        print(f"👉 本機瀏覽器請開啟：http://localhost:{bind_port}\n")
                        asyncio.create_task(telemetry_broadcast_worker())
                        return
                    except Exception:
                        pass
            print(f"⚠️ [7L Web 後台] 啟動失敗: {e}")
            return
        except Exception as e:
            print(f"⚠️ [7L Web 後台] 啟動失敗: {e}")
            return
