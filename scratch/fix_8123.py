import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()
l = lines[8122]
assert "_rescue_claim" in l and "log_print" in l, repr(l[:100])
i = l.find("continue") + len("continue")
lines[8122:8123] = [
    "            if not rescue_claim(song, now):\n",
    "                continue\n",
    "            " + l[i:].strip() + "\n",
]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("fixed")
