import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
assert "rescue_claim" in lines[8121], repr(lines[8121][:60])
l = lines[8122]
assert l.strip().startswith("continue") and "log_print" in l, repr(l[:80])
i = l.find("continue") + len("continue")
rest = l[i:].strip()
lines[8121:8123] = [
    "            if not rescue_claim(song, now):\n",
    "                continue\n",
    "            " + rest + "\n",
]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("fixed")
