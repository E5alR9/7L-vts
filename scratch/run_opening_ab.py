# -*- coding: utf-8 -*-
"""開頭段實測：直轉 vs 三明治，誰在第一句出怪聲。檔案全留給耳朵驗屍。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
SRC = r"songs_library\cover_cache\喜歡你_vocals.wav"
data, sr = sf.read(SRC, always_2d=True)
seg = data[:int(30 * sr)]
OP = os.path.join(D, "opening.wav")
sf.write(OP, seg, sr)

from services.rvc_pitch import analyze_vocal_range
med, p90, vs = analyze_vocal_range(OP)
print(f"opening range: median={med} p90={p90} voiced={vs:.0f}s")

# f0 雙追蹤：yin vs （rmvpe 太重，這裡先看 yin 穩定度＋能量包絡）
y, _ = librosa.load(OP, sr=16000, mono=True)
f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
n = min(len(f0), len(rms))
f0, rms = f0[:n], rms[:n]
gate = max(float(np.max(rms)) * 0.05, 1e-4)
for sec in (5, 15, 30):
    m = int(sec * 16000 / 512)
    seg_f0 = f0[:m]
    vv = seg_f0[np.isfinite(seg_f0) & (seg_f0 > 50)]
    r = vv[1:] / np.maximum(vv[:-1], 1e-6)
    j = int(np.sum((r > 1.8) | (r < 0.55)))
    print(f"前{sec}s: voiced中位={np.median(vv):.0f} 跳變={j}/{len(vv)}({j/max(len(vv),1)*100:.0f}%) 能量比={float(np.mean(rms[:m]))/max(float(np.max(rms)),1e-9):.2f}")

from services.neural_voice_converter import convert_vocal_to_xiaoyi
from services.auto_cover_pipeline import pitch_shift_vocal_to_female
MP = r"C:\Users\qiwai\RVC-WebUI\assets\weights\7L_v2.pth"
IX = r"C:\Users\qiwai\RVC-WebUI\assets\indices\7L_v2_added_IVF256_Flat_nprobe_1_7L_v2_v2.index"

t0 = time.time()
ok_a = convert_vocal_to_xiaoyi(OP, os.path.join(D, "open_direct.wav"),
                               key=0.0, model_pth=MP, index_file=IX,
                               index_rate=0.88, auto_pitch=True)
print(f"direct: ok={ok_a} {time.time()-t0:.0f}s")
t0 = time.time()
ok_b = pitch_shift_vocal_to_female(OP, os.path.join(D, "open_sandwich.wav"), 0.0, True)
print(f"sandwich: ok={ok_b} {time.time()-t0:.0f}s")


def measure(path, label):
    y, sr = librosa.load(path, sr=16000, mono=True)
    f = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    vv = f[np.isfinite(f) & (f > 50)]
    r = vv[1:] / np.maximum(vv[:-1], 1e-6)
    j = int(np.sum((r > 1.8) | (r < 0.55)))
    yf, _ = sf.read(path, always_2d=True)
    peak = float(np.max(np.abs(yf)))
    nclip = int(np.sum(np.abs(yf) >= 0.999))
    print(f"[{label}] f0med={np.median(vv):.0f} 跳變={j}/{len(vv)}({j/max(len(vv),1)*100:.0f}%) peak={peak:.3f} clips={nclip}")


print("--- input ---")
measure(OP, "input ")
print("--- outputs ---")
if ok_a:
    measure(os.path.join(D, "open_direct.wav"), "direct")
if ok_b:
    measure(os.path.join(D, "open_sandwich.wav"), "sandw ")
print("FILES READY FOR EARS:", sorted(os.path.basename(p) for p in
      [OP, os.path.join(D, "open_direct.wav"), os.path.join(D, "open_sandwich.wav")]
      if os.path.exists(p)))
print("DONE")
