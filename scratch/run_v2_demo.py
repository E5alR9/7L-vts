# -*- coding: utf-8 -*-
"""三明治 v2 試聽檔：開頭段，原音直進 RVC（f0 軌內部降調）＋一次 post 拉回。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
from services.auto_cover_pipeline import pitch_shift_vocal_to_female

t0 = time.time()
ok = pitch_shift_vocal_to_female(
    os.path.join(D, "opening.wav"),
    os.path.join(D, "open_sandwich_v2.wav"),
    0.0, True)
print(f"v2 done: ok={ok} {time.time()-t0:.0f}s")

import numpy as np
import soundfile as sf
import librosa
for fn in ("opening.wav", "open_direct.wav", "open_sandwich.wav", "open_sandwich_v2.wav"):
    p = os.path.join(D, fn)
    if not os.path.exists(p):
        print(f"{fn}: MISSING"); continue
    y, sr = librosa.load(p, sr=16000, mono=True)
    f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    vv = f0[np.isfinite(f0) & (f0 > 50)]
    yf, _ = sf.read(p, always_2d=True)
    print(f"{fn}: f0med={np.median(vv):.0f} peak={np.max(np.abs(yf)):.3f} "
          f"clips={int(np.sum(np.abs(yf) >= 0.999))}")
print("DONE")
