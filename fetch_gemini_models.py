import os
import requests
import re
from dotenv import load_dotenv

def get_gemini_models():
    # 讀取 .env 中的設定
    load_dotenv()
    
    # 取得金鑰 (相容單一或多把金鑰的寫法)
    keys_str = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    keys = [k.strip() for k in re.split(r'[\s,;]+', keys_str) if k.strip()]
    
    if not keys:
        print("❌ 找不到 Gemini API 金鑰！請確認 .env 中有設定 GEMINI_API_KEY")
        return
        
    api_key = keys[0]
    print(f"🔍 正在測試金鑰 (前幾個字元): {api_key[:8]}...")
    
    # 呼叫 Gemini 官方 API 列出模型
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    try:
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            print("\n✅ === 目前你的 API 金鑰可呼叫的 Gemini 語言模型 ID ===")
            for model in data.get("models", []):
                # 過濾出支援 "generateContent" (文字/多模態生成) 的模型，過濾掉純 embedding 等模型
                if "generateContent" in model.get("supportedGenerationMethods", []):
                    # 把 models/ 前綴拿掉，就是你填入 GEMINI_MODELS 的 ID
                    model_id = model["name"].replace("models/", "")
                    print(f"👉 '{model_id}',")
                    
        elif response.status_code == 401:
            print("\n❌ 認證失敗 (HTTP 401)：")
            print("你目前 .env 中的金鑰似乎已經失效、過期，或不是標準的 Gemini API 金鑰 (通常應以 AIzaSy 開頭)。")
            print("請至 Google AI Studio (https://aistudio.google.com/app/apikey) 重新申請一把。")
        else:
            print(f"\n❌ 讀取失敗！錯誤代碼: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"發生錯誤: {e}")

if __name__ == "__main__":
    get_gemini_models()
