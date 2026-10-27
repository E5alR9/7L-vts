import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[2711]
i = l.find('):')
assert i > 0
head, tail = l[: i + 2] + "\n", "    " + l[i + 2:].lstrip() + ("\n" if not l.endswith("\n") else "")
tail = "    " + l[i + 2:].strip() + "\n"
lines[2711:2712] = [head, tail]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("split ok:", repr(lines[2711][:40]), "|", repr(lines[2712][:20]))
