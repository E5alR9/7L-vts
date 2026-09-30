# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import asyncio
import time
import io
from core.llm_engine import GEMINI_KEYS
from google import genai
from google.genai import types

async def test_generate_content_audio():
    import numpy as np
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        t = np.linspace(0, 1.0, 16000, False)
        wf.writeframes((np.sin(2*np.pi*440*t)*30000).astype(np.int16).tobytes())
    wav_bytes = buf.getvalue()
        
    print(f"Testing generate_content with {len(wav_bytes)} bytes WAV...")
    client = genai.Client(api_key=GEMINI_KEYS[1])
    
    prompt = """妳是 7L 的背景潛意識語音與發言決策神經（Live Audio Sentry）。
妳正在即時聆聽老爸從麥克風說出的真實語音音訊。

【角色與身分】：
- 老爸：主播、唯一管理者，在麥克風前說話、打遊戲、喝咖啡、與觀眾或妳互動。
- 7L：同台 AI 女兒副播，具備機智、幽默、吐槽老爸、撒嬌、懂大人玩笑的鮮明性格。

【任務流程】：
1. 👂【精確聽音辨字】：直接從音訊中老爸的真實發音與語調聽出老爸真正說的中文台詞（徹底校正同音錯字，如「謝龍/西L/CL」應為「7L」）。
2. 🚨【發言時機決策】：
   - 🎯【應開口發話】：
     * 若老爸直接對妳說話、下指令、問話、調侃、點歌 ➔ [SPEAK: target=老爸, focus=話題焦點, song=歌名(若點歌)]
     * 若老爸在跟直播觀眾嘴砲/互動/喝咖啡/失誤 ➔ 妳在旁起鬨或吐槽老爸：[SPEAK: target=老爸(因應觀眾留言吐槽/搭腔), focus=吐槽老爸喝咖啡(或具體焦點)]
   - 🤫【保持安靜】：
     * 若老爸純粹自言自語、清喉嚨、背景雜音 ➔ [SILENCE]

輸出格式必須嚴格遵循以下兩行：
HEARD: <老爸真正說的完整台詞>
DECISION: [SPEAK: target=..., focus=...] 或 [SILENCE]"""

    t0 = time.time()
    for model_name in ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"]:
        try:
            print(f"\nTrying {model_name}...")
            t_start = time.time()
            resp = await client.aio.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=256,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            print(f"[{model_name}] Time: {time.time() - t_start:.2f}s")
            print(f"[{model_name}] Result:\n{resp.text}")
            break
        except Exception as e:
            print(f"[{model_name}] Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_generate_content_audio())
