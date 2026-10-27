import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "services/piano_engine.py"
lines = open(p, encoding="utf-8").readlines()
for idx, l in enumerate(lines):
    if l.startswith("def is_midi_playable") and '"""' in l:
        print("glued at 1-based line:", idx + 1)
        # def 行 + 後續行拼到 docstring 結尾 """ 為止
        buf = l
        j = idx
        while buf.count('"""') < 2 and j + 1 < len(lines):
            j += 1
            buf += lines[j]
        # buf = "def ... -> bool:    \"\"\"doc...\"\"\"" (+ maybe trailing code?)
        sig_end = buf.find("-> bool:") + len("-> bool:")
        head = buf[:sig_end] + "\n"
        rest = buf[sig_end:].strip()
        assert rest.startswith('"""'), repr(rest[:40])
        close = rest.find('"""', 3) + 3
        doc = "    " + rest[:close] + "\n"
        tail = rest[close:].strip()
        new = [head, doc] + (["    " + tail + "\n"] if tail else [])
        lines[idx:j + 1] = new
        print("new lines:", len(new), "tail:", repr(tail[:40]))
        break
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("done")
