import io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

files = ["data/7l_persona.json", "data/cloud_knowledge_local.json",
         "data/cloud_knowledge_local_companion.json",
         "data/cloud_knowledge_local_vtuber.json"]
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    exs = d.get("few_shot_examples", [])
    n_th = sum(1 for e in exs if "thought" in e)
    for e in exs:
        e.pop("thought", None)
    memes = d.get("memes_and_slang", [])
    d["memes_and_slang"] = memes[:10]
    json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{f}: 去thought×{n_th}, memes {len(memes)}→{len(d['memes_and_slang'])}")

# 驗證：全檔無 thought 鍵、memes ≤10
for f in files:
    raw = open(f, encoding="utf-8").read()
    assert '"thought"' not in raw, f
    d = json.loads(raw)
    assert len(d.get("memes_and_slang", [])) <= 10, f
print("verify ok")
