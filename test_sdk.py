import os
import sys
import io
import re
from dotenv import load_dotenv
from google import genai

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_sdk():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path, override=True)
    
    raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    gemini_keys_list = [k.strip() for k in re.split(r'[\s,;]+', raw_keys) if k.strip() and len(k.strip()) < 150]
    
    if not gemini_keys_list:
        print("沒有找到金鑰")
        return
        
    api_key = gemini_keys_list[0]
    client = genai.Client(api_key=api_key)
    model = "gemini-3.5-flash-lite"
    
    print(f"🔍 測試 google-genai SDK 呼叫 {model}...")
    try:
        response = client.models.generate_content(
            model=model,
            contents="hello"
        )
        print(f"✅ 成功! 回應: {response.text}")
    except Exception as e:
        print(f"❌ 發生異常: {type(e).__name__} - {str(e)}")
        print(f"小寫版字串: {str(e).lower()}")

if __name__ == "__main__":
    test_sdk()
