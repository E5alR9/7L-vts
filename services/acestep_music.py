# -*- coding: utf-8 -*-
"""
🎵 ACE-Step AI 作曲腿（PROVIDER: LOCAL-ACE-Step；見 docs/AI_SOURCES.md）

定位：文字→完整歌曲（含人聲＋編曲）的 AI 作曲服務，與 MIDI 樂隊互補：
  MIDI 樂隊＝精準器樂演奏（GM 音色，立即響應）
  ACE-Step＝AI 生成完整歌曲（含唱＋混音，後台慢任務）

    ACESTEP_ENABLED=0      預設關；設 1 啟用（需另裝 ACE-Step 1.5 服務，8GB 可跑 2B turbo）
    ACESTEP_URL=http://127.0.0.1:7865
    ACESTEP_GEN_PATH=/api/v1/generate   # 依實際服務 schema 可配，免改碼
    ACESTEP_OUT_DIR=songs_ai            # 生成成品目錄

服務未裝／未啟 → 所有呼叫安全跳過（回 ok=False），不擋主流程。
"""
import os
import time

import httpx

from core.utils import log_print

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       os.getenv("ACESTEP_OUT_DIR") or "songs_ai")
os.makedirs(OUT_DIR, exist_ok=True)


def _cfg():
    return {
        "enabled": (os.getenv("ACESTEP_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes"),
        "url": (os.getenv("ACESTEP_URL") or "http://127.0.0.1:7865").rstrip("/"),
        "gen_path": (os.getenv("ACESTEP_GEN_PATH") or "/api/v1/generate").strip() or "/api/v1/generate",
        "timeout": float(os.getenv("ACESTEP_TIMEOUT") or "600"),
    }


def is_enabled() -> bool:
    return _cfg()["enabled"]


def build_request(caption: str, lyrics: str = "", duration: int = 120, style: str = "") -> dict:
    """純函式：組生成請求（可測；不打網路）。"""
    cap = (caption or "").strip()
    if style and style not in cap:
        cap = f"{cap}, {style}".strip(", ")
    return {
        "caption": cap or "溫柔抒情流行歌",
        "lyrics": (lyrics or "").strip() or "[Instrumental]",
        "duration": max(10, min(600, int(duration or 120))),
    }


async def generate_song(caption: str, lyrics: str = "", duration: int = 120, style: str = "") -> dict:
    """送件生成（慢任務；服務未啟回 ok=False）。成功回 {ok, file}。"""
    c = _cfg()
    if not c["enabled"]:
        return {"ok": False, "error": "ACE-Step 未啟用（ACESTEP_ENABLED=1＋另裝服務）"}
    payload = build_request(caption, lyrics, duration, style)
    try:
        async with httpx.AsyncClient(timeout=c["timeout"]) as cli:
            r = await cli.post(f"{c['url']}{c['gen_path']}", json=payload)
            if r.status_code != 200:
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:120]}"}
            data = r.json() if "json" in (r.headers.get("content-type") or "") else {}
            audio_url = data.get("audio_url") or data.get("file") or data.get("url") or ""
            fname = f"acestep_{int(time.time())}.mp3"
            fpath = os.path.join(OUT_DIR, fname)
            if audio_url:
                if audio_url.startswith("http"):
                    dl = await cli.get(audio_url, timeout=120)
                    if dl.status_code == 200:
                        with open(fpath, "wb") as f:
                            f.write(dl.content)
                        return {"ok": True, "file": fpath}
                else:
                    return {"ok": True, "file": audio_url}
            return {"ok": True, "file": "", "raw": str(data)[:200]}
    except Exception as e:
        log_print(f"⚠️ [ACE-Step] 生成失敗（已跳過）: {str(e)[:100]}")
        return {"ok": False, "error": str(e)[:150]}


def status() -> dict:
    c = _cfg()
    alive = False
    if c["enabled"]:
        try:
            import httpx as _hx
            r = _hx.get(c["url"], timeout=5.0)
            alive = r.status_code < 500
        except Exception:
            pass
    return {"enabled": c["enabled"], "alive": alive, "url": c["url"], "at": time.time()}
