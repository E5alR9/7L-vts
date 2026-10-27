import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[2569]
assert "等翻唱超時" in l and l.lstrip().startswith('log_print(f"'), repr(l[:50])
lines[2569] = l.replace('log_print(f"', 'log_print("', 1)
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("fixed")
