import os
import google.generativeai as genai

# 🔑 步驟一：請在這裡填入你的 Google Gemini API 金鑰
API_KEY = "AQ.Ab8RN6LCZV4TyIBjFjDqNI35E-xHeKSlPlCZ6qzOaHvvwDugBQ"

def list_all_gemini_models():
    print("📡 正在連線至 Google 伺服器抓取【無過濾完整版】模型清單...\n")
    print("=" * 80)
    
    try:
        # 載入金鑰設定
        genai.configure(api_key=API_KEY)
        
        # 向官方伺服器請求模型列表
        models = genai.list_models()
        
        count = 0
        for m in models:
            # 這次不加任何 if 過濾條件，直接全部印出來！
            print(f"模型 ID: {m.name}")
            print(f"顯示名稱: {m.display_name}")
            print(f"支援方法: {m.supported_generation_methods}")
            print("-" * 80)
            count += 1
                
        print(f"✅ 抓取完畢！這把金鑰目前總共綁定了 {count} 個模型（包含即時版、舊版與特殊專武）。")
        
    except Exception as e:
        print(f"❌ 發生錯誤啦！")
        print(f"錯誤訊息: {e}")

if __name__ == "__main__":
    list_all_gemini_models()