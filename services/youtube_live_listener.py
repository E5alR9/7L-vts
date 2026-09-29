# -*- coding: utf-8 -*-
"""
📺 YouTube Live 聊天室監聽（InnerTube get_live_chat 輪詢 · 免 API 金鑰）

流程：抓 live_chat 頁面拿 continuation → 輪詢 get_live_chat → 解析留言 →
     input_queue（source="youtube"），與 TikTok/Twitch 同一條觀眾軌道。

設定 .env：
    YOUTUBE_LIVE_ID=watch?v= 後面那串 ID（直接貼完整網址也行）
⚠️ 非官方端點：YouTube 改版可能失效，失效時本 worker 持續重試並記錄，
   不會影響主程式。
"""
import asyncio
import json
import os
import re
import time

import httpx

from core.utils import log_print

_API = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?prettyPrint=false"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_CLIENT = {"clientName": "WEB", "clientVersion": "2.20260101.01.00", "hl": "zh-TW", "gl": "TW"}

_CONT_PATTERNS = [
    r'"liveChatRenderer":\{"continuation":"([^"]+)"',
    r'"continuation"\s*:\s*"([A-Za-z0-9_%\-\.]{12,})"',
]


def normalize_video_id(raw: str) -> str:
    """接受完整網址（v= / youtu.be/ / live/）或裸 ID。頻道輸入請用 resolve_live_video_id。"""
    raw = (raw or "").strip().strip("'\"")
    if not raw:
        return ""
    # 頻道（@handle / UC id / 網址）不是直播 ID → 交給頻道解析
    if raw.startswith("@") or re.fullmatch(r"UC[A-Za-z0-9_\-]{20,}", raw) \
            or re.search(r"youtube\.com/@|youtube\.com/channel/|youtube\.com/(c|user)/", raw):
        return ""
    m = re.search(r"(?:v=|youtu\.be/|live/)([A-Za-z0-9_\-]{6,})", raw)
    return m.group(1) if m else raw


def normalize_channel(raw: str) -> str:
    """頻道輸入正規化 → 用於 https://www.youtube.com/{channel}/live 的路徑部分
    支援：@handle / UC id / 完整網址。非頻道輸入回 ''。"""
    raw = (raw or "").strip().strip("'\"")
    if not raw:
        return ""
    if raw.startswith("@"):
        return raw.split("/")[0].rstrip("/")
    m = re.search(r"youtube\.com/(@[^/?#]+|channel/UC[A-Za-z0-9_\-]+|(?:c|user)/[^/?#]+)", raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"UC[A-Za-z0-9_\-]{20,}", raw):
        return f"channel/{raw}"
    return ""


def extract_live_from_html(html: str):
    """純函式：{channel}/live 頁 → (video_id, is_live, title, ok)
    video_id 取 canonical（頻道當前直播或最近預告）；
    is_live 以 ytInitialPlayerResponse.videoDetails.isLiveContent 判定；
    解析失敗時 video_id 回 None、ok 回 False（呼叫端重試）。"""
    if not html:
        return None, False, "", False
    canon = re.findall(r'rel="canonical" href="[^"]*[?&]v=([A-Za-z0-9_\-]{6,})', html)
    video_id = canon[0] if canon else None
    raw = cut_balanced_json(html, "ytInitialPlayerResponse")
    if not raw or not video_id:
        return video_id, False, "", False
    try:
        pr = json.loads(raw)
    except Exception:
        return video_id, False, "", True        # 有 ID 但狀態解析失敗 → 讓呼叫端用聊天端點二次確認
    vd = pr.get("videoDetails") or {}
    ok = (pr.get("playabilityStatus") or {}).get("status") == "OK"
    is_live = bool(vd.get("isLiveContent")) and ok
    return video_id, is_live, str(vd.get("title") or "")[:80], True


def cut_balanced_json(html: str, marker: str):
    """括號配對切出 marker 後的第一個完整 JSON（防 ytInitialPlayerResponse 內嵌 '};'）"""
    i = html.find(marker)
    if i < 0:
        return None
    j = html.find("{", i)
    if j < 0:
        return None
    depth, instr, esc = 0, False, False
    for k in range(j, len(html)):
        c = html[k]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return html[j:k + 1]
    return None


def extract_continuation(html: str):
    """從 live_chat 頁面 HTML/JSON 抓第一個 continuation token"""
    for p in _CONT_PATTERNS:
        m = re.search(p, html or "")
        if m:
            return m.group(1)
    return None


def _find_simple(obj, key):
    """深度搜尋 {key: {"simpleText": ...}}（authorName 等），回傳字串或 None"""
    if isinstance(obj, dict):
        if key in obj:
            v = obj[key]
            if isinstance(v, dict) and "simpleText" in v:
                return v["simpleText"]
            if isinstance(v, str):
                return v
        for v in obj.values():
            r = _find_simple(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_simple(v, key)
            if r:
                return r
    return None


def parse_live_chat_response(data):
    """純函式：InnerTube get_live_chat 回應 → (messages, next_continuation, wait_seconds)

    messages = [{"user": 顯示名, "message": 內容}, ...]
    相容兩種形狀：有包 continuationContents 或直接 liveChatContinuation。
    """
    data = data or {}
    lc = (data.get("continuationContents", {}) or {}).get("liveChatContinuation") \
        or data.get("liveChatContinuation") or data

    messages = []
    for act in (lc.get("actions") or []):
        renderer = None
        text_action = act.get("addLiveChatTextAction")
        if isinstance(text_action, dict):
            item = text_action.get("item") or text_action
            renderer = item.get("liveChatTextActionRenderer")
        if not renderer:
            continue                                   # 送禮/徽章/入場等其他 action 忽略
        runs = (renderer.get("message") or {}).get("runs") or []
        text = "".join(str(r.get("text", "")) for r in runs).strip()
        if not text:
            continue
        author = _find_simple(renderer, "authorName") or "觀眾"
        msg_id = str(renderer.get("id") or "")
        thumbs = ((renderer.get("authorPhoto") or {}).get("thumbnails") or [])
        avatar = str((thumbs[-1] or {}).get("url", "")) if thumbs else ""
        try:
            sent_at = float(int(renderer.get("timestampUsec"))) / 1e6 if renderer.get("timestampUsec") else time.time()
        except Exception:
            sent_at = time.time()
        messages.append({"user": author, "message": text, "id": msg_id,
                         "avatar": avatar, "sent_at": sent_at})

    cont = lc.get("continuation")
    if not cont:                                  # 下一代 token 藏在 continuations 陣列裡
        for c in (lc.get("continuations") or []):
            icd = (c or {}).get("invalidationContinuationData") \
                or (c or {}).get("timedContinuationData") \
                or (c or {}).get("liveChatReplayContinuationData") or {}
            if icd.get("continuation"):
                cont = icd["continuation"]
                break
    if not cont:                                  # 最後手段：整包深度搜第一個長 token
        for m in re.finditer(r'"continuation":"([A-Za-z0-9_%\-\.]{40,})"', json.dumps(lc)):
            t = m.group(1)
            if t not in ("", None):
                cont = t
                break
    timeout_ms = lc.get("timeoutMs") or 8000
    wait = max(5.0, min(15.0, float(timeout_ms) / 1000.0))   # 官方給幾秒就等幾秒（上下限 5~15s）
    return messages, cont, wait


def build_queue_item(user: str, message: str, message_id: str = "", avatar: str = "") -> dict:
    """與 TikTok/Twitch 相容的格式（軌道2 正則可解析；無 (@id) 時自動用暱稱當 id）
    text 格式凍結不可改；多出 message_id/avatar/user 欄位給控制台顯示用。"""
    return {
        "text": f"【YouTube 直播觀眾 {user}】：{message}",
        "audio_base64": None,
        "timestamp": time.time(),
        "source": "youtube",
        "message_id": message_id or "",
        "user": user,
        "avatar": avatar or "",
    }


async def youtube_live_worker(input_queue):
    """背景協程：頻道模式（YOUTUBE_CHANNEL → 跟進目前直播）優先，否則用直播 ID。
    去重＋指數退避＋狀態回報；頻道離線自動待命（60s 再查），開播自動跟進。

    頻道模式：每 60s 查 {channel}/live 的 canonical + isLiveContent；
              在播 → 輪詢聊天室；不在播 → 記錄狀態待命。
    """
    from services import chat_source as cs
    vid = normalize_video_id(os.getenv("YOUTUBE_LIVE_ID") or "")
    channel = normalize_channel(os.getenv("YOUTUBE_CHANNEL") or "")
    if not vid and not channel:
        log_print("ℹ️ [YouTube] 未設定 YOUTUBE_CHANNEL 或 YOUTUBE_LIVE_ID，聊天室監聽未啟動")
        cs.report_chat_status("youtube", "disabled", "未設定 YOUTUBE_CHANNEL / YOUTUBE_LIVE_ID")
        return

    headers = {"User-Agent": _UA, "Content-Type": "application/json"}
    warned_no_cont = False
    dedup = cs.DedupTracker()
    attempt = 0
    live_reported = False

    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": _UA}) as cli:
        # ── 頻道模式的前置解析：{channel}/live → canonical + isLiveContent ──
        async def resolve_channel():
            try:
                page = await cli.get(f"https://www.youtube.com/{channel}/live")
                return extract_live_from_html(page.text)
            except Exception as e:
                return None, False, "", False

        if channel and not vid:
            while not vid:                            # 離線/解析失敗就待命重查，不直接 return（開播自動跟進）
                video_id, is_live, title, ok = await resolve_channel()
                if not ok or not video_id:
                    log_print(f"⚠️ [YouTube] 頻道 {channel} 解析失敗（YouTube 改版？），60 秒後重試")
                    cs.report_chat_status("youtube", "error", "頻道解析失敗")
                    await asyncio.sleep(60)
                    continue
                if not is_live:
                    log_print(f"📺 [YouTube] 頻道 {channel} 目前沒有直播（最近：{title or video_id}），60 秒後再查")
                    # 暫時不用 input_queue.put：靜默待命，避免每分鐘灌一次「沒直播」
                    cs.report_chat_status("youtube", "waiting", f"未開播（{title or video_id}）")
                    await asyncio.sleep(60)
                    continue
                vid = video_id
                log_print(f"📺 [YouTube] 頻道 {channel} 正在直播：{title or vid}（ID={vid}），開始輪詢聊天室")
            cs.report_chat_status("youtube", "connecting", vid)

        cont = None
        while True:                                   # 外層：取得（或重新取得）continuation
            try:
                if not cont:
                    page = await cli.get(f"https://www.youtube.com/live_chat?v={vid}&is_popout=1")
                    cont = extract_continuation(page.text)
                    if not cont:
                        if not warned_no_cont:
                            log_print(f"⚠️ [YouTube] 取不到 continuation（ID={vid} —— 該影片正在直播嗎？），15 秒後重試")
                            warned_no_cont = True
                        cs.report_chat_status("youtube", "connecting", "等 continuation")
                        await asyncio.sleep(15)
                        continue
                    warned_no_cont = False
                    log_print(f"📺 [YouTube] 已連線 live_chat：{vid}")
                    cs.report_chat_status("youtube", "connecting", vid)

                while True:                           # 內層：輪詢聊天
                    resp = await cli.post(_API, headers=headers,
                                          json={"context": {"client": _CLIENT}, "continuation": cont})
                    if resp.status_code != 200:
                        raise RuntimeError(f"get_live_chat HTTP {resp.status_code}")

                    msgs, next_cont, wait = parse_live_chat_response(resp.json())
                    attempt = 0
                    if msgs and not live_reported:
                        live_reported = True
                        cs.report_chat_status("youtube", "live", vid)
                    for m in msgs:
                        if dedup.seen(m.get("id", "")):
                            continue                # 重 poll 的舊留言，直接丟
                        await input_queue.put(build_queue_item(
                            m["user"], m["message"],
                            message_id=m.get("id", ""), avatar=m.get("avatar", "")))
                        try:
                            import services.web_dashboard as wd
                            wd.broadcast_event("youtube_comment", {
                                "user": m["user"], "text": m["message"],
                                "message_id": m.get("id", ""), "avatar": m.get("avatar", ""),
                            })
                        except Exception:
                            pass

                    if not next_cont:
                        log_print("ℹ️ [YouTube] continuation 結束（直播可能已結束），20 秒後重抓")
                        cs.report_chat_status("youtube", "connecting", "continuation 結束")
                        cont = None
                        await asyncio.sleep(20)
                        break
                    cont = next_cont
                    await asyncio.sleep(wait)
            except Exception as e:
                attempt += 1
                delay = cs.backoff_delay(attempt)
                log_print(f"⚠️ [YouTube] 輪詢異常：{type(e).__name__}: {e}，{delay:.0f} 秒後重試")
                cs.report_chat_status("youtube", "error", f"{type(e).__name__}: {e}")
                cont = None
                await asyncio.sleep(delay)
