# -*- coding: utf-8 -*-
"""印 L76-L79 的形狀（遮罩值）。"""
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8")
lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
for i in (75, 76, 77, 78):
    l = lines[i]
    shape = re.sub(r'[A-Za-z0-9]', 'X', l)
    shape = re.sub(r'X{20,}', lambda m: f"X[{len(m.group(0))}]", shape)
    print(f"L{i+1} len={len(l)} shape={shape[:110]}")
