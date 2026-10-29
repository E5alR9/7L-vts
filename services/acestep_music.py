# -*- coding: utf-8 -*-
"""
🎵 ACE-Step AI 作曲腿（PROVIDER: LOCAL-ACE-Step 1.5；見 docs/AI_SOURCES.md）

定位：文字→完整歌曲（含人聲＋編曲）的 AI 作曲服務，與 MIDI 樂隊互補：
  MIDI 樂隊＝精準器樂演奏（GM 音色，立即響應）
  ACE-Step＝AI 生成完整歌曲（含唱＋混音，後台慢任務）

服務：ACE-Step 1.5 官方 REST API（裝在 ~/ACE-Step-1.5，用 scripts/start_acestep.bat 開）。
  POST /release_task 送件 → POST /query_result 輪詢（status 0 跑／1 好／2 失敗）→ GET /v1/audio 下載。
  埠用 7865（官方預設 8001 跟 VTube Studio 撞）。
沒開服務 → 所有呼叫安全跳過（回 ok=False），不擋主流程；不用在 .env 設開關，服務有回應就算啟用。
（2026-10-29 以前照猜的 schema 打 /api/v1/generate，服務從沒裝過，所以一直沒用過）
"""
import json
import os
import time
from urllib.parse import quote

import httpx

from core.utils import log_print
from core.paths import ROOT_DIR

ACESTEP_URL = "http://127.0.0.1:7865"
ACESTEP_MODEL = "acestep-v15-turbo"   # 8 步、最快；12GB 顯卡要跟 7L 搶，大模型跑不動
ACESTEP_TIMEOUT = 600.0               # 生一首歌最多等幾秒
ACESTEP_POLL_SEC = 2.0
OUT_DIR = os.path.join(ROOT_DIR, "songs_ai")


def _alive(timeout: float = 3.0) -> bool:
    try:
        return httpx.get(f"{ACESTEP_URL}/health", timeout=timeout).status_code == 200
    except Exception:
        return False


def is_enabled() -> bool:
    return _alive()


def _vocal_language(lyrics: str) -> str:
    t = lyrics or ""
    if any("぀" <= ch <= "ヿ" for ch in t):
        return "ja"
    if any("一" <= ch <= "鿿" for ch in t):
        return "zh"
    return "en"


def build_request(caption: str, lyrics: str = "", duration: int = 120, style: str = "") -> dict:
    """純函式：組 /release_task 請求（可測；不打網路）。"""
    cap = (caption or "").strip()
    if style and style not in cap:
        cap = f"{cap}, {style}".strip(", ")
    lyr = (lyrics or "").strip() or "[Instrumental]"
    return {
        "prompt": cap or "溫柔抒情流行歌",
        "lyrics": lyr,
        "audio_duration": max(10, min(600, int(duration or 120))),
        "model": ACESTEP_MODEL,
        "vocal_language": _vocal_language(lyr),
        "batch_size": 1,
        "audio_format": "mp3",
    }


def parse_result(item: dict) -> tuple:
    """純函式：/query_result 的一筆 → (status, 音檔 file 欄位或錯誤字)。result 是 JSON 字串（也可能是一串）。"""
    st = int(item.get("status", 0) or 0)
    res = item.get("result")
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except Exception:
            res = {}
    if isinstance(res, list):
        res = res[0] if res else {}
    res = res or {}
    if st == 2:
        return 2, str(res.get("error") or item.get("error") or "生成失敗")[:150]
    return st, res.get("file") or ""


async def generate_song(caption: str, lyrics: str = "", duration: int = 120, style: str = "") -> dict:
    """送件、等它生完、下載到 songs_ai/（慢任務；服務沒開回 ok=False）。成功回 {ok, file}。"""
    payload = build_request(caption, lyrics, duration, style)
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            try:
                r = await cli.post(f"{ACESTEP_URL}/release_task", json=payload)
            except httpx.ConnectError:
                return {"ok": False, "error": "ACE-Step 服務沒開（scripts/start_acestep.bat）"}
            if r.status_code != 200:
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:120]}"}
            task_id = ((r.json() or {}).get("data") or {}).get("task_id")
            if not task_id:
                return {"ok": False, "error": f"送件沒拿到 task_id：{r.text[:120]}"}
            log_print(f"🎵 [ACE-Step] 開始作曲（{payload['audio_duration']} 秒）：{payload['prompt'][:40]}")
            t0 = time.time()
            while time.time() - t0 < ACESTEP_TIMEOUT:
                await _sleep(ACESTEP_POLL_SEC)
                q = await cli.post(f"{ACESTEP_URL}/query_result", json={"task_id_list": [task_id]})
                items = (q.json() or {}).get("data") or []
                if not items:
                    continue
                st, val = parse_result(items[0])
                if st == 0:
                    continue
                if st == 2:
                    return {"ok": False, "error": val}
                if not val:
                    return {"ok": False, "error": "生成完成但沒有音檔"}
                url = val if val.startswith("http") else f"{ACESTEP_URL}{val}" if val.startswith("/") \
                    else f"{ACESTEP_URL}/v1/audio?path={quote(val)}"
                dl = await cli.get(url, timeout=120)
                if dl.status_code != 200:
                    return {"ok": False, "error": f"下載音檔 HTTP {dl.status_code}"}
                os.makedirs(OUT_DIR, exist_ok=True)
                fpath = os.path.join(OUT_DIR, f"acestep_{int(time.time())}.mp3")
                with open(fpath, "wb") as f:
                    f.write(dl.content)
                log_print(f"🎵 [ACE-Step] 作曲完成（{time.time() - t0:.0f} 秒）：{fpath}")
                return {"ok": True, "file": fpath}
            return {"ok": False, "error": f"超過 {ACESTEP_TIMEOUT:.0f} 秒沒生完"}
    except Exception as e:
        log_print(f"⚠️ [ACE-Step] 生成失敗（已跳過）: {str(e)[:100]}")
        return {"ok": False, "error": str(e)[:150]}


async def _sleep(sec: float):
    import asyncio
    await asyncio.sleep(sec)


def status() -> dict:
    return {"enabled": True, "alive": _alive(), "url": ACESTEP_URL, "at": time.time()}
