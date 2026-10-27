# -*- coding: utf-8 -*-
"""定位削波：第幾段開始爆的（輸入→前降→RVC中音→回拉）。"""
import sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import soundfile as sf

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
for f in sorted(glob.glob(os.path.join(D, "*.wav"))):
    try:
        y, sr = sf.read(f, always_2d=True)
    except Exception as e:
        print(os.path.basename(f), "READ FAIL", e)
        continue
    peak = float(np.max(np.abs(y)))
    rms = float(np.sqrt(np.mean(y.astype(np.float64) ** 2)))
    nclip = int(np.sum(np.abs(y) >= 0.999))
    nhot = int(np.sum(np.abs(y) >= 0.95))
    print(f"peak={peak:.3f} rms={rms:.3f} clips={nclip:5d} hot95={nhot:6d} {os.path.basename(f)}")
