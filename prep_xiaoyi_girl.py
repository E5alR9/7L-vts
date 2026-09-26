import asyncio
import edge_tts
import librosa
import soundfile as sf

VOICE = "zh-CN-XiaoyiNeural"
# 挑選更具少女感、語氣活潑靈動的台詞
GIRL_TEXT = "哇！真的假的？太棒了吧！今天也要一起加油喔！嘿嘿～"
OUTPUT_MP3 = "xiaoyi_girl_ref.mp3"
OUTPUT_WAV = "xiaoyi_girl_ref.wav"

async def generate_girl_ref():
    print(f"正在生成溫柔甜美少女參考音 (自然音調，消除刺耳高音): {VOICE} ...")
    # 🎧 溫柔自然甜美少女調音：移除 +30Hz 刺耳高音，保持 Xiaoyi 標誌性親切甜妹原聲
    communicate = edge_tts.Communicate(GIRL_TEXT, VOICE, rate="+0%", pitch="+0Hz")
    await communicate.save(OUTPUT_MP3)
    
    y, sr = librosa.load(OUTPUT_MP3, sr=32000, mono=True)
    import numpy as np
    y = y / (np.max(np.abs(y)) + 1e-6) * 0.95
    sf.write(OUTPUT_WAV, y, sr)
    print(f"溫柔甜美少女參考音已就緒: {OUTPUT_WAV}")

if __name__ == "__main__":
    asyncio.run(generate_girl_ref())
