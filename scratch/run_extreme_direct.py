# -*- coding: utf-8 -*-
"""極端段直轉實測：f0正確性＋削波＋穩定度＋成品留檔給耳朵。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
EXT = os.path.join(D, "extreme.wav")
OUT = os.path.join(D, "extreme_direct.wav")

from services.neural_voice_converter import convert_vocal_to_xiaoyi
MP = r"C:\Users\qiwai\RVC-WebUI\assets\weights\7L_v2.pth"
IX = r"C:\Users\qiwai\RVC-WebUI\assets\indices\7L_v2_added_IVF256_Flat_nprobe_1_7L_v2_v2.index"
t0 = time.time()
ok = convert_vocal_to_xiaoyi(EXT, OUT, key=0.0, model_pth=MP, index_file=IX,
                             index_rate=0.88, auto_pitch=True)
print(f"direct extreme: ok={ok} {time.time()-t0:.0f}s")
assert ok and os.path.exists(OUT)


def stats(path, label, fmax=1200):
    y, sr = librosa.load(path, sr=16000, mono=True)
    f0 = librosa.yin(y, fmin=50, fmax=fmax, sr=16000)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    n = min(len(f0), len(rms))
    f0, rms = f0[:n], rms[:n]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    vv = f0[(rms > gate) & np.isfinite(f0) & (f0 > 50)]
    r = vv[1:] / np.maximum(vv[:-1], 1e-6)
    j = int(np.sum((r > 1.8) | (r < 0.55)))
    yf, _ = sf.read(path, always_2d=True)
    peak = float(np.max(np.abs(yf)))
    print(f"[{label}] med={np.median(vv):.0f} p90={np.percentile(vv,90):.0f} "
          f"跳變={j}/{len(vv)}({j/max(len(vv),1)*100:.1f}%) peak={peak:.3f} "
          f"clips={int(np.sum(np.abs(yf) >= 0.999))}")


stats(EXT, "input ")
stats(OUT, "direct")
print("OUT:", OUT)
print("DONE")
