import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "services/auto_cover_pipeline.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[207]
print("line208:", ascii(l[:60]))
assert l.lstrip().startswith('"""') and "global " in l, repr(l[:80])
i = l.find('"""') + 3
j = l.find('"""', i) + 3
doc = "    " + l[i:j].strip().strip('"').strip() + '"""\n'
doc = '    """' + l[i:j].strip().lstrip('"').rstrip('"') + '"""\n'
tail = "    " + l[j:].strip() + "\n"
lines[207:208] = [doc, tail]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("done")
