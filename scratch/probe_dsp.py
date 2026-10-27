# -*- coding: utf-8 -*-
"""量測：librosa版本/soxr/soundfile有無＋yin全曲分析耗時＋pitch_shift立體聲行為。"""
import sys, time
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import librosa
print("librosa:", librosa.__version__)
try:
    import soxr
    print("soxr: yes", soxr.__version__)
except Exception as e:
    print("soxr: NO", e)
try:
    import soundfile as sf
    print("soundfile: yes")
except Exception as e:
    print("soundfile: NO", e)

sr = 16000
dur = 180.0
t = np.arange(int(sr * dur)) / sr
# 混合：A3(220) 60s + A4(440) 60s + E5(659) 60s，立體聲
mono = np.concatenate([np.sin(2 * np.pi * f * t[:sr * 60]) for f in (220.0, 440.0, 659.0)])
stereo = np.stack([mono, mono * 0.9])
print("synth shape:", stereo.shape)

t0 = time.time()
f0 = librosa.yin(stereo[0], fmin=50, fmax=800, sr=sr, frame_length=2048, hop_length=512)
t1 = time.time()
voiced = f0[~np.isnan(f0)]
print(f"yin full-track: {t1-t0:.1f}s, voiced frames={len(voiced)}, median={np.median(voiced):.1f}")

t0 = time.time()
y2 = librosa.effects.pitch_shift(stereo[0][:sr * 10], sr=sr, n_steps=-12)
t1 = time.time()
print(f"pitch_shift 10s mono: {t1-t0:.1f}s, in={sr*10}, out={len(y2)}")
try:
    y3 = librosa.effects.pitch_shift(stereo[:, :sr * 5], sr=sr, n_steps=12)
    print(f"pitch_shift stereo in-shape={stereo[:, :sr*5].shape} out-shape={y3.shape}")
except Exception as e:
    print("pitch_shift stereo FAIL:", str(e)[:150])
