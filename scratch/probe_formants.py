# -*- coding: utf-8 -*-
"""驗 formant=preserved 是否真保得住：穩態母音＋倒頻譜包絡峰（有最小間距），
比較 shift 前後包絡峰位移。包絡不動＝保住，包絡跟著×2＝花栗鼠。"""
import sys, os, subprocess
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa
from scipy.signal import butter, sosfilt

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_formant_probe")
os.makedirs(TMP, exist_ok=True)
sr = 44100

# 穩態「啊」：f0=220Hz 無顫音＋800/1200/2800 共振峰
dur = 4.0
t = np.arange(int(sr * dur)) / sr
phase = 2 * np.pi * 220.0 * t
src = sum(np.sin(k * phase) / k for k in range(1, 9))
src = src / np.max(np.abs(src))
sos = np.vstack([
    butter(4, [700 / (sr / 2), 900 / (sr / 2)], btype="band", output="sos"),
    butter(4, [1100 / (sr / 2), 1300 / (sr / 2)], btype="band", output="sos"),
    butter(4, [2600 / (sr / 2), 3000 / (sr / 2)], btype="band", output="sos"),
])
vowel = sosfilt(sos, src)
vowel = (0.5 * vowel / np.max(np.abs(vowel))).astype(np.float32)
inp = os.path.join(TMP, "vowel_steady.wav")
sf.write(inp, vowel, sr)


def envelope_peaks(path, fmin=300, fmax=3500, min_sep=300.0):
    """倒頻譜包絡峰：real cepstrum → 低倒頻域 lifter → 包絡 → 找峰（強制最小間距）。"""
    y, _ = librosa.load(path, sr=sr, mono=True, offset=1.0, duration=2.5)
    S = np.abs(librosa.stft(y, n_fft=8192, hop_length=2048))
    logmag = np.log(np.maximum(np.mean(S, axis=1), 1e-8))
    ceps = np.fft.irfft(logmag)
    lifter = np.zeros_like(ceps)
    lifter[:48] = 1.0  # 只留慢變包絡
    env = np.abs(np.fft.rfft(ceps * lifter, n=len(logmag)))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=8192)
    cand = [(env[i], freqs[i]) for i in range(1, len(env) - 1)
            if (freqs[i] >= fmin and freqs[i] <= fmax
                and env[i] > env[i - 1] and env[i] > env[i + 1])]
    cand.sort(reverse=True)
    picked = []
    for mag, f in cand:
        if all(abs(f - p) >= min_sep for p in picked):
            picked.append(f)
        if len(picked) == 3:
            break
    return sorted(picked)


def f0_fft(path):
    y, _ = librosa.load(path, sr=16000, mono=True, offset=1.0, duration=2.0)
    S = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1.0 / 16000)
    band = (freqs >= 100) & (freqs <= 900)
    f, m = freqs[band], S[band]
    return float(f[int(np.argmax(m))])


print("原音：f0=%.0f 包絡=%s" % (f0_fft(inp), [int(x) for x in envelope_peaks(inp)]))
FF = r"C:\ffmpeg\bin\ffmpeg.exe"
for label, filt in [("preserved", "pitch=2.0:formant=preserved"),
                    ("shifted(default)", "pitch=2.0")]:
    out = os.path.join(TMP, f"up_{label.split('(')[0]}.wav")
    r = subprocess.run([FF, "-y", "-v", "error", "-i", inp,
                        "-af", f"rubberband={filt}", out],
                       capture_output=True, timeout=120)
    if r.returncode == 0 and os.path.exists(out):
        print("%s：f0=%.0f 包絡=%s" % (label, f0_fft(out), [int(x) for x in envelope_peaks(out)]))
    else:
        print(label, "失敗", r.stderr.decode("utf-8", "replace")[:150])
