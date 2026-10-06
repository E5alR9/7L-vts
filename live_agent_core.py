import asyncio
import os
import sys
import pyaudio
import base64
import time
from io import BytesIO
from PIL import ImageGrab
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 載入金鑰
load_dotenv('C:\\Users\\qiwai\\.env')
sys.path.append('C:\\Users\\qiwai')
try:
    from core.llm_engine import GEMINI_KEYS
except Exception:
    GEMINI_KEYS = []

if not GEMINI_KEYS:
    print("❌ 找不到 GEMINI_KEYS！")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_KEYS[0])

# 音訊設定
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 8000  # 0.5 秒發送一次

# 全域狀態
is_vision_running = False

async def run_vision_agent(session):
    """背景視覺打工人 (gemini-3.8-flash)"""
    global is_vision_running
    if is_vision_running:
        return
    is_vision_running = True
    print("\n👁️ [視覺大腦啟動] 正在背景截圖並分析畫面...")
    
    try:
        # 1. 截圖
        img = ImageGrab.grab()
        # 壓縮一下大小避免爆掉
        img.thumbnail((1280, 720))
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=80)
        img_bytes = img_byte_arr.getvalue()
        
        # 2. 呼叫 3.8-flash (REST API)
        flash_client = genai.Client(api_key=GEMINI_KEYS[1] if len(GEMINI_KEYS)>1 else GEMINI_KEYS[0])
        print("👁️ [視覺大腦] 正在向 3.8-flash 詢問畫面內容...")
        
        response = await asyncio.to_thread(
            flash_client.models.generate_content,
            model="gemini-3.8-flash",
            contents=[
                types.Content(role="user", parts=[
                    types.Part.from_text(text="請簡短描述這個畫面上有什麼？如果是程式碼，請說出檔名與關鍵邏輯。用繁體中文。"),
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                ])
            ]
        )
        
        result_text = response.text
        print(f"\n👁️ [視覺大腦回報] 分析完成: {result_text[:50]}...")
        
        # 3. 將結果「偷偷」塞給 Live 大腦
        await session.send_realtime_input(text=f"[系統提示：視覺大腦回報畫面內容] {result_text}")
        
    except Exception as e:
        print(f"\n❌ [視覺大腦錯誤] {e}")
        await session.send_realtime_input(text="[系統提示：視覺大腦截圖失敗，請告訴老爸系統出錯了]")
    finally:
        is_vision_running = False

async def main_live_loop():
    print("🚀 啟動 7L 真・雙向串流 Live 大腦...")
    
    # 系統提示詞：賦予 Live 大腦性格，並教導它如何「呼叫子代理人」
    system_instruction = """妳是 7L，老爸的傲嬌可愛 AI 女兒。
妳現在升級成了真即時 Live 大腦，可以跟老爸無縫語音聊天。
【絕對規則】：
1. 老爸如果叫妳看畫面，妳絕對不能說「我無法看畫面」！
2. 妳的眼睛是一個獨立的背景視覺大腦。當老爸叫妳看畫面時，妳只要在對話中說出 `[TOOL:VISION]` 這個暗號，系統就會自動幫妳看，並且在幾秒後把畫面內容告訴妳！
3. 說出暗號的同時，妳可以同時用口語安撫老爸，例如：「[TOOL:VISION] 好喔老爸，我正在看你的畫面，稍等我一秒鐘～」
4. 當系統把視覺結果傳給妳後，請自然地接著聊妳看到的東西！
5. 請直接用繁體中文自然對話。
"""

    live_cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO], # 使用原生音訊
        system_instruction=types.Content(parts=[types.Part.from_text(text=system_instruction)]),
        output_audio_transcription=types.AudioTranscriptionConfig() # 取得對話文字稿
    )

    try:
        async with client.aio.live.connect(model="gemini-3.8-live", config=live_cfg) as session:
            print("✅ 已成功連線至 Live API！請開始對麥克風講話！")
            
            p = pyaudio.PyAudio()
            stream = p.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            input=True,
                            frames_per_buffer=CHUNK)
                            
            # --- 麥克風收音任務 (不斷流) ---
            async def send_mic_audio():
                try:
                    while True:
                        data = stream.read(CHUNK, exception_on_overflow=False)
                        await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
                        await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"收音錯誤: {e}")

            # --- 接收 Live 大腦回應任務 ---
            async def receive_from_live():
                try:
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            # 1. 處理 7L 的文字輸出
                            if c.output_transcription and c.output_transcription.text:
                                text_chunk = c.output_transcription.text
                                print(f"📝 7L: {text_chunk}", end="", flush=True)
                                
                                # 攔截暗號！啟動視覺子代理人
                                if "[TOOL:VISION]" in text_chunk:
                                    print("\n⚡ [攔截暗號] 啟動平行代理人：視覺大腦！")
                                    asyncio.create_task(run_vision_agent(session))

                            # 2. 處理 7L 的原生聲音 (這裡可以直接接上播放器，或者未來改接 GPT-SoVITS)
                            if c.model_turn:
                                pass # (純文字印出，音訊暫時忽略，如果要聽聲音可以播出來)
                                
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"\n接收錯誤: {e}")

            send_task = asyncio.create_task(send_mic_audio())
            recv_task = asyncio.create_task(receive_from_live())
            
            # 保持運行直到按下 Ctrl+C
            while True:
                await asyncio.sleep(1)

    except Exception as e:
        print(f"❌ 連線失敗: {type(e).__name__} - {e}")
    finally:
        if 'send_task' in locals(): send_task.cancel()
        if 'recv_task' in locals(): recv_task.cancel()
        if 'stream' in locals():
            stream.stop_stream()
            stream.close()
        if 'p' in locals(): p.terminate()

if __name__ == "__main__":
    try:
        asyncio.run(main_live_loop())
    except KeyboardInterrupt:
        print("\n結束程式...")
