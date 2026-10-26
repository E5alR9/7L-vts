# -*- coding: utf-8 -*-
"""列出 .env 各金鑰的長度與前綴（不印出金鑰本體）。
路徑：專案根目錄的 .env（本檔在 scripts/ 下）。"""
import os

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

with open(ENV_PATH, "r", encoding="utf-8") as f:
    for line in f:
        line_s = line.strip()
        if line_s and not line_s.startswith("#") and "=" in line_s:
            k, v = line_s.split("=", 1)
            v = v.strip().strip('"').strip("'")
            print(f"{k}: len={len(v)}")
            if "," in v:
                sub = [s.strip().strip('"').strip("'") for s in v.split(",") if s.strip()]
                for i, s in enumerate(sub):
                    print(f"  [{i}] prefix={s[:10]} len={len(s)}")
            else:
                print(f"  prefix={v[:10]}")
