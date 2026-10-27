import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[945]
i = l.find(" else f")
assert i > 0, "pattern not found"
body = l[i + 8:]
print("has-brace:", ("{" in body))
if ("{" not in body):
    lines[945] = l[: i + 6] + l[i + 7:]
    open(p, "w", encoding="utf-8", newline="").write("".join(lines))
    print("fixed")
