import os
import requests
import re
from dotenv import load_dotenv

load_dotenv()
keys_str = os.getenv('OPENROUTER_API_KEYS') or os.getenv('OPENROUTER_API_KEY') or ''
keys = [k.strip() for k in re.split(r'[\s,;]+', keys_str) if k.strip()]

print(f'Found {len(keys)} OpenRouter keys.')

models_to_test = [
    'qwen/qwen3.8-27b:free',
    'google/gemma-4-31b-it:free'
]

# 測試第一把金鑰看看詳細錯誤
if keys:
    key = keys[0]
    print(f"\n--- 測試第 1 把金鑰 ---")
    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json'
    }
    
    for model in models_to_test:
        print(f"\n呼叫模型: {model}")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10
        }
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=10)
            print(f"Status Code: {r.status_code}")
            if r.status_code == 200:
                print("✅ 成功! Response:", r.json()['choices'][0]['message']['content'])
            else:
                print(f"❌ 錯誤! Response: {r.text}")
        except Exception as e:
            print(f"🚨 連線錯誤: {e}")
else:
    print("找不到 OpenRouter API Key。")
