import time
import soundfile as sf
from kokoro_onnx import Kokoro

print("=== 正在加載 Kokoro ONNX 日本語聲優引擎 ===")
t0 = time.time()
kokoro = Kokoro("kokoro-v0_19.onnx", "voices-v1.0.bin")
print(f"引擎加載完成！耗時: {time.time()-t0:.2f}s")

# 日語五十音純淨測試
test_jp = "お兄ちゃん、おかえり！待ってたよ！今日も配信見に来てくれてありがとう！"
print(f"\n正在以純正五十音母音發音: {test_jp}")

t_gen = time.time()
# 使用日語聲優音色 (如 jf_alpha: 日語女性聲優)
samples, sample_rate = kokoro.create(
    test_jp,
    voice="jf_alpha",
    speed=1.0,
    lang="ja"
)

output_file = "kokoro_japanese_pure.wav"
sf.write(output_file, samples, sample_rate)
print(f"🎉 生成成功！耗時: {time.time()-t_gen:.2f}s")
print(f"輸出檔案: {output_file}")
