import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "services/auto_cover_pipeline.py"
lines = open(p, encoding="utf-8").readlines()
for idx, l in enumerate(lines):
    if l.startswith("def stop_singing") and '"""' in l and "global " in l:
        print("glued at 1-based line:", idx + 1)
        i = l.find("):") + 2
        head = l[:i] + "\n"
        rest = l[i:].strip()
        j = rest.find('"""') + 3
        doc = "    " + rest[:j] + "\n"
        tail = rest[j:].strip()
        lines[idx:idx + 1] = [head, doc] + (["    " + tail + "\n"] if tail else [])
        break
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("done")
