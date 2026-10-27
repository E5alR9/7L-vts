# -*- coding: utf-8 -*-
"""模型高音穩定度：直轉成品 f0 跳變率 vs 輸入。若輸出跳、輸入不跳＝模型站不穩。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import librosa

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")


def jumps(path, label):
    y, sr = librosa.load(path, sr=16000, mono=True)
    f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    v = f0[np.isfinite(f0) & (f0 > 50)]
    r = v[1:] / np.maximum(v[:-1], 1e-6)
    j = int(np.sum((r > 1.8) | (r < 0.55)))
    # 高頻粗糙度代理：f0 一階差分中位數（抖動）
    d = np.median(np.abs(np.diff(v)))
    print(f"[{label}] 跳變={j}/{len(v)} ({j/max(len(v),1)*100:.1f}%) 抖動中位={d:.1f}Hz")
    return j / max(len(v), 1)


j_in = jumps(os.path.join(D, "seg.wav"), "輸入原唱")
j_dir = jumps(os.path.join(D, "out_direct.wav"), "直轉成品")
j_sw = jumps(os.path.join(D, "out_sandwich.wav"), "三明治成品")
print(f"輸入跳變率={j_in*100:.1f}% 直轉={j_dir*100:.1f}% 三明治={j_sw*100:.1f}%")
print("DONE")
