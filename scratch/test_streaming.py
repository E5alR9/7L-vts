import asyncio
import time
from google import genai
from dotenv import load_dotenv
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_streaming():
    load_dotenv(r"C:\Users\qiwai\.env")
    raw_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
    
    # 之前這裡寫錯了，.env 裡是用空白分隔，不是逗號
    keys = [k.strip() for k in raw_keys.split() if k.strip()]
    
    if not keys:
        print("沒有找到 Gemini 金鑰")
        return
        
    print(f"找到 {len(keys)} 把金鑰，準備開始測試串流...")
    
    for key_idx, k in enumerate(keys):
        api_key = "".join(c for c in k if c.isprintable()).strip('"').strip("'")
        client = genai.Client(api_key=api_key)
        
        print(f"\n👉 嘗試使用第 {key_idx + 1} 把金鑰...")
        start_time = time.time()
        
        try:
            stream_iter = await client.aio.models.generate_content_stream(
                model='gemini-3.5-flash-lite',
                contents='請用繁體中文寫一篇關於「太空旅行」的短文，大約 30 字就好。'
            )
            
            print("✅ 成功建立串流通道！開始接收碎片...\n")
            print("-" * 50)
            
            chunk_count = 0
            async for chunk in stream_iter:
                if chunk.text:
                    chunk_count += 1
                    elapsed = time.time() - start_time
                    # 故意把收到的內容印出來，並附上收到的時間
                    print(f"[{elapsed:.2f} s] 第 {chunk_count:02d} 包: {repr(chunk.text)}")
                    
            total_time = time.time() - start_time
            print("-" * 50)
            print(f"\n🏁 測試結束！共收到 {chunk_count} 包文字碎片，總耗時 {total_time:.2f} 秒。")
            print("結論：API 確實是「邊算邊給」，而不是等全部算完才一次給！")
            return  # 成功跑完就結束
            
        except Exception as e:
            err_msg = str(e)
            # 如果是 401 就安靜跳過，如果是其他錯誤再印出來
            if "401" in err_msg or "UNAUTHENTICATED" in err_msg:
                print("❌ 這把金鑰無效 (401)，換下一把...")
            else:
                print(f"❌ 發生錯誤: {err_msg[:100]}")

if __name__ == "__main__":
    asyncio.run(test_streaming())
