# -*- coding: utf-8 -*-
"""REST 大腦（2026-10-26）：沒有 Live 主腦的時候，用一般 API 呼叫讓她講話。

兩種時候會用到：Live 主腦斷線太久；VTuber 模式（不開 Live 主腦，觀眾留言全靠這裡回）。
一次呼叫：純文字先試 Groq（快、不吃 Gemini 額度），不行再輪 Gemini 的 (key, model)。
要給工具、帶聲音或圖片的不走 Groq（Groq 的工具呼叫不可靠，也不收聲音圖片）。
以前這段在主程式抄了三份（看板備援、老爸 REST 路、觀眾 Live 管道），各自輪金鑰、各自處理限流。
"""
import asyncio
import random
from dataclasses import dataclass, field
from typing import List, Optional

from google import genai
from google.genai import types

from core import groq_router, usage
from core.llm_engine import (GEMINI_KEYS, UNRESTRICTED_SAFETY_SETTINGS, key_cooling, report_gemini_key_error,
                             sort_keys_by_load, track_key)
from core.utils import log_print


@dataclass
class RestReply:
    text: str = ""
    calls: list = field(default_factory=list)   # 模型呼叫的工具 [(名稱, 參數)]
    model: str = ""


def gemini_pairs(models, attempts: int, keys=None) -> List[tuple]:
    """(key, model) 輪著試：空閒的 key 先（同負載隨機打散，免得大家擠同一把），
    冷卻中的排最後（全部冷卻時照樣試，不餓死）。"""
    keys = [k for k in (GEMINI_KEYS if keys is None else keys) if k]
    models = [m for m in (models or []) if m]
    if not keys or not models or attempts <= 0:
        return []
    order = keys[:]
    random.shuffle(order)
    order = sort_keys_by_load(order)
    pairs = [(order[i % len(order)], models[i % len(models)]) for i in range(attempts)]
    pairs.sort(key=lambda km: key_cooling(km[0], km[1]))
    return pairs


async def _groq_once(prompt: str, temperature: float, max_tokens: int) -> Optional[RestReply]:
    resp = await groq_router.groq_chat([{"role": "user", "content": prompt}],
                                       temperature=temperature, max_tokens=max_tokens, timeout=4.5)
    if resp and resp.text and not resp.function_calls:
        return RestReply(text=resp.text.strip(), model=f"Groq/{resp.model}")
    return None


async def _gemini_once(key: str, model: str, parts, cfg, timeout: float):
    client = genai.Client(api_key=key)
    with usage.timed(model, default_role="REST") as u:
        async with track_key(key):
            resp = await asyncio.wait_for(client.aio.models.generate_content(
                model=model, contents=[types.Content(role="user", parts=parts)], config=cfg), timeout=timeout)
        u.tokens = getattr(getattr(resp, "usage_metadata", None), "total_token_count", 0) or 0
    return resp


def _reply_from(resp, model: str) -> RestReply:
    calls = [(getattr(fc, "name", ""), dict(getattr(fc, "args", None) or {}))
             for fc in (getattr(resp, "function_calls", None) or [])]
    text = ""
    try:
        for p in resp.candidates[0].content.parts or []:
            if getattr(p, "text", None) and not getattr(p, "thought", False):
                text += p.text
    except Exception:
        text = getattr(resp, "text", "") or ""
    return RestReply(text=text.strip(), calls=calls, model=model)


async def rest_chat(system_text: str, user_text: str, *, models, keys=None, tools=None, audio_wav: bytes = b"",
                    extra_parts=(),
                    temperature: float = 0.8, max_tokens: int = 500, groq_first: bool = True,
                    attempts: int = 6, timeout: float = 6.0, total_timeout: float = 25.0) -> Optional[RestReply]:
    """系統提示詞＋這次的話 → RestReply；Groq 和 Gemini 全部失敗或超過 total_timeout 回 None。
    提示詞照舊併成一則 user 訊息送（看板備援的提示詞是照這個格式調出來的）；extra_parts（圖片）接在後面。"""
    prompt = f"{system_text}\n\n{user_text}" if system_text else user_text
    try:
        async with asyncio.timeout(total_timeout):
            if groq_first and not tools and not audio_wav and not extra_parts:
                try:
                    r = await _groq_once(prompt, temperature, max_tokens)
                    if r:
                        return r
                except Exception as e:
                    log_print(f"⚠️ [REST 大腦] Groq 這次不行，換 Gemini：{str(e)[:80]}")
            parts = [types.Part(text=prompt)]
            if audio_wav:
                parts.append(types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"))
            parts.extend(extra_parts)
            cfg = types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens,
                                              safety_settings=UNRESTRICTED_SAFETY_SETTINGS, tools=tools or None)
            for key, model in gemini_pairs(models, attempts, keys):
                try:
                    r = _reply_from(await _gemini_once(key, model, parts, cfg, timeout), model)
                    if r.text or r.calls:
                        return r
                except Exception as e:
                    report_gemini_key_error(key, e, model)
                    log_print(f"⚠️ [REST 大腦] {model} 這次不行：{type(e).__name__} {str(e)[:60]}")
    except TimeoutError:
        log_print(f"⚠️ [REST 大腦] 超過 {total_timeout:.0f} 秒沒有回覆，這次放棄")
    return None
