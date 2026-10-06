import os
import sys
import io
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_payload():
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
    
    system_instruction = "You are a helpful AI assistant." * 100 # 大一點的 system prompt
    
    tools = [
        {
            "type": "function",
            "name": "trigger_vts_expression",
            "description": "切換表情",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression_name": {"type": "string"}
                },
                "required": ["expression_name"]
            }
        }
    ]
    
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
        tools=tools
    )
    
    print(f"🔍 測試帶有大 Payload (System Instruction + Tools) 的 {model}...")
    try:
        response = client.models.generate_content(
            model=model,
            contents="hello",
            config=config
        )
        print(f"✅ 成功! 回應: {response.text}")
    except Exception as e:
        print(f"❌ 發生異常: {type(e).__name__} - {str(e)}")

if __name__ == "__main__":
    test_payload()
