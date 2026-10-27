# -*- coding: utf-8 -*-
"""診斷 NV key 行結構：只顯示行號/變數名/值長度/分隔符形狀，絕不印值。"""
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8")
lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
print("total lines:", len(lines))
for i, l in enumerate(lines, 1):
    if re.search(r'NV', l):
        name = l.split("=", 1)[0].strip() if "=" in l else l.strip()[:40]
        v = l.split("=", 1)[1] if "=" in l else ""
        shape = re.sub(r'[A-Za-z0-9]', 'X', v)
        shape = re.sub(r'X{12,}', lambda m: f"X[{len(m.group(0))}]", shape)
        print(f"L{i}: var={name} rawlen={len(l)} shape={shape[:120]}")
