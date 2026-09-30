import asyncio
import time
import os
import sys

# Ensure core and services can be imported
sys.path.append(r"C:\Users\qiwai")

from services.tts_router import _synth_kokoro, _synth_xiaoyi

async def main():
    test_text = "老爸，這是一段用來測試語音合成速度的文字！我們來看看誰跑得比較快吧，準備好了嗎？三、二、一，開始！"
    
    print(f"測試句子長度: {len(test_text)} 字")
    print(f"測試句子: {test_text}")
    print("-" * 50)
    
    # 測試 Kokoro
    print("🚀 [開始測試 Kokoro-82M ONNX]")
    try:
        t0 = time.time()
        audio_k = await _synth_kokoro(test_text)
        t1 = time.time()
        elapsed_k = t1 - t0
        
        # Save file
        k_path = os.path.join(r"C:\Users\qiwai\scratch", "kokoro_test.wav")
        with open(k_path, "wb") as f:
            f.write(audio_k)
            
        print(f"✅ Kokoro 成功! 耗時: {elapsed_k:.3f} 秒 (產出檔案: {k_path})")
    except Exception as e:
        print(f"❌ Kokoro 失敗: {e}")
        elapsed_k = None
        
    print("-" * 50)
    
    # 測試 GPT-SoVITS
    print("🚀 [開始測試 GPT-SoVITS (xiaoyi)]")
    try:
        t0 = time.time()
        audio_g = await _synth_xiaoyi(test_text)
        t1 = time.time()
        elapsed_g = t1 - t0
        
        # Save file
        g_path = os.path.join(r"C:\Users\qiwai\scratch", "gpt_sovits_test.wav")
        with open(g_path, "wb") as f:
            f.write(audio_g)
            
        print(f"✅ GPT-SoVITS 成功! 耗時: {elapsed_g:.3f} 秒 (產出檔案: {g_path})")
    except Exception as e:
        print(f"❌ GPT-SoVITS 失敗: {e}")
        elapsed_g = None
        
    print("=" * 50)
    print("🏆 【最終對比結果】 🏆")
    if elapsed_k and elapsed_g:
        if elapsed_k < elapsed_g:
            print(f"Kokoro 獲勝！比 GPT-SoVITS 快了 {elapsed_g / elapsed_k:.1f} 倍！")
        else:
            print(f"GPT-SoVITS 獲勝！比 Kokoro 快了 {elapsed_k / elapsed_g:.1f} 倍！")

if __name__ == "__main__":
    # Force mock env to test GPT-SoVITS locally if needed, though tts_router uses OS env
    asyncio.run(main())
