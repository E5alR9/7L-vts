import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "web/dashboard.js"
lines = open(p, encoding="utf-8").readlines()
for idx, l in enumerate(lines):
    if l.startswith("  loadConversationHistory(memories) {") and "if (!memories" in l:
        head, rest = l.split("{", 1)
        lines[idx:idx + 1] = [head + "{\n", "    " + rest.lstrip()]
        print("fixed line", idx + 1)
        break
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("done")
