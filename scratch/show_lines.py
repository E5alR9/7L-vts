import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
path, nums = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]
lines = open(path, encoding="utf-8").readlines()
for n in nums:
    for i in range(max(0, n - 2), min(len(lines), n + 3)):
        print(f"{i+1}: {lines[i].rstrip()}")
    print("---")
