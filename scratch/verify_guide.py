import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
from core.prompts import PromptTemplateEngine as P

# 預設 5 條範例永遠兜底（fallback）→ 有預設在，指南就不必出現（範例本身就是格式教學）
new_kn = {"persona_core": "", "memes_and_slang": [], "few_shot_examples": [],
          "learned_facts": [], "custom_rules": [], "banned_phrases": []}
out = P.format_cloud_knowledge_prompt(dict(new_kn), is_tiktok=True)
print("空knowledge靠預設範例，指南不出現（正確）:", "自我演進指南" not in out)
print("但預設範例有在（格式教學沒丟）:", "神回覆思維示範" in out)

# 已演進（有梗）→ 指南不出現
old_kn = dict(new_kn, memes_and_slang=["test梗"])
out2 = P.format_cloud_knowledge_prompt(old_kn, is_tiktok=True)
print("舊knowledge無指南:", "自我演進指南" not in out2)

# audience 佔位符
raw = open("prompts/7L_audience.md", encoding="utf-8").read()
print("audience:", len(raw), "字")
out3 = raw.format(id_display="X", v_info="Y", v_call_name="Z", v_unique_id="U")
import re
print("殘留佔位符:", re.findall(r"\{[a-z_]+\}", out3))
