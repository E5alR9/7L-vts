# -*- coding: utf-8 -*-
"""把 NV_API_KEYS 的裸換行三把併成單行空白分隔。絕不印出任何 key 值。"""
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8")

p = ".env"
raw = io.open(p, encoding="utf-8", errors="replace").read().splitlines(keepends=True)

idx = next(i for i, l in enumerate(raw) if re.match(r"\s*NV_API_KEYS\s*=", l))
eol = "\r\n" if raw[idx].endswith("\r\n") else "\n"
l76 = raw[idx].strip()
m = re.match(r"NV_API_KEYS\s*=\s*(\S+)\s*$", l76)
assert m, "L76 shape unexpected, abort"
keys = [m.group(1).strip('"').strip("'")]

for j in (idx + 1, idx + 2):
    s = raw[j].strip()
    assert re.fullmatch(r"nvapi-[A-Za-z0-9_\-]+", s) and len(s) >= 60, \
        f"line {j + 1} is not a bare nvapi key, abort"
    keys.append(s)

assert len({len(k) for k in keys}) <= 3  # 只是 sanity，不印值
comment = "# 注意：多把 key 請用空白隔開寫在同一行（換行會被 dotenv 當廢行丟掉）" + eol
new_lines = (raw[:idx] + [comment]
             + [f"NV_API_KEYS={' '.join(keys)}" + eol]
             + raw[idx + 3:])
io.open(p, "w", encoding="utf-8", newline="").writelines(new_lines)

# 驗收：重跑 vts 同款解析（只數數量與長度）
import re as _re
text = io.open(p, encoding="utf-8", errors="replace").read()
mv = _re.search(r"NV_API_KEYS\s*=\s*(.+)", text)
parts = [x for x in _re.split(r"[\s,;]+", mv.group(1).strip()) if x.strip()]
print("parsed keys:", len(parts), "lens:", sorted(len(x) for x in parts))
assert len(parts) == 3, "NOT 3 after merge!"
print("MERGE OK")
