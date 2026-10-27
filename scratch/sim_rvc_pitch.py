# -*- coding: utf-8 -*-
"""RVC 整首統一判決執行模擬：載入真實 compute_adaptive_phrase_keys（重依賴 stub），
餵合成 f0（低音樂句＋中音樂句混合），驗證全曲單一偏移、絕不跳變。"""
import sys, os, types
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "services", "rvc"))

# 依賴全用真的（torch/faiss/librosa/scipy 本機都有）；只需要補 path，
# 讓 pipeline.py 內的裸 import（from infer.hubert import ...）能解析。
import infer.vc.pipeline as _pl  # noqa: E402


def make_track(segs, frame_ms=10, total_s=20.0):
    """segs: [(t0, t1, f0_hz or None), ...] → (f0_interp, uv_mask)."""
    n = int(total_s * 1000 / frame_ms)
    f0 = np.zeros(n, dtype=np.float32)
    uv = np.ones(n, dtype=bool)
    for t0, t1, hz in segs:
        s, e = int(t0 * 1000 / frame_ms), int(t1 * 1000 / frame_ms)
        s, e = max(0, s), min(n, e)
        if hz:
            f0[s:e] = hz
            uv[s:e] = False
    return f0, uv


def voiced_values(key_shifts, f0):
    return key_shifts[f0 > 50]


# Pipeline.__new__ 跳過 __init__（方法本體沒用到實例屬性）
pipe = _pl.Pipeline.__new__(_pl.Pipeline)

# --- 場景 1：混合（低 8s + 中 4s）→ 全曲 +12，發聲區零跳變 ---
f0, uv = make_track([(1.0, 5.0, 130.0), (6.0, 10.0, 130.0), (11.0, 15.0, 260.0)])
ks = pipe.compute_adaptive_phrase_keys(f0, uv)
v = voiced_values(ks, f0)
assert set(np.unique(v)) == {12.0}, f"mixed-low must be uniform +12, got {np.unique(v)}"

# --- 場景 2：混合（低 3s + 中 12s）→ 全曲 0 ---
f0, uv = make_track([(1.0, 4.0, 130.0), (5.0, 11.0, 260.0), (12.0, 18.0, 280.0)])
ks = pipe.compute_adaptive_phrase_keys(f0, uv)
v = voiced_values(ks, f0)
assert set(np.unique(v)) == {0.0}, f"mixed-high must be uniform 0, got {np.unique(v)}"

# --- 場景 3：全低 → +12；全高 → 0 ---
f0, uv = make_track([(1.0, 9.0, 140.0), (10.0, 18.0, 170.0)])
assert set(np.unique(voiced_values(pipe.compute_adaptive_phrase_keys(f0, uv), f0))) == {12.0}
f0, uv = make_track([(1.0, 9.0, 240.0), (10.0, 18.0, 300.0)])
assert set(np.unique(voiced_values(pipe.compute_adaptive_phrase_keys(f0, uv), f0))) == {0.0}

# --- 場景 4：全靜音 → 全 0 不炸 ---
f0 = np.zeros(500, dtype=np.float32)
uv = np.ones(500, dtype=bool)
assert set(np.unique(pipe.compute_adaptive_phrase_keys(f0, uv))) == {0.0}

# --- 場景 5：base_offset 照加 ---
f0, uv = make_track([(1.0, 9.0, 140.0)])
ks = pipe.compute_adaptive_phrase_keys(f0, uv, base_offset=2.0)
assert set(np.unique(voiced_values(ks, f0))) == {14.0}

print("RVC PITCH SIM: ALL OK")
