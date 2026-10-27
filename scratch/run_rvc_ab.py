# -*- coding: utf-8 -*-
"""RVC 實測：同段高音，直轉 vs 三明治，量測對打（f0正確性/削波/平坦度/頻譜傾斜）。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundfile as sf
import librosa

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rvc_test")
SEG = os.path.join(D, "seg.wav")
MP = r"C:\Users\qiwai\RVC-WebUI\assets\weights\7L_v2.pth"
IX = r"C:\Users\qiwai\RVC-WebUI\assets\indices\7L_v2_added_IVF256_Flat_nprobe_1_7L_v2_v2.index"

t0 = time.time()
from services.neural_voice_converter import convert_vocal_to_xiaoyi
from services.auto_cover_pipeline import pitch_shift_vocal_to_female
print(f"imports: {time.time()-t0:.0f}s")

# A 路：直轉（現行高音行為，uniform 0）
t0 = time.time()
ok_a = convert_vocal_to_xiaoyi(SEG, os.path.join(D, "out_direct.wav"),
                               key=0.0, model_pth=MP, index_file=IX,
                               index_rate=0.88, auto_pitch=True)
print(f"direct RVC: ok={ok_a} {time.time()-t0:.0f}s")

# B 路：三明治全流程（分析→前降→RVC→回拉）
t0 = time.time()
ok_b = pitch_shift_vocal_to_female(SEG, os.path.join(D, "out_sandwich.wav"), 0.0, True)
print(f"sandwich full: ok={ok_b} {time.time()-t0:.0f}s")


def measure(path, label):
    y, sr = librosa.load(path, sr=16000, mono=True)
    f0 = librosa.yin(y, fmin=50, fmax=800, sr=16000)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    n = min(len(f0), len(rms))
    f0, rms = f0[:n], rms[:n]
    gate = max(float(np.max(rms)) * 0.05, 1e-4)
    vv = f0[(rms > gate) & np.isfinite(f0) & (f0 > 50)]
    med = float(np.median(vv)) if len(vv) else 0.0
    yf, _ = sf.read(path, always_2d=True)
    peak = float(np.max(np.abs(yf)))
    nclip = int(np.sum(np.abs(yf) >= 0.999))
    flat = librosa.feature.spectral_flatness(y=y)
    fl = float(np.median(flat[0, :n][(rms > gate)])) if n else 0.0
    S = np.abs(librosa.stft(y, n_fft=4096))
    fr = librosa.fft_frequencies(sr=16000, n_fft=4096)
    hi = float(S[(fr >= 3000)].mean())
    lo = float(S[(fr < 3000)].mean())
    print(f"[{label}] f0med={med:.0f} peak={peak:.3f} clips={nclip} flat={fl:.4f} hi/lo={hi/max(lo,1e-9):.3f}")
    return med


print("--- input ---")
mi = measure(SEG, "input ")
print("--- outputs ---")
ma = measure(os.path.join(D, "out_direct.wav"), "direct") if ok_a else None
mb = measure(os.path.join(D, "out_sandwich.wav"), "sandw") if ok_b else None
print(f"f0 ratio direct/in={ma/mi:.2f} sandw/in={mb/mi:.2f}" if ma and mb else "INCOMPLETE")
print("DONE")
