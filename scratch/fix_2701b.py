import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[2700]
assert l.lstrip().startswith('"""') and "for _ in range" in l, repr(l[:60])
i = l.find('"""', 3) + 3
doc = "    " + l[:i].strip() + "\n"
rest = "    " + l[i:].strip() + "\n"
lines[2700:2701] = [doc, rest]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("fixed")
