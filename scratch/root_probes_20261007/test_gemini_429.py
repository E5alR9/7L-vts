import os
import requests
import json
import sys
import io
import re
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_keys():
    # 強制載入目前的 .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path, override=True)
    
    # 按照 vts_7L_test.py 的邏輯解析
    raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    gemini_keys_list = [k.strip() for k in re.split(r'[\s,;]+', raw_keys) if k.strip() and len(k.strip()) < 150]
    
    gemini_keys = []
    for i, key in enumerate(gemini_keys_list):
        gemini_keys.append((f"Key_{i+1}", key))
        
    print(f"🔍 從 .env 找到 {len(gemini_keys)} 把 Gemini 金鑰，開始逐一測試...", flush=True)
    print("-" * 50, flush=True)
    
    # 測試用的 Prompt
    payload = {
        "contents": [{"parts": [{"text": "hello"}]}]
    }
    
    # 使用日誌中出現的模型名稱
    model = "gemini-3.5-flash-lite"
    
    success_count = 0
    error_429_count = 0
    other_error_count = 0
    
    for name, api_key in gemini_keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            response = requests.post(url, json=payload, timeout=10)
            status = response.status_code
            
            if status == 200:
                print(f"✅ [{name}] 狀態: 200 OK (測試成功，沒有 429)", flush=True)
                success_count += 1
            elif status == 429:
                print(f"❌ [{name}] 狀態: 429 Too Many Requests (真的被限速了)", flush=True)
                error_429_count += 1
            else:
                print(f"⚠️ [{name}] 狀態: {status} - {response.text[:100]}", flush=True)
                other_error_count += 1
        except Exception as e:
            print(f"❌ [{name}] 請求失敗: {e}", flush=True)
            other_error_count += 1
            
    print("-" * 50, flush=True)
    print(f"📊 測試總結: 成功 {success_count} 把 | 確實 429 限速 {error_429_count} 把 | 其他錯誤 {other_error_count} 把", flush=True)
    
if __name__ == "__main__":
    test_keys()
