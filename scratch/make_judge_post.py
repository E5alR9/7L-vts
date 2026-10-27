# -*- coding: utf-8 -*-
"""判官檔：乾淨直轉成品直接 +6（不經 RVC、不經前降）。
花栗鼠＝post-DSP 有罪；乾淨＝post 無罪，兇手在 RVC-mid。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa
from services.rvc_pitch import shift_octave_file

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
SRC = os.path.join(D, "open_direct.wav")
OUT = os.path.join(D, "judge_post_only_plus6.wav")
assert os.path.exists(SRC), SRC
assert shift_octave_file(SRC, OUT, 6.0) is True

for label, p in (("direct-clean ", SRC), ("post-only +6", OUT)):
    y, sr = librosa.load(p, sr=16000, mono=True)
    f0 = librosa.yin(y, fmin=50, fmax=1600, sr=16000)
    vv = f0[np.isfinite(f0) & (f0 > 50)]
    yf, _ = sf.read(p, always_2d=True)
    print(f"[{label}] f0med={np.median(vv):.0f} peak={np.max(np.abs(yf)):.3f} "
          f"clips={int(np.sum(np.abs(yf) >= 0.999))}")
print("JUDGE FILE:", OUT)
print("DONE")
