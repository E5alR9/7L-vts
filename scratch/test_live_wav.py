import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.websocket_patch
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import asyncio
import numpy as np
import io
import wave
from core.llm_engine import GEMINI_KEYS
from google import genai
from google.genai import types

API_KEY = GEMINI_KEYS[0] if GEMINI_KEYS else ""

def create_test_wav_bytes():
    # Create 1.5s 16kHz sine wave audio as WAV
    sample_rate = 16000
    duration = 1.5
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_data = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).tobytes()
    
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)
    return buf.getvalue()

async def test():
    wav_path = r"C:\Users\qiwai\scratch\test_dad_16k.wav"
    with wave.open(wav_path, "rb") as wf:
        raw_pcm = wf.readframes(wf.getnframes())
    print(f"Loaded {wav_path}: {len(raw_pcm)} bytes PCM")
    
    client = genai.Client(api_key=API_KEY)
    live_cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(parts=[types.Part(text="妳是 7L 潛意識哨兵。若音訊是純雜音或無意義嗶聲，請回傳 [SILENCE]。")])
    )
    
    async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
        print("Connected! Sending audio as audio/pcm;rate=16000...")
        await session.send_realtime_input(audio=types.Blob(data=raw_pcm, mime_type="audio/pcm;rate=16000"))
        await session.send_realtime_input(text="（請判定音訊內容與決策）")
        
        async for resp in session.receive():
            sc = resp.server_content
            if sc:
                if sc.output_transcription and sc.output_transcription.text:
                    print(f"Output: {sc.output_transcription.text}")
                if sc.turn_complete or getattr(sc, 'generation_complete', False):
                    print("Turn complete!")
                    break

if __name__ == "__main__":
    asyncio.run(test())
