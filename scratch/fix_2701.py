import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[2700]
i = l.find("):")
assert i > 0 and '"""' in l, repr(l[:100])
head = l[: i + 2] + "\n"
tail = "    " + l[i + 2:].strip() + "\n"
# tail 可能是 docstring 結尾另起 for：把 for 切到下一行
if '"""' in tail:
    j = tail.find('"""') + 3
    doc, rest = tail[:j] + "\n", tail[j:].strip()
    lines[2700:2701] = [head, doc] + ([rest + "\n"] if rest else [])
else:
    lines[2700:2701] = [head, tail]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("split ok")
