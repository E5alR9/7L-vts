# -*- coding: utf-8 -*-
"""
📺 直播聊天共用基建（Twitch / YouTube）
=====================================
概念移植自 LiveCore（chat-source.ts / chat-runtime.ts），純 Python、零新依賴：

2. make_chat_item()         — TikTok／Twitch／YouTube 丟進 input_queue 的統一格式（viewer／content／platform_uid）
3. DedupTracker             — 訊息 ID 去重（上限 256，LiveCore 同值），防重連/重 poll 重複餵話
4. backoff_delay()          — 指數退避 5→10→20→40→60s 上限（取代固定 5 秒硬重連）
5. Worker 註冊表            — register/bind/start/stop/status，給 Web 控制台開關＋重啟用。
                             放這裡（而非 vts_7L_test）是為了避開循環 import：
                             web_dashboard 只依賴 services.*，vts 主程式只管註冊。
"""
import asyncio
import collections
import time

from core.utils import log_print

# ── 常數（對齊 LiveCore） ──────────────────────────────────────────────
DEDUP_MAXSIZE = 256


PLATFORM_LABEL = {"tiktok": "TikTok", "twitch": "Twitch", "youtube": "YouTube"}


def make_chat_item(source, viewer="", content="", *, platform_uid="", text="", user="", message_id=""):
    """直播間輸入丟進 input_queue 的統一格式（TikTok／Twitch／YouTube 三個監聽器共用；以前各自拼 dict，TikTok 拼了九處）。
    主程式只讀 viewer／content／platform_uid／source（core/input_sources.parse_input_item）；
    text 給日誌和後台看，沒給就照「【平台 直播觀眾 名字】：內容」拼。
    platform_uid 是平台唯一帳號（觀眾改不到），認老爸只信這個，顯示名稱可以亂取。"""
    if not text:
        label = PLATFORM_LABEL.get(source.split("_")[0], source)
        tail = " 留言" if source == "tiktok" else ""
        text = f"【{label} 直播觀眾 {viewer}{tail}】：{content}"
    return {
        "text": text,
        "viewer": viewer or "",
        "content": content or "",
        "platform_uid": platform_uid or "",
        "user": user or viewer or "",
        "message_id": message_id or "",
        "audio_base64": None,
        "timestamp": time.time(),
        "source": source,
    }


class DedupTracker:
    """訊息 ID 去重（上限 256，滿了丟最舊）。空 id 永遠回 False（不擋）。"""

    def __init__(self, maxsize=DEDUP_MAXSIZE):
        self._seen = collections.OrderedDict()
        self._max = max(1, int(maxsize))

    def seen(self, message_id):
        """True = 重複（要丟掉）；False = 首見（已登記）。"""
        if not message_id:
            return False
        if message_id in self._seen:
            self._seen.move_to_end(message_id)
            return True
        self._seen[message_id] = True
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return False

    def __len__(self):
        return len(self._seen)


def backoff_delay(attempt, base=5.0, cap=60.0):
    """指數退避：5→10→20→40→60（上限），attempt 從 0 起算。"""
    try:
        return min(float(cap), float(base) * (2 ** max(0, int(attempt))))
    except Exception:
        return float(cap)


# ── Worker 註冊表（給 Web 控制台開關/重啟；狀態統一回報） ──────────────
WORKER_FACTORIES = {}
WORKER_TASKS = {}
WORKER_STATUS = {}
_INPUT_QUEUE = None


def _set_status(name, state, detail=""):
    WORKER_STATUS[name] = {"state": state, "detail": detail, "updated_at": time.time()}


def report_chat_status(provider, state, detail=""):
    """listener 回報用：寫狀態表＋log＋廣播（broadcast 失敗吞掉，不影響主流程）。"""
    _set_status(provider, state, detail)
    if state in ("live", "error", "disabled"):
        try:
            log_print(f"📺 [{provider}] 狀態→{state}" + (f"：{detail}" if detail else ""))
        except Exception:
            pass
    try:
        from services.web_dashboard import broadcast_event
        broadcast_event("chat_source_status",
                        {"provider": provider, "state": state, "detail": detail})
    except Exception:
        pass


def bind_chat_workers(input_queue):
    global _INPUT_QUEUE
    _INPUT_QUEUE = input_queue


def register_chat_worker(name, func):
    WORKER_FACTORIES[name] = func
    if name not in WORKER_STATUS:
        _set_status(name, "waiting", "待啟動")


def _configured_target(name):
    import os
    if name == "twitch":
        return os.getenv("TWITCH_CHANNELS") or ""
    if name == "youtube":
        return os.getenv("YOUTUBE_CHANNEL") or os.getenv("YOUTUBE_LIVE_ID") or ""
    return ""


def chat_workers_status():
    out = []
    for name in ("twitch", "youtube"):
        st = WORKER_STATUS.get(name, {"state": "waiting", "detail": ""})
        task = WORKER_TASKS.get(name)
        out.append({
            "name": name,
            "state": st.get("state", "waiting"),
            "detail": st.get("detail", ""),
            "alive": bool(task and not task.done()),
            "target": _configured_target(name),
            "updated_at": st.get("updated_at", 0),
        })
    return out


async def _supervised(name, func, queue):
    _set_status(name, "waiting", "啟動中")
    try:
        await func(queue)
    except asyncio.CancelledError:
        _set_status(name, "stopped", "已手動停止")
        raise
    except Exception as e:
        _set_status(name, "error", f"{type(e).__name__}: {e}")
    else:
        st = WORKER_STATUS.get(name, {})
        if st.get("state") not in ("stopped",):
            _set_status(name, "stopped", "worker 已結束（可能未設定頻道）")


def start_chat_worker(name):
    """啟動（先停舊的再起新的）。回 dict 給 API 直接轉發。"""
    if name not in WORKER_FACTORIES:
        return {"ok": False, "error": f"未知 worker：{name}"}
    if _INPUT_QUEUE is None:
        return {"ok": False, "error": "主程式尚未就緒（input_queue 未綁定）"}
    old = WORKER_TASKS.pop(name, None)
    try:
        if old and not old.done():
            old.cancel()
    except Exception:
        pass
    WORKER_TASKS[name] = asyncio.create_task(_supervised(name, WORKER_FACTORIES[name], _INPUT_QUEUE))
    return {"ok": True, "state": "starting"}


def stop_chat_worker(name):
    if name not in WORKER_FACTORIES:
        return {"ok": False, "error": f"未知 worker：{name}"}
    task = WORKER_TASKS.pop(name, None)
    try:
        if task and not task.done():
            task.cancel()
    except Exception:
        pass
    _set_status(name, "stopped", "已手動停止")
    return {"ok": True, "state": "stopped"}
