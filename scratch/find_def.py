import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

lines = open("vts_7L_test.py", encoding="utf-8").readlines()
for target in (1118, 1358):
    print(f"=== {target} 附近的 def ===")
    for i in range(max(0, target - 300), target):
        if re.match(r"(async )?def \w+", lines[i].lstrip()):
            print(i + 1, lines[i].strip()[:70])
