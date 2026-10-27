# -*- coding: utf-8 -*-
"""dataset/xiaoyi_7L 稽核：檔數、總時長、音域分佈（重訓有沒有高音吃， grain 先看）。"""
import sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa

files = sorted(glob.glob(r"dataset\xiaoyi_7L\wavs\*.wav"))
print(f"files: {len(files)}")
if not files:
    raise SystemExit(0)

tot_dur = 0.0
rows = []
for f in files:
    try:
        y, sr = librosa.load(f, sr=16000, mono=True)
    except Exception as e:
        print("READ FAIL", os.path.basename(f), str(e)[:80])
        continue
    dur = len(y) / 16000
    tot_dur += dur
    f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    n = min(len(f0), len(rms))
    f0, rms = f0[:n], rms[:n]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    vv = f0[(rms > gate) & np.isfinite(f0) & (f0 > 50)]
    if len(vv):
        rows.append((float(np.median(vv)), float(np.percentile(vv, 90)), dur, os.path.basename(f)))

print(f"total duration: {tot_dur/60:.1f} min, measurable: {len(rows)}")
rows.sort()
import math
meds = [r[0] for r in rows]
print(f"median-of-medians={np.median(meds):.0f} min={min(meds):.0f} max={max(meds):.0f}")
for lo, hi, tag in ((0, 195, "低"), (195, 300, "中"), (300, 450, "高"), (450, 1e9, "超高")):
    c = [r for r in rows if lo <= r[0] < hi]
    d = sum(r[2] for r in c)
    print(f"{tag}: {len(c)} 檔, {d/60:.1f} 分鐘")
print("--- top5 by median ---")
for med, p90, dur, name in rows[-5:]:
    print(f"{med:.0f}/{p90:.0f} {dur:.0f}s {name}")
print("DONE")
