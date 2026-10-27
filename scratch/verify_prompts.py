import io, json, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

# 1. JSON 合法
d = json.load(open("data/7l_persona.json", encoding="utf-8"))
print("json ok, hard_rules_len:", len(d["hard_technical_rules"]))

# 2. 佔位符代入（走 load_prompt 同款邏輯）
sys.path.insert(0, os.getcwd())
fails = []
for fn, kw in [("7L_persona.md", dict(char_name="7L", owner="老爸")),
               ("7L_constraints.md", dict(char_name="7L", owner="老爸")),
               ("7L_responses.md", dict(char_name="7L", owner="老爸",
                                       expression_menu="被誇/撒嬌→愛心")),
               ("7L_audience.md", dict(id_display="X", v_info="Y", v_call_name="Z"))]:
    raw = open(os.path.join("prompts", fn), encoding="utf-8").read()
    try:
        out = raw.format(**kw)
    except (KeyError, IndexError, ValueError) as e:
        fails.append((fn, repr(e)))
        continue
    left = re.findall(r"\{[a-z_]+\}", out)
    print(f"{fn}: {len(out)}字, 殘留佔位符={left}")
print("format fails:", fails)

# 3. few-shot 表情全在新選單內
menu = ("愛心,比心,星星眼,臉紅,哭哭,笑,開心,生氣,黑臉,黑化,暈,流汗,著急,"
        "吐舌,花花,問號,震驚,翻白眼,皺眉,抬手,雙馬尾,WINK,正常,微笑")
bad = []
for ex in d.get("few_shot_examples", []):
    for m in re.findall(r"\[EXPRESSION:\s*([^\]]+)\]", ex.get("reply", "")):
        if m.strip() not in menu.split(","):
            bad.append((ex.get("scenario"), m))
print("few-shot 非選單表情:", bad if bad else "無")

# 4. 三檔＋hard_rules 總字數
tot = 0
for fn in ("7L_persona.md", "7L_constraints.md", "7L_responses.md"):
    tot += len(open(os.path.join("prompts", fn), encoding="utf-8").read())
print(f"三檔合計 {tot} 字 + hard_rules {len(d['hard_technical_rules'])} 字")
