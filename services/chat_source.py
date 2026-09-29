# -*- coding: utf-8 -*-
"""
📺 直播聊天共用基建（Twitch / YouTube）
=====================================
概念移植自 LiveCore（chat-source.ts / chat-runtime.ts），純 Python、零新依賴：

1. parse_chat_source_url()  — 任意貼上網址 → 標準描述子（provider/mode/channel/video_id）
2. make_chat_item()         — 統一訊息格式（message_id / actor / avatar / sent_at），
                             text 欄位與舊軌道2格式完全相容（【Twitch/YouTube 直播觀眾 …】：）
3. DedupTracker             — 訊息 ID 去重（上限 256，LiveCore 同值），防重連/重 poll 重複餵話
4. backoff_delay()          — 指數退避 5→10→20→40→60s 上限（取代固定 5 秒硬重連）
5. Worker 註冊表            — register/bind/start/stop/status，給 Web 控制台開關＋重啟用。
                             放這裡（而非 vts_7L_test）是為了避開循環 import：
                             web_dashboard 只依賴 services.*，vts 主程式只管註冊。
"""
import asyncio
import collections
import re
import time
from urllib.parse import urlparse, parse_qs

from core.utils import log_print

# ── 常數（對齊 LiveCore） ──────────────────────────────────────────────
TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
RESERVED_TWITCH_SEGMENTS = {
    "directory", "downloads", "jobs", "login", "messages", "p", "search",
    "settings", "signup", "store", "subscriptions", "turbo", "videos", "wallet",
}
DEDUP_MAXSIZE = 256


def _host_ok(hostname, supported):
    hostname = (hostname or "").lower()
    return any(hostname == h or hostname.endswith("." + h) for h in supported)


def parse_chat_source_url(url):
    """純函式：任意網址 → 描述子 dict。

    成功例：{"provider": "twitch", "mode": "channel", "channel": "xxx", ...}
            {"provider": "youtube", "mode": "video", "video_id": "xxx", ...}
            {"provider": "youtube", "mode": "channel", "channel": "@xxx", ...}
    失敗：{"provider": None, ..., "error": "原因"}（絕不丟例外）
    """
    out = {"provider": None, "mode": None, "channel": "",
           "video_id": "", "normalized_url": "", "display_label": "", "error": ""}
    try:
        raw = (url or "").strip()
        if not raw:
            out["error"] = "網址為空"
            return out
        if "://" not in raw:
            raw = "https://" + raw
        u = urlparse(raw)
        host = (u.hostname or "").lower()
        segs = [s for s in (u.path or "").split("/") if s]
        qs = parse_qs(u.query or "")

        if _host_ok(host, TWITCH_HOSTS):
            if not segs or segs[0].lower() in RESERVED_TWITCH_SEGMENTS:
                out["error"] = "不是 Twitch 頻道網址"
                return out
            login = re.sub(r"[^a-z0-9_]", "", segs[0].lower())
            if not login:
                out["error"] = "Twitch 頻道名無效"
                return out
            out.update(provider="twitch", mode="channel", channel=login,
                       normalized_url=f"https://www.twitch.tv/{login}",
                       display_label=f"Twitch #{login}")
            return out

        if _host_ok(host, YOUTUBE_HOSTS):
            if host == "youtu.be" or host.endswith(".youtu.be"):
                vid = segs[0] if segs else ""
                if re.fullmatch(r"[A-Za-z0-9_\-]{6,}", vid or ""):
                    out.update(provider="youtube", mode="video", video_id=vid,
                               normalized_url=f"https://www.youtube.com/watch?v={vid}",
                               display_label=f"YouTube 影片 {vid}")
                    return out
                out["error"] = "youtu.be 短網址無效"
                return out
            v = (qs.get("v") or [""])[0]
            if v and re.fullmatch(r"[A-Za-z0-9_\-]{6,}", v):
                out.update(provider="youtube", mode="video", video_id=v,
                           normalized_url=f"https://www.youtube.com/watch?v={v}",
                           display_label=f"YouTube 影片 {v}")
                return out
            if len(segs) >= 2 and segs[0] == "live" and re.fullmatch(r"[A-Za-z0-9_\-]{6,}", segs[1]):
                vid = segs[1]
                out.update(provider="youtube", mode="video", video_id=vid,
                           normalized_url=f"https://www.youtube.com/watch?v={vid}",
                           display_label=f"YouTube 影片 {vid}")
                return out
            if segs and segs[0].startswith("@"):
                handle = segs[0].split("?")[0]
                out.update(provider="youtube", mode="channel", channel=handle,
                           normalized_url=f"https://www.youtube.com/{handle}/live",
                           display_label=f"YouTube {handle}")
                return out
            if len(segs) >= 2 and segs[0] == "channel" and re.fullmatch(r"UC[A-Za-z0-9_\-]{20,}", segs[1]):
                ch = f"channel/{segs[1]}"
                out.update(provider="youtube", mode="channel", channel=ch,
                           normalized_url=f"https://www.youtube.com/{ch}/live",
                           display_label=f"YouTube {ch}")
                return out
            if len(segs) >= 2 and segs[0] in ("c", "user") and segs[1]:
                ch = f"{segs[0]}/{segs[1]}"
                out.update(provider="youtube", mode="channel", channel=ch,
                           normalized_url=f"https://www.youtube.com/{ch}/live",
                           display_label=f"YouTube {ch}")
                return out
            out["error"] = "不是可識別的 YouTube 影片/頻道網址"
            return out

        out["error"] = "不支援的網址（只吃 twitch.tv / youtube.com）"
        return out
    except Exception as e:
        out["error"] = f"解析失敗：{e}"
        return out


def make_chat_item(provider, channel="", message_id="", user="", display="",
                   message="", avatar="", actor_id="", actor_login=""):
    """統一訊息格式。text 與舊軌道2格式完全相容（主程式正則照抓），其餘欄位給控制台/日誌用。"""
    who = display or user
    if provider == "twitch":
        who_txt = f"{display} (@{user})" if display and user and display.lower() != user.lower() else (display or user)
        text = f"【Twitch 直播觀眾 {who_txt}】：{message}"
    else:
        text = f"【YouTube 直播觀眾 {who}】：{message}"
    return {
        "text": text,
        "audio_base64": None,
        "timestamp": time.time(),
        "source": provider,
        "channel": channel,
        "message_id": message_id or "",
        "user": user,
        "display": display,
        "avatar": avatar or "",
        "actor_id": actor_id or "",
        "actor_login": actor_login or "",
        "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
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
