# -*- coding: utf-8 -*-
"""DSP 自證清白實驗：
1. roundtrip：原唱 -6 再 +6（不經 RVC），跟原唱比高頻雜訊/瞬態，看 DSP 本身髒不髒。
2. 高頻 hash：8kHz 以上能量比（相位 vocoder 金屬感會堆在這裡）。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa
from services.rvc_pitch import shift_octave_file

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
SRC = os.path.join(D, "opening.wav")
RT = os.path.join(D, "roundtrip_min6_plus6.wav")


def hf_hash(path, cutoff=8000, sr_t=44100):
    y, _ = librosa.load(path, sr=sr_t, mono=True)
    S = np.abs(librosa.stft(y, n_fft=4096, hop_length=1024))
    fr = librosa.fft_frequencies(sr=sr_t, n_fft=4096)
    hi = S[fr >= cutoff].mean()
    lo = S[(fr >= 300) & (fr < cutoff)].mean()
    return float(hi / max(lo, 1e-9))


def onset_corr(a_path, b_path, sr_t=22050):
    a, _ = librosa.load(a_path, sr=sr_t, mono=True)
    b, _ = librosa.load(b_path, sr=sr_t, mono=True)
    n = min(len(a), len(b))
    oa = librosa.onset.onset_strength(y=a[:n], sr=sr_t, hop_length=512)
    ob = librosa.onset.onset_strength(y=b[:n], sr=sr_t, hop_length=512)
    oa -= oa.mean()
    ob -= ob.mean()
    d = max(float(np.std(oa)) * float(np.std(ob)), 1e-9)
    return float((oa * ob).mean() / d)


def flat_of(path):
    y, _ = librosa.load(path, sr=16000, mono=True)
    return float(np.median(librosa.feature.spectral_flatness(y=y)))


ok1 = shift_octave_file(SRC, os.path.join(D, "_rt_mid.wav"), -6.0)
ok2 = shift_octave_file(os.path.join(D, "_rt_mid.wav"), RT, 6.0)
print("roundtrip DSP ok:", ok1 and ok2)
if ok1 and ok2:
    print(f"hf-hash  原唱={hf_hash(SRC):.4f}  roundtrip={hf_hash(RT):.4f} "
          f"(變大＝DSP 堆了高頻金屬雜訊)")
    print(f"flat    原唱={flat_of(SRC):.4f}  roundtrip={flat_of(RT):.4f}")
    print(f"onset相關係數={onset_corr(SRC, RT):.3f} (1.0=瞬態完好, 越低越糊)")
    for f in (os.path.join(D, "_rt_mid.wav"),):
        try:
            os.remove(f)
        except Exception:
            pass
print("DONE")
