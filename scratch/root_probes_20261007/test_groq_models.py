import os
import asyncio
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

groq_keys_str = os.getenv("GROQ_API_KEYS", "")
if not groq_keys_str:
    print("找不到 GROQ_API_KEYS")
    exit(1)
    
keys = [k for k in groq_keys_str.replace(",", " ").split() if k.strip()]
client = AsyncGroq(api_key=keys[0])

MODELS_TO_TEST = [
    'qwen/qwen3.8-27b',
    'allam-2-7b',
    'canopylabs/orpheus-arabic-saudi',
    'canopylabs/orpheus-v1-english',
    'openai/gpt-oss-120b',
    'openai/gpt-oss-20b',
]

async def test_models():
    print(f"🔑 使用 Groq 金鑰測試 (前綴): {keys[0][:8]}...")
    print("-" * 50)
    for model in MODELS_TO_TEST:
        print(f"⏳ 測試模型: {model} ...", end=" ", flush=True)
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10
            )
            print(f"✅ 成功! (回應: {resp.choices[0].message.content.strip()})")
        except Exception as e:
            err = str(e).replace('\n', ' ')
            print(f"❌ 失敗: {err}")

if __name__ == "__main__":
    asyncio.run(test_models())
