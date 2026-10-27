# -*- coding: utf-8 -*-
"""用 python-dotenv 實際載入 .env 副本，看 NV_API_KEYS 解析出幾把（不印值）。"""
import io, os, re, sys, shutil, tempfile
sys.stdout.reconfigure(encoding="utf-8")

tmp = os.path.join(tempfile.gettempdir(), "dotenv_probe.env")
shutil.copyfile(".env", tmp)
for var in ("NV_API_KEYS", "NV_API_KEY"):
    os.environ.pop(var, None)

from dotenv import load_dotenv
load_dotenv(tmp, override=True)
for var in ("NV_API_KEYS", "NV_API_KEY"):
    v = os.getenv(var) or ""
    parts = [p for p in re.split(r"[\s,;]+", v) if p.strip()]
    print(f"{var}: parsed={len(parts)} lens={sorted(len(p) for p in parts)}")
    os.environ.pop(var, None)
os.remove(tmp)
print("PROBE DONE")
