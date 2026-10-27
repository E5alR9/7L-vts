# -*- coding: utf-8 -*-
"""RMVPE vs yin 高音追蹤對打：八度跳變誰多，誰就是破音/怪聲的源頭之一。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "services", "rvc"))
import numpy as np
import soundfile as sf
import librosa

SEG = os.path.join(ROOT, "scratch", "_rvc_test", "seg.wav")
assert os.path.exists(SEG), f"segment missing: {SEG}"

y, sr = librosa.load(SEG, sr=16000, mono=True)
print(f"audio: {len(y)/sr:.0f}s @ {sr}Hz")

# 以能量取共同 voiced 遮罩
rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=160)[0]  # 與 rmvpe 同 10ms 格
gate = max(float(np.max(rms)) * 0.05, 1e-4)
print(f"voiced frames: {int((rms > gate).sum())}/{len(rms)}")


def octave_jumps(f0):
    v = f0[np.isfinite(f0) & (f0 > 50)]
    if len(v) < 2:
        return 0, 0
    r = v[1:] / np.maximum(v[:-1], 1e-6)
    jumps = int(np.sum((r > 1.8) | (r < 0.55)))
    return jumps, len(v)


def stats(name, f0):
    v = f0[np.isfinite(f0) & (f0 > 50)]
    j, n = octave_jumps(f0)
    print(f"[{name}] med={np.median(v):.0f} p90={np.percentile(v,90):.0f} "
          f"跳變={j}/{n} ({j/max(n,1)*100:.1f}%)")
    return v


t0 = time.time()
fy = librosa.yin(y, fmin=50, fmax=800, sr=16000, frame_length=2048, hop_length=512)
# yin 是 32ms 格，重取樣到 10ms 格對齊比較（話題只在跳變率，不比逐幀）
print(f"yin: {time.time()-t0:.1f}s")
vy = stats("yin   ", fy)

t0 = time.time()
from infer.rmvpe import RMVPE
rmvpe = RMVPE(os.path.join(ROOT, "models", "rvc", "rmvpe.pt"),
              is_half=True, device="cuda:0")
fr = rmvpe.infer_from_audio(y.astype(np.float32))
print(f"rmvpe: {time.time()-t0:.1f}s, frames={len(fr)}")
vr = stats("rmvpe ", fr)
print("DONE")
