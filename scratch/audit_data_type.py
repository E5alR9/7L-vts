# -*- coding: utf-8 -*-
"""數據集是說話還是唱歌？看連續發聲段長度（說話音節短、唱歌元音長）。
另讀 7L_v2.pth 配置（目標採樣率等，不載入 GPU）。"""
import sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import librosa

files = sorted(glob.glob(r"dataset\xiaoyi_7L\wavs\*.wav"))[:12]
runlens = []
for f in files[:12]:
    y, sr = librosa.load(f, sr=16000, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    gate = max(float(np.max(rms)) * 0.1, 1e-4)
    v = (rms > gate).astype(int)
    d = np.diff(np.concatenate([[0], v, [0]]))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    lens = [(e - s) * 512.0 / 16000 for s, e in zip(starts, ends)]
    runlens.extend(lens)
runlens = np.array(runlens)
print(f"連續發聲段: 中位數={np.median(runlens):.2f}s 平均={runlens.mean():.2f}s "
      f">1s佔比={(runlens > 1.0).mean()*100:.0f}% (>1秒基本就是唱歌的長元音)")
print("--- checkpoint config ---")
import torch
cpt = torch.load(r"C:\Users\qiwai\RVC-WebUI\assets\weights\7L_v2.pth",
                 map_location="cpu", weights_only=False)
cfg = cpt.get("config", None)
print("config:", cfg)
print("weight keys:", len(cpt.get("weight", {})))
print("DONE")
