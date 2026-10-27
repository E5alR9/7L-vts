# -*- coding: utf-8 -*-
"""看其他家 API key 的排列形狀（只印形狀，不印值）。"""
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8")
lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
for i, l in enumerate(lines, 1):
    if re.match(r'\s*(GROQ_API_KEYS|GEMINI_API_KEY|TAVILY_KEYS|ELEVENLABS_API_KEY|NV_API_KEYS)\s*=', l):
        name = l.split("=", 1)[0].strip()
        v = l.split("=", 1)[1]
        shape = re.sub(r'[A-Za-z0-9]', 'X', v)
        shape = re.sub(r'X{16,}', lambda m: f"X[{len(m.group(0))}]", shape)
        print(f"L{i}: {name} shape={shape[:100]}")
    elif re.match(r'\s*GEMINI_KEYS?\d*\s*=', l):
        name = l.split("=", 1)[0].strip()
        print(f"L{i}: {name} (len={len(l)})")
