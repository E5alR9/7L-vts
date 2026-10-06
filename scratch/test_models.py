import os
import re
import asyncio
from dotenv import load_dotenv
from google import genai

load_dotenv()
keys = [k.strip() for k in re.split(r'[\s,;]+', os.getenv('GEMINI_API_KEYS') or os.getenv('GEMINI_API_KEY') or '') if k.strip()]
if not keys:
    print("No keys found.")
    exit(1)

client = genai.Client(api_key=keys[0])

models_to_test = [
    'gemini-3.5-flash-lite',
    'gemini-3.1-flash-lite',
    'gemini-3.8-flash',
    'gemini-3.7-flash',
    'gemini-3.6-flash',
    'gemini-3.5-flash',
    'gemini-3-flash',
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite'
]

async def test_model(model_name):
    try:
        resp = await client.aio.models.generate_content(
            model=model_name,
            contents="hello",
        )
        print(f"[SUCCESS] {model_name}: 200 OK")
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str or "rate limit" in err_str:
            print(f"[QUOTA] {model_name}: 429 Quota Exceeded (Model is VALID and usable, just out of quota)")
        elif "503" in err_str or "unavailable" in err_str or "overload" in err_str:
            print(f"[503] {model_name}: 503 Server Overload (Wait and retry)")
        elif "404" in err_str or "not found" in err_str or "invalid" in err_str:
            print(f"[404] {model_name}: 404 Not Found (Model does NOT exist or not accessible)")
        else:
            print(f"[ERROR] {model_name}: {e}")

async def main():
    print(f"Testing {len(models_to_test)} models using 1 API key...")
    tasks = [asyncio.create_task(test_model(m)) for m in models_to_test]
    await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
