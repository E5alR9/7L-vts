# -*- coding: utf-8 -*-
"""逐把驗 NV key（/v1/models 免費列表，零推理配額）。只印第幾把＋結果，絕不印值。"""
import io, os, re, sys, json, shutil, tempfile, urllib.request
sys.stdout.reconfigure(encoding="utf-8")

tmp = os.path.join(tempfile.gettempdir(), "dotenv_probe2.env")
shutil.copyfile(".env", tmp)
os.environ.pop("NV_API_KEYS", None)
os.environ.pop("NV_API_KEY", None)
from dotenv import load_dotenv
load_dotenv(tmp, override=True)
v = os.getenv("NV_API_KEYS") or ""
keys = [p for p in re.split(r"[\s,;]+", v) if p.strip()]
os.environ.pop("NV_API_KEYS", None)
os.remove(tmp)

print("keys loaded:", len(keys))
want = "nvidia/nemotron-3-super-120b-a12b"
for i, k in enumerate(keys, 1):
    req = urllib.request.Request("https://integrate.api.nvidia.com/v1/models")
    req.add_header("Authorization", "Bearer " + k)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            models = [m.get("id", "") for m in json.loads(r.read().decode("utf-8", "replace")).get("data", [])]
        print(f"key#{i}: OK ({len(models)} models), want-present={want in models}")
    except Exception as e:
        print(f"key#{i}: FAIL {str(e)[:120]}")
