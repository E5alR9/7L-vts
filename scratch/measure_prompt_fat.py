import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

def fsz(p):
    return len(open(p, encoding="utf-8").read())

print("== prompts/*.md ==")
for fn in sorted(os.listdir("prompts")):
    if fn.endswith(".md"):
        print(f"  {fn}: {fsz(os.path.join('prompts', fn))}字")

print("== data/7l_persona.json ==")
d = json.load(open("data/7l_persona.json", encoding="utf-8"))
print(f"  hard_rules: {len(d['hard_technical_rules'])}字, fewshot: {len(d['few_shot_examples'])}條 "
      f"({sum(len(e.get('reply','')) for e in d['few_shot_examples'])}字reply)")

print("== cloud local (vtuber) ==")
c = json.load(open("data/cloud_knowledge_local_vtuber.json", encoding="utf-8"))
for k in ("persona_core", "conversation_style", "streamer_bio", "proactive_guide"):
    print(f"  {k}: {len(str(c.get(k, '')))}字")
for k in ("memes_and_slang", "learned_facts", "custom_rules", "banned_phrases", "few_shot_examples"):
    v = c.get(k, [])
    n = len(v)
    ch = sum(len(str(x)) for x in v)
    print(f"  {k}: {n}條共{ch}字")

print("== format_cloud_knowledge_prompt 組裝後 ==")
from core.prompts import PromptTemplateEngine as P
kn = dict(c)
out = P.format_cloud_knowledge_prompt(kn, is_tiktok=True)
print(f"  audience版: {len(out)}字")
out2 = P.format_cloud_knowledge_prompt(kn, current_custom_name="老爸")
print(f"  live主腦版: {len(out2)}字")

print("== Live主腦 system_instruction 組裝估算 ==")
p1 = open("prompts/7L_persona.md", encoding="utf-8").read()
p2 = open("prompts/7L_constraints.md", encoding="utf-8").read()
p3 = open("prompts/7L_responses.md", encoding="utf-8").read()
print(f"  三檔: {len(p1)+len(p2)+len(p3)}字 + cloud {len(out2)}字 + hard_rules {len(d['hard_technical_rules'])}字 = {len(p1)+len(p2)+len(p3)+len(out2)+len(d['hard_technical_rules'])}字 (未含6輪記憶)")
