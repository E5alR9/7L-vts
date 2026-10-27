# -*- coding: utf-8 -*-
import os, sys, glob, time
sys.stdout.reconfigure(encoding="utf-8")
CACHE = r"songs_library\cover_cache"
files = sorted(glob.glob(os.path.join(CACHE, "*.wav")), key=os.path.getmtime)
for f in files:
    st = os.stat(f)
    print(f"{time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime))} {st.st_size//1024:7d}KB {os.path.basename(f)}")
