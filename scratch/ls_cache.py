# -*- coding: utf-8 -*-
import os, sys, glob, time
sys.stdout.reconfigure(encoding="utf-8")
CACHE = r"songs_library\cover_cache"
files = sorted(glob.glob(os.path.join(CACHE, "*.wav")), key=os.path.getmtime)
print(f"total wav: {len(files)}")
for f in files[-14:]:
    st = os.stat(f)
    print(f"{time.strftime('%H:%M', time.localtime(st.st_mtime))} {st.st_size//1024:7d}KB {os.path.basename(f)}")
