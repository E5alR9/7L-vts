# -*- coding: utf-8 -*-
"""RMVPE 裁判極端段：真有 900+，還是 yin 誤判？"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "services", "rvc"))
import numpy as np
import librosa

from infer.rmvpe import RMVPE
rmvpe = RMVPE(os.path.join(ROOT, "models", "rvc", "rmvpe.pt"),
              is_half=True, device="cuda:0")

for name in ("extreme.wav", "extreme_direct.wav"):
    p = os.path.join(ROOT, "scratch", "_rvc_test", name)
    y, sr = librosa.load(p, sr=16000, mono=True)
    fr = rmvpe.infer_from_audio(y.astype(np.float32))
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=160)[0]
    n = min(len(fr), len(rms))
    fr, rms = fr[:n], rms[:n]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    vv = fr[(rms > gate) & np.isfinite(fr) & (fr > 50)]
    r = vv[1:] / np.maximum(vv[:-1], 1e-6)
    j = int(np.sum((r > 1.8) | (r < 0.55)))
    print(f"[{name}] rmvpe med={np.median(vv):.0f} p90={np.percentile(vv,90):.0f} "
          f"max={np.max(vv):.0f} 跳變={j}/{len(vv)}({j/max(len(vv),1)*100:.1f}%)")
print("DONE")
