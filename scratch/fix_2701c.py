import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
a, b = lines[2700], lines[2701]
assert a.strip() == '"""', repr(a)
assert '"""' in b and "for _ in range" in b, repr(b[:80])
j = b.find('"""') + 3
doc = '    """' + b[:j].strip().strip('"').strip() + '"""\n'
rest = "    " + b[j:].strip() + "\n"
lines[2700:2702] = [doc, rest]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("fixed")
