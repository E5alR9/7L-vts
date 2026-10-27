# -*- coding: utf-8 -*-
"""ListModels 驗屍：2.5 的 404 是名字錯還是真沒開通。抽 5 把 key 列出可用模型。"""
import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from google import genai

keys = [k.strip() for k in re.split(r"[\s,;]+", os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]

WANT = ("2.5-flash", "2.5-flash-lite", "3.5-flash", "3.8-flash", "flash-lite", "live")
for ki in [0, 7, 15, 23, 30]:
    key = keys[ki]
    try:
        cli = genai.Client(api_key=key)
        names = []
        for m in cli.models.list():
            n = getattr(m, "name", "")
            n = n.split("/")[-1]
            names.append(n)
        print(f"--- K{ki} 共 {len(names)} 個模型 ---")
        for w in WANT:
            hit = sorted({n for n in names if w in n})
            print(f"  含[{w}]: {hit if hit else '無'}")
    except Exception as e:
        print(f"--- K{ki} list 失敗: {type(e).__name__}:{str(e)[:80]}")
