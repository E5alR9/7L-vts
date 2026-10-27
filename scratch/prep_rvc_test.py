# -*- coding: utf-8 -*-
"""從高音歌切 30 秒高能量段做 RVC 實測輸入。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
from services.rvc_pitch import analyze_vocal_range, decide_sandwich_octave

SRC = r"songs_library\cover_cache\喜歡你_vocals.wav"
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
os.makedirs(OUTDIR, exist_ok=True)

data, sr = sf.read(SRC, always_2d=True)
print("src:", data.shape, sr)
win = int(30 * sr)
hop = int(5 * sr)
best, best_e = 0, -1.0
for s in range(0, len(data) - win + 1, hop):
    e = float(np.mean(data[s:s + win] ** 2))
    if e > best_e:
        best_e, best = e, s
print(f"best window: {best/sr:.0f}s-{(best+win)/sr:.0f}s")
seg = os.path.join(OUTDIR, "seg.wav")
sf.write(seg, data[best:best + win], sr)
med, p90, vs = analyze_vocal_range(seg)
print(f"segment range: median={med:.0f} p90={p90:.0f} voiced={vs:.0f}s sandwich={decide_sandwich_octave(med, p90)}")
print("SEG:", seg)
