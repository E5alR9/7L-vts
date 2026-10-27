# -*- coding: utf-8 -*-
"""RVC-WebUI/datasets/7L_singing 真實訓練集稽核：每首音域＋總時長。"""
import sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa

files = sorted(glob.glob(r"RVC-WebUI\datasets\7L_singing\*.wav"))
print(f"files: {len(files)}")
tot = 0.0
for f in files:
    info = sf.info(f)
    dur = info.frames / info.samplerate
    tot += dur
    y, sr = librosa.load(f, sr=16000, mono=True, duration=min(dur, 150.0))
    f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    n = min(len(f0), len(rms))
    f0, rms = f0[:n], rms[:n]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    vv = f0[(rms > gate) & np.isfinite(f0) & (f0 > 50)]
    med = float(np.median(vv)) if len(vv) else 0
    p90 = float(np.percentile(vv, 90)) if len(vv) else 0
    flag = ""
    nl = os.path.basename(f).lower()
    if "nightcore" in nl or "slowed" in nl or "reverb" in nl or "breakcore" in nl:
        flag = " ← DSP加工過"
    print(f"{med:5.0f} {p90:5.0f} {dur:5.0f}s {flag:12} {os.path.basename(f)[:50]}")
print(f"total: {tot/60:.1f} min")
print("DONE")
