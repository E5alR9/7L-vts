# -*- coding: utf-8 -*-
"""三明治鏈二分：input→mid(前降)→rvc-mid→final，逐段量 f0/包絡/平坦度，定位花栗鼠段。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import soundfile as sf
import librosa

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
FILES = [
    ("input ", "opening.wav"),
    ("mid-6 ", "open_sandwich.sandwich_mid.wav"),
    ("rvc   ", "open_sandwich.sandwich_rvc.wav"),
    ("final ", "open_sandwich.wav"),
    ("direct", "open_direct.wav"),
]


def env_peaks(path, fmin=300, fmax=3500, min_sep=400.0, topn=3):
    y, sr = librosa.load(path, sr=44100, mono=True, offset=2.0, duration=20.0)
    S = np.abs(librosa.stft(y, n_fft=8192, hop_length=2048))
    logmag = np.log(np.maximum(np.mean(S, axis=1), 1e-8))
    ceps = np.fft.irfft(logmag)
    lifter = np.zeros_like(ceps)
    lifter[:40] = 1.0
    env = np.abs(np.fft.rfft(ceps * lifter, n=len(logmag)))
    freqs = librosa.fft_frequencies(sr=44100, n_fft=8192)
    cand = [(env[i], freqs[i]) for i in range(1, len(env) - 1)
            if freqs[i] >= fmin and freqs[i] <= fmax
            and env[i] > env[i - 1] and env[i] > env[i + 1]]
    cand.sort(reverse=True)
    picked = []
    for mag, f in cand:
        if all(abs(f - p) >= min_sep for p in picked):
            picked.append(f)
        if len(picked) == topn:
            break
    return sorted(picked)


def stats(path):
    y, sr = librosa.load(path, sr=16000, mono=True)
    f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    n = min(len(f0), len(rms))
    f0, rms = f0[:n], rms[:n]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    vv = f0[(rms > gate) & np.isfinite(f0) & (f0 > 50)]
    yf, _ = sf.read(path, always_2d=True)
    peak = float(np.max(np.abs(yf)))
    flat = librosa.feature.spectral_flatness(y=y)[0]
    fl = float(np.median(flat[:n][rms > gate])) if n else 0.0
    return (float(np.median(vv)) if len(vv) else 0.0), peak, fl


print(f"{'stage':7} {'f0med':>6} {'peak':>5} {'flat':>7} env-peaks")
res = {}
for label, fn in FILES:
    p = os.path.join(D, fn)
    if not os.path.exists(p):
        print(f"{label:7} MISSING {fn}")
        continue
    med, peak, fl = stats(p)
    env = env_peaks(p)
    res[label] = (med, env)
    print(f"{label:7} {med:6.0f} {peak:5.3f} {fl:7.4f} {[int(x) for x in env]}")

if all(k in res for k in ("input ", "mid-6 ", "rvc   ", "final ")):
    mi, mm, mr, mf = (res[k][0] for k in ("input ", "mid-6 ", "rvc   ", "final "))
    print(f"\nf0鏈: in={mi:.0f} → mid={mm:.0f}(x{mm/max(mi,1):.2f}, 預期÷1.41) → "
          f"rvc={mr:.0f}(x{mr/max(mm,1):.2f}, 預期≈1.0) → final={mf:.0f}(x{mf/max(mr,1):.2f}, 預期×1.41)")
    ei, em, er, ef = (res[k][1] for k in ("input ", "mid-6 ", "rvc   ", "final "))
    def show(tag, a, b):
        pairs = min(len(a), len(b))
        rs = [b[i] / max(a[i], 1) for i in range(pairs)]
        print(f"包絡{tag}: {[round(x,2) for x in rs]} (1.0=保住, 1.41=跟音高跑=花栗鼠)")
    show("mid/in ", ei, em)
    show("rvc/mid ", em, er)
    show("final/rvc", er, ef)
print("DONE")
