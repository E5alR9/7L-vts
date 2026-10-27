import os, sys
from dotenv import load_dotenv
load_dotenv('C:\\Users\\qiwai\\.env')
sys.path.append('C:\\Users\\qiwai')
from core.llm_engine import GEMINI_KEYS
import httpx

if GEMINI_KEYS:
    key = GEMINI_KEYS[0]
    res = httpx.get(f'https://generativelanguage.googleapis.com/v1beta/models?key={key}')
    if res.status_code == 200:
        models = res.json().get('models', [])
        print("=== ALL LIVE OR EXPERIMENTAL MODELS ===")
        for m in models:
            name = m['name']
            if 'live' in name.lower() or 'audio' in name.lower() or 'exp' in name.lower() or '3.' in name.lower() or '2.5' in name.lower():
                print(name)
    else:
        print("API Error:", res.text)
else:
    print("No GEMINI_KEYS found even after load_dotenv.")
