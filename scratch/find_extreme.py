# -*- coding: utf-8 -*-
"""找最極端的高音 30 秒（全曲庫滑窗），直轉實測 + 量測，回答「直轉到底會不會破」。"""
import sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa

CACHE = r"songs_library\cover_cache"
OUTD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")

best = None  # (p90, path, start)
for f in sorted(glob.glob(os.path.join(CACHE, "*_vocals.wav"))):
    y, sr = librosa.load(f, sr=16000, mono=True)
    win, hop = int(30 * sr), int(10 * sr)
    for s in range(0, max(len(y) - win, 1), hop):
        seg = y[s:s + win]
        f0 = librosa.yin(seg, fmin=50, fmax=1200, sr=16000)
        rms = librosa.feature.rms(y=seg, frame_length=2048, hop_length=512)[0]
        n = min(len(f0), len(rms))
        f0, rms = f0[:n], rms[:n]
        gate = max(float(np.max(rms)) * 0.1, 1e-4)
        vv = f0[(rms > gate) & np.isfinite(f0) & (f0 > 50)]
        if len(vv) < 100:
            continue
        p90 = float(np.percentile(vv, 90))
        if best is None or p90 > best[0]:
            best = (p90, f, s / sr, float(np.median(vv)))
print(f"extreme: p90={best[0]:.0f} median={best[3]:.0f} "
      f"{os.path.basename(best[1])} @{best[2]:.0f}s")

# 切出來
data, sr = sf.read(best[1], always_2d=True)
s0 = int(best[2] * sr)
seg = data[s0:s0 + int(30 * sr)]
EXT = os.path.join(OUTD, "extreme.wav")
sf.write(EXT, seg, sr)
print("EXT:", EXT)
