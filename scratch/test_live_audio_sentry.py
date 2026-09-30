import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.websocket_patch
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import asyncio
import numpy as np
import io
import re
import edge_tts
from pydub import AudioSegment
from core.llm_engine import GEMINI_KEYS
from google import genai
from google.genai import types

API_KEY = GEMINI_KEYS[0] if GEMINI_KEYS else ""

async def gen_test_audio(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, "zh-TW-YunJheNeural")
    mp3_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_data += chunk["data"]
            
    # Convert MP3 to 16kHz mono PCM
    seg = AudioSegment.from_file(io.BytesIO(mp3_data), format="mp3")
    seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    return seg.raw_data

async def test():
    test_phrase = "7L，這咖啡怎麼這麼苦啊？妳看觀眾都在笑我。"
    print(f"Generating test speech: 「{test_phrase}」...")
    pcm_bytes = await gen_test_audio(test_phrase)
    print(f"Generated {len(pcm_bytes)} bytes of 16kHz PCM audio.")
    
    print(f"Connecting to gemini-3.8-live with key {API_KEY[:6]}...")
    client = genai.Client(api_key=API_KEY)
    
    live_cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(parts=[types.Part(text="""妳是 7L 的背景潛意識語音與發言決策神經（Live Audio Sentry）。
妳正在即時聆聽老爸從麥克風說出的真實語音音訊。

妳的任務：
1. 【精確聽取】：直接從老爸的真實發音與語調聽出老爸真正說的每一句話（徹底修正任何語音轉文字的同音錯字，如「謝龍/西L/CL」應為「7L」，「Evade」等）。
2. 【決策判斷】：
   - 若老爸是在跟妳（7L）說話、下指令、問話、調侃吐槽、聊天、或點歌 ➔ 請判定應開口！
     輸出：[HEARD: 老爸真正說的話] [SPEAK: target=目標, focus=焦點, song=歌名(若點歌)]
     （目標常見：老爸、老爸(因應觀眾留言吐槽/搭腔) 等；焦點例如：吐槽老爸喝咖啡、討論遊戲操作 等）
   - 若老爸只是單純無意義清喉嚨、背景雜音、或專注自言自語且無需妳搭理 ➔ 保持安靜！
     輸出：[HEARD: 聽到的內容(若有)] [SILENCE]

輸出格式必須嚴格遵循：
[HEARD: ...] [SPEAK: target=..., focus=...] 或 [HEARD: ...] [SILENCE]
嚴禁輸出任何多餘廢話！""")])
    )
    
    model = "gemini-3.8-live"
    async with client.aio.live.connect(model=model, config=live_cfg) as session:
        print("Connected to Live session! Sending audio...")
        # Send audio in chunks of 1600 samples (100ms)
        chunk_size = 3200 # 1600 samples * 2 bytes
        for i in range(0, len(pcm_bytes), chunk_size):
            chunk = pcm_bytes[i:i+chunk_size]
            await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))
            await asyncio.sleep(0.02)
            
        await session.send_realtime_input(text="（老爸說完話了，請給出 [HEARD: ...] 與 [SPEAK: ...] 或 [SILENCE]）")
        print("Waiting for sentry decision...")
        
        input_text = ""
        output_text = ""
        async for resp in session.receive():
            sc = resp.server_content
            if sc:
                if sc.input_transcription and sc.input_transcription.text:
                    input_text += sc.input_transcription.text
                if sc.output_transcription and sc.output_transcription.text:
                    output_text += sc.output_transcription.text
                if sc.turn_complete or getattr(sc, 'generation_complete', False):
                    break
                    
        print(f"\n🎧 [3.8 Live 接收到語音輸入辨識]: {input_text.strip()}")
        print(f"🚨 [3.8 Live 哨兵決策輸出]: {output_text.strip()}")

if __name__ == "__main__":
    asyncio.run(test())
