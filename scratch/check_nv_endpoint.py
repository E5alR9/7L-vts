# -*- coding: utf-8 -*-
"""驗證 NV endpoint/model（只打 /v1/models 列表，不做推理、零配額消耗）。
絕不印出金鑰。"""
import io, re, sys, json, urllib.request
sys.stdout.reconfigure(encoding="utf-8")

lines = io.open('.env', encoding='utf-8', errors='replace').read().splitlines()
key = ""
for l in lines:
    if re.match(r'\s*NV_API_KEYS?\s*=', l):
        v = l.split("=", 1)[1].strip().strip('"').strip("'")
        parts = [p for p in re.split(r'[\s,;]+', v) if p.strip()]
        if parts:
            key = parts[0]
if not key:
    print("NO NV KEY FOUND")
    raise SystemExit(1)

req = urllib.request.Request("https://integrate.api.nvidia.com/v1/models")
# 完整 header（只在記憶體組裝，絕不印出）
req.add_header("Authorization", "Bearer " + key)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
except Exception as e:
    print("ENDPOINT FAIL:", str(e)[:200])
    raise SystemExit(2)

models = [m.get("id", "") for m in data.get("data", [])]
print(f"endpoint OK, models listed: {len(models)}")
want = "nvidia/nemotron-3-super-120b-a12b"
hits = [m for m in models if "nemotron-3-super" in m]
print("nemotron-3-super family:", hits if hits else "NOT LISTED")
print("exact want present:", want in models)
