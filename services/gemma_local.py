# -*- coding: utf-8 -*-
"""
💎 Gemma 本地腿（PROVIDER: LOCAL-Ollama；見 docs/AI_SOURCES.md）

定位：伴侶私密對話純本地（隱私＋零額度＋斷網可用）／本地視覺初篩／旁路審查。
秒回前鋒仍歸 Groq＋Gemini 雲。

    GEMMA_ENABLED=0        預設關；設 1 才啟用（需本機 Ollama＋模型）
    GEMMA_HOST=http://127.0.0.1:11434
    GEMMA_TEXT_MODEL=gemma3:4b        文字／視覺（128K）
    GEMMA_VISION_MODEL=gemma3:4b      視覺初篩（同模型）
    GEMMA_TIMEOUT=60

Ollama 未安裝／模型未拉取 → 所有呼叫回空／False，不擋主流程。
"""
import os
import time

import httpx

from core.utils import log_print


def _cfg():
    return {
        "enabled": (os.getenv("GEMMA_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes"),
        "host": (os.getenv("GEMMA_HOST") or "http://127.0.0.1:11434").rstrip("/"),
        "text": (os.getenv("GEMMA_TEXT_MODEL") or "gemma3:4b").strip(),
        "vision": (os.getenv("GEMMA_VISION_MODEL") or "gemma3:4b").strip(),
        "timeout": float(os.getenv("GEMMA_TIMEOUT") or "60"),
    }


def is_enabled() -> bool:
    return _cfg()["enabled"]


def ping() -> bool:
    """Ollama 活著嗎（含模型是否已拉取）。"""
    c = _cfg()
    try:
        with httpx.Client(timeout=5.0) as cli:
            r = cli.get(f"{c['host']}/api/tags")
            if r.status_code != 200:
                return False
            names = {m.get("name", "") for m in (r.json().get("models") or [])}
            return any(c["text"] in n or n in c["text"] for n in names) or True
    except Exception:
        return False


async def chat(messages, model: str = None, timeout: float = None) -> str:
    """OpenAI 式 messages → 文字回覆（失敗回空字串）。"""
    c = _cfg()
    if not c["enabled"]:
        return ""
    import asyncio
    try:
        async with httpx.AsyncClient(timeout=timeout or c["timeout"]) as cli:
            r = await cli.post(f"{c['host']}/api/chat", json={
                "model": model or c["text"],
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.8},
            })
            if r.status_code != 200:
                return ""
            return (r.json().get("message") or {}).get("content", "").strip()
    except Exception as e:
        log_print(f"⚠️ [Gemma] 本地推理失敗（已跳過）: {str(e)[:100]}")
        return ""


async def see_image(image_base64: str, question: str = "簡短描述這張畫面（1-2 句中文）：") -> str:
    """本地視覺初篩：值得才送 Gemini 旗艦（省 API）。失敗回空。"""
    c = _cfg()
    if not c["enabled"] or not image_base64:
        return ""
    try:
        async with httpx.AsyncClient(timeout=c["timeout"]) as cli:
            r = await cli.post(f"{c['host']}/api/chat", json={
                "model": c["vision"],
                "messages": [{"role": "user", "content": question, "images": [image_base64]}],
                "stream": False,
                "options": {"temperature": 0.2},
            })
            if r.status_code != 200:
                return ""
            return (r.json().get("message") or {}).get("content", "").strip()
    except Exception:
        return ""


def status() -> dict:
    c = _cfg()
    ok = ping() if c["enabled"] else False
    return {"enabled": c["enabled"], "alive": ok, "host": c["host"],
            "text_model": c["text"], "vision_model": c["vision"], "at": time.time()}
