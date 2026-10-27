# -*- coding: utf-8 -*-
"""全曲庫分離人聲量音域，挑一首高的做 RVC 實測。"""
import sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.rvc_pitch import analyze_vocal_range, decide_sandwich_octave

CACHE = r"songs_library\cover_cache"
files = sorted(glob.glob(os.path.join(CACHE, "*_vocals.wav")), key=os.path.getmtime)
for f in files:
    med, p90, vs = analyze_vocal_range(f)
    med_s = f"{med:.0f}" if med else "-"
    p90_s = f"{p90:.0f}" if p90 else "-"
    sw = "SANDWICH" if decide_sandwich_octave(med, p90) else "-"
    print(f"{med_s:>5} {p90_s:>5} {vs:5.0f}s {sw:8} {os.path.basename(f)}")
