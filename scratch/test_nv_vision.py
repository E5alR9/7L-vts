import asyncio
import base64
import os
import re
import time
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv("c:/Users/qiwai/.env")
KEYS = [k for k in re.split(r"[\s,;]+", os.getenv("NV_API_KEYS") or os.getenv("NV_API_KEY") or "") if k.startswith("nvapi-")]
BASE = "https://integrate.api.nvidia.com/v1"

async def test_nv_vision():
    # 產生純紅圖片
    print("Generating dummy red image...")
    img = Image.new('RGB', (100, 100), color='red')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_bytes = img_byte_arr.getvalue()
    b64_str = base64.b64encode(img_bytes).decode('utf-8')
    
    client = AsyncOpenAI(api_key=KEYS[0], base_url=BASE, max_retries=0)
    
    models = ["meta/llama-3.2-11b-vision-instruct"]
    for m in models:
        print(f"\nTesting {m}...")
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(client.chat.completions.create(
                model=m,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "這是一張什麼顏色的圖片？"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_str}"}}
                    ]
                }],
                max_tokens=100
            ), 45)
            dt = time.monotonic() - t0
            print(f"✅ {dt:.1f}s | {r.choices[0].message.content.strip()}")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_nv_vision())
