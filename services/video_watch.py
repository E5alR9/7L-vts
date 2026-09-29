# -*- coding: utf-8 -*-
"""
📺 觀眾點播看全片（Video Watch）：點播隊列＋後台消化＋筆記播報
PROVIDER: LOCAL（yt-dlp＋faster-whisper＋opencv）＋GEMINI-VISION（抽幀看圖）＋GROQ（分段摘要）
見 docs/AI_SOURCES.md。

流程：觀眾貼 URL → /api 或工具 request_watch 入隊 → worker 依序消化：
  1. captions 優先（--write-auto-sub，零成本）
  2. 無字幕 → 音軌 faster-whisper 本地轉錄
  3. 抽幀（每 N 秒一幀，Gemini 視覺看圖；長片降採樣）
  4. Groq 分段摘要 → 筆記寫入統一記憶＋心智看板（source="video_watch"）→ 7L 播報

全程非同步，不擋直播。單片上限 VIDEO_WATCH_MAX_MIN（預設 30 分鐘）。
"""
import asyncio
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlparse, parse_qs

from core.utils import log_print

WATCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "watch")
os.makedirs(WATCH_DIR, exist_ok=True)

WATCH_QUEUE: asyncio.Queue = None
WATCH_HISTORY = []


def normalize_video_url(raw: str) -> str:
    """純函式：任意 YT 輸入 → 11 碼 ID（失敗回空字串）。"""
    raw = (raw or "").strip().strip("'\"")
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_\-]{11}", raw):
        return raw
    try:
        if "://" not in raw:
            raw = "https://" + raw
        u = urlparse(raw)
        host = (u.hostname or "").lower()
        if "youtu.be" in host:
            vid = (u.path or "").strip("/").split("/")[0]
            return vid if re.fullmatch(r"[A-Za-z0-9_\-]{11}", vid) else ""
        if "youtube.com" in host:
            v = (parse_qs(u.query or {}).get("v") or [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_\-]{11}", v):
                return v
            m = re.search(r"/(live|shorts|embed)/([A-Za-z0-9_\-]{11})", u.path or "")
            if m:
                return m.group(2)
    except Exception:
        pass
    return ""


def max_minutes() -> int:
    try:
        return max(1, int(os.getenv("VIDEO_WATCH_MAX_MIN") or "30"))
    except Exception:
        return 30


def frame_interval() -> int:
    try:
        return max(5, int(os.getenv("VIDEO_WATCH_FRAME_SEC") or "20"))
    except Exception:
        return 20


async def request_watch(url: str, requester: str = "觀眾") -> dict:
    """工具/API 入口：點播入隊（去重：同片排隊中不重複）。"""
    vid = normalize_video_url(url)
    if not vid:
        return {"ok": False, "error": "不是有效的 YouTube 網址/ID"}
    global WATCH_QUEUE
    if WATCH_QUEUE is None:
        WATCH_QUEUE = asyncio.Queue()
    for q in list(WATCH_QUEUE._queue):
        if isinstance(q, dict) and q.get("video_id") == vid:
            return {"ok": True, "queued": False, "video_id": vid, "message": "該片已在隊列中"}
    await WATCH_QUEUE.put({"video_id": vid, "requester": requester, "at": time.time()})
    try:
        WATCH_HISTORY.append({"video_id": vid, "requester": requester, "at": time.time()})
        del WATCH_HISTORY[:-50]
    except Exception:
        pass
    log_print(f"📺 [點播] {requester} 點播 https://youtu.be/{vid}（隊列＋1）")
    return {"ok": True, "queued": True, "video_id": vid}


def _run(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)


def fetch_captions(video_id: str) -> str:
    """抓字幕（優先人工→自動；零轉錄成本）。"""
    out = os.path.join(WATCH_DIR, video_id)
    cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-sub", "--write-auto-sub",
           "--sub-langs", "zh.*|zho|en.*", "--sub-format", "vtt", "-o", out,
           f"https://www.youtube.com/watch?v={video_id}"]
    _run(cmd, timeout=90)
    texts = []
    try:
        for f in sorted(os.listdir(WATCH_DIR)):
            if f.startswith(video_id) and f.endswith(".vtt"):
                with open(os.path.join(WATCH_DIR, f), "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh.read().splitlines():
                        line = line.strip()
                        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")):
                            continue
                        line = re.sub(r"<[^>]+>", "", line).strip()
                        if line and (not texts or texts[-1] != line):
                            texts.append(line)
                break
    except Exception:
        pass
    return "\n".join(texts)


def fetch_audio(video_id: str):
    """抓音軌（m4a/best audio）。回傳路徑或空字串。"""
    out = os.path.join(WATCH_DIR, video_id)
    cmd = [sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "m4a",
           "--no-playlist", "-o", out, f"https://www.youtube.com/watch?v={video_id}"]
    rc, _ = _run(cmd, timeout=600)
    if rc != 0:
        return ""
    for f in sorted(os.listdir(WATCH_DIR)):
        if f.startswith(video_id) and f.endswith((".m4a", ".mp3", ".opus", ".webm")):
            return os.path.join(WATCH_DIR, f)
    return ""


def extract_frames(video_id: str, video_path: str, every_sec: int = None):
    """等間隔抽幀 → [jpg 路徑]（長片自動降採樣；失敗回空）。"""
    every_sec = every_sec or frame_interval()
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur = total / fps if fps else 0
        if dur > max_minutes() * 60:
            every_sec = max(every_sec, int(dur / 90))  # 再長也只看 ~90 幀
        step = max(1, int(fps * every_sec))
        paths, idx, n = [], 0, 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                p = os.path.join(WATCH_DIR, f"{video_id}_f{n:03d}.jpg")
                cv2.imwrite(p, frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                paths.append(p)
                n += 1
                if n >= 120:
                    break
            idx += 1
        cap.release()
        return paths
    except Exception:
        return []


async def digest_video(video_id: str, requester: str) -> dict:
    """消化單片：字幕→音軌轉錄→抽幀看圖→Groq 摘要→記憶＋看板。回報摘要。"""
    from services import rag_store as _rag  # noqa (digest 內 lazy，避免循環)
    log_print(f"📺 [消化] 開始看片 https://youtu.be/{video_id}（{requester} 點播）")
    text = await asyncio.to_thread(fetch_captions, video_id)
    src_note = "字幕"
    if len(text.strip()) < 100:
        audio = await asyncio.to_thread(fetch_audio, video_id)
        if audio:
            try:
                from services.stt import _transcribe_faster
                text = await asyncio.to_thread(_transcribe_faster, open(audio, "rb").read())
                src_note = "音軌轉錄"
            except Exception:
                pass
    frames_desc = ""
    vpath = ""
    for f in sorted(os.listdir(WATCH_DIR)):
        if f.startswith(video_id) and f.endswith((".mp4", ".webm", ".mkv")):
            vpath = os.path.join(WATCH_DIR, f)
            break
    if not vpath:
        out = os.path.join(WATCH_DIR, video_id)
        rc, _ = _run([sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=480]+ba/b[height<=480]/b",
                      "--no-playlist", "-o", out, f"https://www.youtube.com/watch?v={video_id}"], timeout=900)
        if rc == 0:
            for f in sorted(os.listdir(WATCH_DIR)):
                if f.startswith(video_id) and f.endswith((".mp4", ".webm", ".mkv")):
                    vpath = os.path.join(WATCH_DIR, f)
                    break
    if vpath:
        frames = await asyncio.to_thread(extract_frames, video_id, vpath)
        if frames:
            try:
                import base64
                from vts_7L_test import get_lightweight_gemini_vision  # lazy：主程式才有
                descs = []
                for fp in frames[::max(1, len(frames) // 12)][:12]:
                    with open(fp, "rb") as fh:
                        b64 = base64.b64encode(fh.read()).decode()
                    d = await get_lightweight_gemini_vision(b64)
                    if d:
                        descs.append(d)
                frames_desc = "\n".join(f"【畫面{i+1}】{d}" for i, d in enumerate(descs))
            except Exception:
                pass
    material = (text[:12000] + ("\n\n【關鍵畫面】\n" + frames_desc[:3000] if frames_desc else "")).strip()
    if not material:
        return {"ok": False, "error": "抓不到字幕/音軌/畫面（可能地區限制或需登入）"}
    try:
        summary = await _rag.fold_summary([material], max_chars=900)
    except Exception:
        summary = material[:900]
    note = f"📺 看完《https://youtu.be/{video_id}》（{requester} 點播，來源：{src_note}）：{summary or material[:400]}"
    try:
        from vts_7L_test import add_to_streamer_mind_board  # lazy
        add_to_streamer_mind_board(f"{requester} 點播的片", f"video:{video_id}", note, "video_watch")
    except Exception:
        pass
    log_print(f"📺 [看完] {video_id}：{(summary or '')[:80]}")
    return {"ok": True, "video_id": video_id, "summary": summary or material[:400]}


async def video_watch_worker():
    """背景消化協程（啟動時掛一個；隊列空時待命）。"""
    global WATCH_QUEUE
    if WATCH_QUEUE is None:
        WATCH_QUEUE = asyncio.Queue()
    log_print("📺 [點播台] 看片消化 worker 就緒")
    while True:
        try:
            job = await WATCH_QUEUE.get()
            try:
                await digest_video(job["video_id"], job.get("requester", "觀眾"))
            except Exception as e:
                log_print(f"⚠️ [點播消化異常]: {e}")
            finally:
                WATCH_QUEUE.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)
