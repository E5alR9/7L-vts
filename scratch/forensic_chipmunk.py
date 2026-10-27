# -*- coding: utf-8 -*-
"""驗屍：最近翻唱成品 vs 原唱，f0 軌跡＋頻譜包絡，定位花栗鼠來源。"""
import sys, os, glob, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import soundfile as sf
import librosa
from services.rvc_pitch import analyze_vocal_range

CACHE = r"songs_library\cover_cache"
files = sorted(glob.glob(os.path.join(CACHE, "*_7l_vocal.wav")),
               key=os.path.getmtime, reverse=True)[:4]

def spec_centroid(path, sr_t=16000, seconds=30, offset=20.0):
    y, sr = librosa.load(path, sr=sr_t, mono=True, offset=offset, duration=seconds)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    cents = []
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr_t, n_fft=2048)
    for i in range(S.shape[1]):
        if rms[i] > gate:
            mag = S[:, i]
            if mag.sum() > 0:
                cents.append(float((freqs * mag).sum() / mag.sum()))
    return float(np.median(cents)) if cents else 0.0

for out in files:
    base = os.path.basename(out)
    name = base.replace("_7l_vocal.wav", "")
    print("=" * 70)
    print("成品:", base, f"({os.path.getsize(out)//1024}KB)")
    # 找輸入：同 safe 名的 _raw / _vocals
    cand_in = None
    for suf in ("_raw.wav", "_vocals.wav"):
        p = os.path.join(CACHE, name + suf)
        if os.path.exists(p):
            cand_in = p
            break
    if not cand_in:
        print("  找不到對應輸入，跳過")
        continue
    print("輸入:", os.path.basename(cand_in))
    med_in, p90_in, vs = analyze_vocal_range(cand_in)
    med_out, p90_out, _ = analyze_vocal_range(out)
    print(f"  輸入整體: median={med_in} p90={p90_in} 發聲{vs:.0f}s")
    print(f"  輸出整體: median={med_out} p90={p90_out}")
    if med_in and med_out:
        print(f"  f0 比例(出/入)={med_out/med_in:.2f}（三明治應≈1.0，直轉+12應≈2.0）")
    c_in = spec_centroid(cand_in)
    c_out = spec_centroid(out)
    print(f"  頻譜質心: 入={c_in:.0f}Hz 出={c_out:.0f}Hz 比例={c_out/max(c_in,1):.2f}（花栗鼠≈跟著f0跑）")
