# -*- coding: utf-8 -*-
"""7L_v2 上次訓練配置＋資料集盤點（只讀元數據）。"""
import os, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

for d in [r"RVC-WebUI\logs\7L_v2", r"RVC-WebUI\datasets\7L_singing",
          r"RVC-WebUI\assets\weights", r"RVC-WebUI\assets\indices"]:
    print("=" * 60)
    print(d)
    try:
        items = sorted(os.listdir(d))
    except Exception as e:
        print("  ERR", e)
        continue
    for name in items[:25]:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            print(f"  {os.path.getsize(p)//1024:8d}KB {name}")
        else:
            try:
                n = len(os.listdir(p))
            except Exception:
                n = "?"
            print(f"  <dir:{n}> {name}/")
