import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
for idx, l in enumerate(lines):
    if '"""' in l and "for _ in range" in l and idx > 0 and lines[idx - 1].startswith("async def "):
        print("glued at 1-based line:", idx + 1)
        i = l.find("):")
        head = l[: i + 2] + "\n"
        rest = l[i + 2:].strip()
        j = rest.find('"""') + 3
        doc = "    " + rest[:j] + "\n"
        tail = rest[j:].strip()
        new = [head, doc] + (["    " + tail + "\n"] if tail else [])
        lines[idx:idx + 1] = new
        print("fixed, new lines:", len(new))
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("done")
