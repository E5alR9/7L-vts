import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
for f, a, b in [("7L.py", 43, 58), ("bot.py", 45, 60)]:
    print("==", f)
    for i, l in enumerate(open(f, encoding="utf-8").readlines()[a:b]):
        print(a + i + 1, l.rstrip())
