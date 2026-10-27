# -*- coding: utf-8 -*-
"""找 NV key 可能的落點：其他變數名、其他 .env 檔、檔案 mtime（只印元數據）。"""
import io, re, sys, os, glob, time
sys.stdout.reconfigure(encoding="utf-8")

print("== .env* files ==")
for f in sorted(glob.glob(".env*")):
    try:
        st = os.stat(f)
        print(f"{f}  size={st.st_size} mtime={time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime))}")
    except Exception as e:
        print(f, "ERR", e)

print("== lines mentioning NV/nvapi/NVIDIA (names only) ==")
lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
for i, l in enumerate(lines, 1):
    if re.search(r'NV|nvapi|NVIDIA|Nvidia', l, re.I):
        name = l.split("=", 1)[0].strip() if "=" in l else l.strip()[:30]
        v = l.split("=", 1)[1] if "=" in l else ""
        print(f"L{i}: var={name} vallen={len(v.strip())}")

print("== lines with 60+ char single tokens (possible pasted keys) ==")
for i, l in enumerate(lines, 1):
    toks = [t for t in re.split(r'[\s,;]+', l) if len(t.strip('"\'')) >= 60]
    if toks:
        name = l.split("=", 1)[0].strip()[:30] if "=" in l else "(no =)"
        print(f"L{i}: var={name} ntoks={len(toks)}")
