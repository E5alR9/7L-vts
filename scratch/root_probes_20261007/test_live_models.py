import asyncio
import os
import sys
from google import genai
from google.genai import types

from dotenv import load_dotenv
load_dotenv('C:\\Users\\qiwai\\.env')
sys.path.append('C:\\Users\\qiwai')
try:
    from core.llm_engine import GEMINI_KEYS
except Exception:
    GEMINI_KEYS = []

async def test_models():
    if not GEMINI_KEYS:
        print("No API keys.")
        return
        
    client = genai.Client(api_key=GEMINI_KEYS[0])
    
    models_to_test = [
        "gemini-3.8-flash",
        "gemini-3.8-live",
        "gemini-3.8-flash-live",
        "gemini-3.8-pro-live",
        "gemini-3.8-live-extended-thinking",
        "gemini-3.5-flash",
        "gemini-3.5-transcribe",
        "gemini-3-flash-live"
    ]
    
    print("Testing Live API connection for various models...")
    for m in models_to_test:
        print(f"\nTrying {m}...")
        try:
            async with asyncio.timeout(3.0):
                async with client.aio.live.connect(model=m) as session:
                    print(f"[SUCCESS] Connected to {m} successfully!")
        except Exception as e:
            print(f"[FAIL] {m}: {type(e).__name__} - {e}")

if __name__ == "__main__":
    asyncio.run(test_models())
