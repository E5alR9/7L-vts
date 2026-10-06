import os
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
raw_key = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEYS") or os.getenv("GEMINI_KEY") or ""
api_key = raw_key.split(",")[0].strip() if "," in raw_key else raw_key.strip()

async def test():
    client = genai.Client(api_key=api_key)
    live_cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO], 
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(parts=[types.Part.from_text(text="測試")])
    )
    
    try:
        async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
            print("Connected!")
    except Exception as e:
        print(f"FAILED: {repr(e)}")
        import traceback
        traceback.print_exc()

asyncio.run(test())
