import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

src = open("vts_7L_test.py", encoding="utf-8").read()

# 1. LIVE_API_TOOLS / INTERACTIONS_TOOLS 描述總量
m = re.search(r"LIVE_API_TOOLS\s*=\s*(\[.*?^\])", src, re.S | re.M)
print("LIVE_API_TOOLS block:", len(m.group(1)) if m else "找不到", "字")

# 2. thought dead params：哪些呼叫還帶 thought_char_limit>0
for mm in re.finditer(r"thought_char_limit\s*=\s*(\w+)", src):
    print("thought引用:", mm.group(0), "行號:",
          src[:mm.start()].count("\n") + 1)

# 3. 主腦組裝現況
p1 = open("prompts/7L_persona.md", encoding="utf-8").read()
p2 = open("prompts/7L_constraints.md", encoding="utf-8").read()
p3 = open("prompts/7L_responses.md", encoding="utf-8").read()
print("三檔:", len(p1) + len(p2) + len(p3), "字")

# 4. audience 單條組裝（靜態部分）
a = open("prompts/7L_audience.md", encoding="utf-8").read()
print("audience檔:", len(a), "字")

# 5. f-string無佔位符（新產生的警告數）
n = len(re.findall(r"log_print\(f\"[^\"]*\"\)", src))
print("log_print f-string總數(抽查):", n)
