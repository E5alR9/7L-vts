import asyncio
import os
import sys
import pyaudio
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load keys
load_dotenv('C:\\Users\\qiwai\\.env')
sys.path.append('C:\\Users\\qiwai')
try:
    from core.llm_engine import GEMINI_KEYS
except Exception:
    GEMINI_KEYS = []

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 8000

async def test_live_mic():
    if not GEMINI_KEYS:
        print("No API keys found.")
        return

    client = genai.Client(api_key=GEMINI_KEYS[0])
    model = "gemini-3.8-live"

    live_cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        )
    )

    print(f"Connecting to {model}...")
    try:
        async with client.aio.live.connect(model=model, config=live_cfg) as session:
            print("✅ Connected! Please speak into your microphone...")
            
            p = pyaudio.PyAudio()
            stream = p.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            input=True,
                            frames_per_buffer=CHUNK)
                            
            print("🎙️ Recording started... (Press Ctrl+C to stop)")
            
            async def send_audio():
                try:
                    while True:
                        data = stream.read(CHUNK, exception_on_overflow=False)
                        await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
                        await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Send audio error: {e}")
                    
            async def receive_response():
                try:
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            if c.output_transcription and c.output_transcription.text:
                                print(f"📝 7L (Transcript): {c.output_transcription.text}")
                            if c.model_turn:
                                print(f"🗣️ 7L (Model Audio/Text response received)")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Receive error: {e}")

            send_task = asyncio.create_task(send_audio())
            recv_task = asyncio.create_task(receive_response())
            
            # Wait for 15 seconds to let the user test
            await asyncio.sleep(15)
            
            print("Stopping recording...")
            send_task.cancel()
            recv_task.cancel()
            stream.stop_stream()
            stream.close()
            p.terminate()
            
    except Exception as e:
        print(f"❌ Connection failed: {type(e).__name__} - {e}")

if __name__ == "__main__":
    try:
        asyncio.run(test_live_mic())
    except KeyboardInterrupt:
        print("\nExiting...")
