import os
import sys
import io
import re
import asyncio
from dotenv import load_dotenv
from google import genai

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def make_request(client, i):
    print(f"[{i}] 發送請求...")
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.5-flash-lite",
            contents="hello, write a 100 word essay."
        )
        print(f"✅ [{i}] 成功! ")
    except Exception as e:
        print(f"❌ [{i}] 失敗: {str(e)[:150]}")

async def main():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path, override=True)
    
    raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    gemini_keys_list = [k.strip() for k in re.split(r'[\s,;]+', raw_keys) if k.strip() and len(k.strip()) < 150]
    
    if not gemini_keys_list:
        print("沒有找到金鑰")
        return
        
    print(f"找到 {len(gemini_keys_list)} 把金鑰。我們同時用前 5 把金鑰發送 10 個請求看看會不會 429...")
    
    tasks = []
    # 模擬主程式同時啟動多個協程 (vision, mind, audio, etc)
    for i in range(20):
        # 循環使用前 5 把金鑰
        key = gemini_keys_list[i % 5]
        client = genai.Client(api_key=key)
        tasks.append(make_request(client, i))
        
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
