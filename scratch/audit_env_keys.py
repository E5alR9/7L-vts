# -*- coding: utf-8 -*-
"""只印 .env 的鍵名與金鑰『數量』，絕不印值。多行值（逗號延續行）會合併計算。"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
raw = open(r"C:\Users\qiwai\.env", encoding="utf-8", errors="replace").read()

keys, cur = {}, None
for line in raw.split("\n"):
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", s)
    if m:
        cur = m.group(1)
        keys[cur] = m.group(2)
    elif cur:
        keys[cur] += "," + s

print("唯一鍵數:", len(keys))
print("鍵名:", ", ".join(sorted(keys)))
print()
for k in sorted(keys):
    if "KEY" in k or "TOKEN" in k:
        if "PRIVATE KEY" in keys[k]:
            tag = "內嵌 service-account JSON（含私鑰明文）"
        else:
            n = len([x for x in re.split(r"[\s,;]+", keys[k]) if x.strip()])
            tag = f"{n} 把"
        print(f"  {k}: {tag}")
