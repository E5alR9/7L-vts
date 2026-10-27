import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv('c:\\Users\\qiwai\\.env', override=True)

async def main():
    api_key_str = os.getenv("NV_API_KEYS", "").strip('"').strip("'")
    if not api_key_str:
        api_key_str = os.getenv("NV_API_KEY", "").strip('"').strip("'")
        
    api_key = api_key_str.split('\n')[0].strip()
    
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Just say Test Successful"}
        ],
        "temperature": 0.0,
        "max_tokens": 100
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            print(f"Status: {resp.status}")
            print(f"Response: {text}")

if __name__ == '__main__':
    asyncio.run(main())
