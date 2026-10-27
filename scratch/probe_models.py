# -*- coding: utf-8 -*-
"""全 key × 全候選模型實測（2026-10-11）：按 Google 免費配額表，只測非零項目。
每個 (key, model) 只打 1 發極小請求；key 只顯示後6碼。
結果寫 scratch/probe_models_result.json。跑完前不要動 GEMINI_MODELS。"""
import io, json, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

import re
from google import genai
from google.genai import types

keys = [k.strip() for k in re.split(r"[\s,;]+", os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]
print(f"keys: {len(keys)}")

# 配額表非零 = 可能能用（TTS/圖/embedding 不列，腦子用不到）
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

out = {"models": MODELS, "n_keys": len(keys), "ok": {m: 0 for m in MODELS},
       "fail": {m: [] for m in MODELS}, "per_key_ok": {}}
for ki, key in enumerate(keys):
    tag = f"K{ki}(...{key[-6:]})"
    oks = []
    for m in MODELS:
        try:
            cli = genai.Client(api_key=key)
            r = cli.models.generate_content(
                model=m, contents="hi",
                config=types.GenerateContentConfig(
                    temperature=0.0, max_output_tokens=8,
                    safety_settings=[
                        types.SafetySetting(category=c, threshold="BLOCK_NONE")
                        for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                                  "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")]),
            )
            txt = (getattr(r, "text", "") or "").strip()
            if txt:
                out["ok"][m] += 1
                oks.append(m)
                print(f"  {tag} {m}: OK")
            else:
                out["fail"][m].append(f"{tag}:empty")
                print(f"  {tag} {m}: EMPTY")
        except Exception as e:
            err = str(e)
            short = "429" if ("429" in err or "RESOURCE_EXHAUSTED" in err) else (
                "404" if ("404" in err or "NOT_FOUND" in err or "not found" in err.lower()) else
                type(e).__name__ + ":" + err[:60])
            out["fail"][m].append(f"{tag}:{short}")
            print(f"  {tag} {m}: {short}")
        time.sleep(0.6)  # 同 key 節流，別把 429 誤判成死亡
    out["per_key_ok"][f"K{ki}"] = oks
    time.sleep(0.5)

json.dump(out, open("scratch/probe_models_result.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("=== SUMMARY (ok keys per model) ===")
for m in MODELS:
    print(f"  {m}: {out['ok'][m]}/{len(keys)}")
print("saved scratch/probe_models_result.json")
