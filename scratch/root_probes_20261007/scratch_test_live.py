import asyncio
from google import genai
from google.genai import types
import os
import re

# Safely extract an API key from the workspace
API_KEY = None
try:
    with open('c:/Users/qiwai/vts_7L_test.py', 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r'GEMINI_KEYS\s*=\s*\[\"([^\"]+)\"', content)
        if match:
            API_KEY = match.group(1)
except Exception:
    pass

if not API_KEY:
    API_KEY = os.getenv('GEMINI_API_KEY')

if not API_KEY:
    print("No API Key found!")
    exit(1)

client = genai.Client(api_key=API_KEY)

async def test_live():
    model_name = 'gemini-3.5-flash-lite'
    print(f'Testing WebSocket connection with model: {model_name}')
    try:
        async with client.aio.live.connect(model=model_name) as session:
            print('✅ SUCCESS! Connection established.')
            await session.send_realtime_input(text='Hello!')
            async for resp in session.receive():
                print('Received response!')
                break
    except Exception as e:
        print(f'❌ FAILED: {e}')
        
asyncio.run(test_live())
