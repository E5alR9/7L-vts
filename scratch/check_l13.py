# -*- coding: utf-8 -*-
"""看 L10-L16 周邊（只印變數名/形狀）。"""
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8")
lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
for i in range(9, 17):
    l = lines[i]
    if "=" in l:
        name = l.split("=", 1)[0].strip()[:30]
        v = l.split("=", 1)[1]
        print(f"L{i+1}: var={name} vallen={len(v.strip())}")
    else:
        s = l.strip()
        print(f"L{i+1}: (no =) len={len(s)} head={s[:12]} tail={s[-12:]}")
