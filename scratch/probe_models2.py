# -*- coding: utf-8 -*-
"""第二輪：3.5-3.8-flash 用更好的探針重測（5把key抽樣）。
第一輪 EMPTY 可能是 thinking 模型（正文在 thought parts，不在 text），
503 可能是瞬時超載（重試一次）。只測這4個，有一個字就算活。"""
import io, json, os, re, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from google import genai
from google.genai import types

keys = [k.strip() for k in re.split(r"[\s,;]+", os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip()]
sample = [0, 7, 15, 23, 30]
MODELS = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]
SAFE = [types.SafetySetting(category=c, threshold="BLOCK_NONE")
        for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                  "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
                  "HARM_CATEGORY_CIVIC_INTEGRITY")]


def probe(cli, model):
    """回 (ok, 證據)。正文/thought/任何part有字就算活。"""
    for attempt in range(2):
        try:
            r = cli.models.generate_content(
                model=model, contents="Reply with the word OK",
                config=types.GenerateContentConfig(
                    temperature=0.0, max_output_tokens=32,
                    safety_settings=SAFE))
            if (getattr(r, "text", "") or "").strip():
                return True, f"text:{r.text.strip()[:20]}"
            try:
                parts = r.candidates[0].content.parts or []
            except Exception:
                parts = []
            for p in parts:
                t = (getattr(p, "text", "") or "").strip()
                if t:
                    kind = "thought" if getattr(p, "thought", False) else "part"
                    return True, f"{kind}:{t[:20]}"
            return False, "empty-text-and-parts"
        except Exception as e:
            err = str(e)
            if ("503" in err or "UNAVAILABLE" in err) and attempt == 0:
                time.sleep(3)
                continue
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                return False, "429"
            if "404" in err or "NOT_FOUND" in err:
                return False, "404"
            return False, type(e).__name__ + ":" + err[:50]
    return False, "unreachable"


out = {}
for ki in sample:
    key = keys[ki]
    cli = genai.Client(api_key=key)
    for m in MODELS:
        ok, ev = probe(cli, m)
        out.setdefault(m, []).append(ok)
        print(f"  K{ki} {m}: {'OK' if ok else 'dead'} ({ev})", flush=True)
        time.sleep(1.0)

print("=== VERDICT ===")
for m in MODELS:
    n = sum(out[m])
    print(f"  {m}: {n}/{len(sample)} alive")
json.dump(out, open("scratch/probe_models_round2.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
