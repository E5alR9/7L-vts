# -*- coding: utf-8 -*-
"""
📺 Twitch 直播聊天室監聽（IRC over WebSocket · 匿名 justinfan · 零金鑰）

把觀眾留言包成 input_queue 項目（source="twitch"），與 TikTok 同一條軌道
進 STREAMER_MIND_BOARD 批量消化（控 API 成本）。

設定 .env：
    TWITCH_CHANNELS=頻道名1,頻道名2     # 不設則本 worker 直接不啟動
"""
import asyncio
import os
import re
import time

from core.utils import log_print

_IRWS = "wss://irc-ws.chat.twitch.tv:443"
_TAG_RE = re.compile(r"^@(?P<tags>[^\s]+)\s+")
_PRIVMSG_RE = re.compile(r"^:(?P<user>[^!]+)![^ ]* PRIVMSG\s+(?P<chan>#[^\s]+)\s+:(?P<msg>.*)$")


def parse_irc_line(line: str):
    """純函式：Twitch IRC 一行 → dict（可單測）

    PING          → {"ping": True}
    PRIVMSG(有tags)→ {"user","display","channel","message"}
    其他/無效      → None
    """
    if not line:
        return None
    if line.startswith("PING"):
        return {"ping": True}

    tags = {}
    rest = line
    m = _TAG_RE.match(line)
    if m:
        for kv in m.group("tags").split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                tags[k] = v
        rest = line[m.end():]

    m2 = _PRIVMSG_RE.match(rest)
    if not m2:
        return None
    user = m2.group("user")
    display = tags.get("display-name") or user
    return {
        "user": user,
        "display": display,
        "channel": m2.group("chan").lstrip("#"),
        "message": m2.group("msg").strip(),
        "badges": tags.get("badges", ""),
        "id": tags.get("id", "") or "",
    }


def parse_channels(raw: str) -> list:
    """'A, b ;C' → ['a', 'b', 'c']（去 #、小寫、去空白）"""
    return [c.strip().lower().lstrip("#") for c in re.split(r"[,\s;]+", raw or "") if c.strip()]


def build_queue_item(user: str, display: str, message: str, message_id: str = "") -> dict:
    """組成與 TikTok 相容的格式：【Twitch 直播觀眾 顯示名 (@id)】：內容
    （主程式軌道2 的正則靠這個格式抓出暱稱與 ID；text 格式凍結不可改）"""
    who = f"{display} (@{user})" if display and display.lower() != user.lower() else user
    return {
        "text": f"【Twitch 直播觀眾 {who}】：{message}",
        "audio_base64": None,
        "timestamp": time.time(),
        "source": "twitch",
        "message_id": message_id or "",
        "user": user,
        "display": display,
    }


async def twitch_live_worker(input_queue):
    """背景協程：連 Twitch IRC、轉發留言（去重＋指數退避重連＋狀態回報）"""
    from services import chat_source as cs
    channels = parse_channels(os.getenv("TWITCH_CHANNELS") or "")
    if not channels:
        log_print("ℹ️ [Twitch] 未設定 TWITCH_CHANNELS，聊天室監聽未啟動")
        cs.report_chat_status("twitch", "disabled", "未設定 TWITCH_CHANNELS")
        return

    nick = f"justinfan{int(time.time()) % 90000 + 10000}"
    import websockets

    dedup = cs.DedupTracker()
    attempt = 0
    targets = ",".join("#" + c for c in channels)
    cs.report_chat_status("twitch", "connecting", targets)
    while True:
        try:
            async with websockets.connect(_IRWS, max_size=2 ** 20, open_timeout=15, ping_interval=30) as ws:
                await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                await ws.send("PASS SCHMOOPIIE")      # 匿名連線慣例
                await ws.send(f"NICK {nick}")
                await ws.send("JOIN " + ",".join(f"#{c}" for c in channels))
                log_print(f"📺 [Twitch] 已連線並加入：{targets}（匿名 {nick}）")
                cs.report_chat_status("twitch", "live", targets)
                attempt = 0

                async for raw in ws:
                    for line in str(raw).split("\r\n"):
                        msg = parse_irc_line(line)
                        if not msg:
                            continue
                        if msg.get("ping"):
                            await ws.send("PONG :tmi.twitch.tv")
                            continue
                        if "message" not in msg or not msg["message"]:
                            continue
                        if dedup.seen(msg.get("id", "")):
                            continue                    # 重連/重送的舊留言，直接丟
                        await input_queue.put(build_queue_item(
                            msg["user"], msg["display"], msg["message"],
                            message_id=msg.get("id", "")))
                        try:
                            import services.web_dashboard as wd
                            wd.broadcast_event("twitch_comment", {
                                "user": msg["display"], "text": msg["message"],
                                "message_id": msg.get("id", ""),
                                "channel": msg.get("channel", ""),
                            })
                        except Exception:
                            pass
            # 連線被對端關閉（沒丟例外）：照退避重連
            attempt += 1
            delay = cs.backoff_delay(attempt)
            log_print(f"⚠️ [Twitch] 連線被關閉，{delay:.0f} 秒後重連")
            cs.report_chat_status("twitch", "connecting", f"斷線重連中（{delay:.0f}s）")
            await asyncio.sleep(delay)
        except Exception as e:
            attempt += 1
            delay = cs.backoff_delay(attempt)
            log_print(f"⚠️ [Twitch] 連線中斷：{type(e).__name__}: {e}，{delay:.0f} 秒後重連")
            cs.report_chat_status("twitch", "error", f"{type(e).__name__}: {e}")
            await asyncio.sleep(delay)
