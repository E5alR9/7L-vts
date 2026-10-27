# -*- coding: utf-8 -*-
"""檢查 NV 金鑰配置存在性（只印數量與長度，絕不印值）。"""
import io, re
lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
found = [l for l in lines if re.match(r'\s*NV_API_KEYS?\s*=', l)]
print("NV_API_KEYS entries:", len(found))
for l in found:
    v = l.split("=", 1)[1].strip().strip('"').strip("'")
    parts = [p for p in re.split(r'[\s,;]+', v) if p.strip()]
    print(f"  keys: {len(parts)}, lens: {[len(p) for p in parts]}")
