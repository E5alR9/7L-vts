# -*- coding: utf-8 -*-
import os, sys, glob, time
sys.stdout.reconfigure(encoding="utf-8")
CACHE = r"songs_library\cover_cache"
files = sorted(glob.glob(os.path.join(CACHE, "*.wav")), key=os.path.getmtime)
for f in files:
    base = os.path.basename(f)
    if "綠色" in base or "sandwich" in base or "mid" in base or "tmp" in base:
        st = os.stat(f)
        print(f"{time.strftime('%H:%M', time.localtime(st.st_mtime))} {st.st_size//1024:7d}KB {base}")
print("---- all files count:", len(files))
