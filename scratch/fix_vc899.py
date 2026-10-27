import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "services/vts_client.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[898]
j = l.find('"""')
assert j > 0, repr(l[:80])
lines[898:899] = [l[:j].rstrip() + "\n", "    " + l[j:].strip() + "\n"]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("split ok")
