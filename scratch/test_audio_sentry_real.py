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

import core.websocket_patch
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import asyncio
import numpy as np
import io
import re
import wave
from core.llm_engine import GEMINI_KEYS
from google import genai
from google.genai import types

async def test():
    wav_path = r"C:\Users\qiwai\scratch\test_dad_16k.wav"
    with wave.open(wav_path, "rb") as wf:
        raw_pcm = wf.readframes(wf.getnframes())
    print(f"Loaded {wav_path}: {len(raw_pcm)} bytes PCM", flush=True)
    
    live_cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(parts=[types.Part(text="""妳是 7L 的背景潛意識語音與發言決策神經（Live Audio Sentry）。
妳正在即時聆聽老爸從麥克風說出的真實語音音訊。

【任務規範】：
1. 【精確聽音辨字】：直接從音訊中聽出老爸真正說的台詞（校正錯字，如「謝龍/西L」校正為「7L」）。
2. 【決策判斷】：
   - 若老爸在跟妳說話/調侃/吐槽/問話/點歌 ➔ [SPEAK: target=老爸, focus=焦點]
   - 若老爸在跟直播觀眾互動/喝咖啡 ➔ [SPEAK: target=老爸(因應觀眾留言吐槽/搭腔), focus=吐槽老爸喝咖啡]
   - 若自言自語/雜音 ➔ [SILENCE]

輸出格式：
HEARD: <老爸真正說的話>
DECISION: [SPEAK: target=..., focus=...] 或 [SILENCE]""")])
    )
    
    model = "gemini-3.8-live"
    for idx, key in enumerate(GEMINI_KEYS[1:8]):
        print(f"\nTrying key #{idx+1} ({key[:8]}...)...", flush=True)
        client = genai.Client(api_key=key)
        try:
            async with client.aio.live.connect(model=model, config=live_cfg) as session:
                print("Connected! Sending PCM audio...", flush=True)
                chunk_sz = 8000
                for offset in range(0, len(raw_pcm), chunk_sz):
                    chunk = raw_pcm[offset:offset+chunk_sz]
                    await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))
                    
                await session.send_realtime_input(text="（老爸說完話了，請輸出 HEARD 與 DECISION）")
                print("Waiting for response...", flush=True)
                
                output_trans = ""
                async for resp in session.receive():
                    sc = resp.server_content
                    if sc:
                        if sc.output_transcription and sc.output_transcription.text:
                            output_trans += sc.output_transcription.text
                            print(f"[Live] {sc.output_transcription.text}", flush=True)
                        if sc.turn_complete or getattr(sc, 'generation_complete', False):
                            print("Turn complete!", flush=True)
                            break
                            
                print(f"\n🚨 [Sentry Decision Output]:\n{output_trans.strip()}", flush=True)
                return
        except Exception as e:
            print(f"Key #{idx+1} failed: {e}", flush=True)
            continue

if __name__ == "__main__":
    asyncio.run(test())
