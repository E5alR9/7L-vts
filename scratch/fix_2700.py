import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[2699]
i = l.find("):")
assert i > 0 and '"""' in l, repr(l[:80])
head = l[: i + 2] + "\n"
tail = "    " + l[i + 2:].strip() + "\n"
lines[2699:2700] = [head, tail]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("split ok")
