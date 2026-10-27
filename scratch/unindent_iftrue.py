import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
lines = open(p, encoding="utf-8").readlines()

# B1a: 7842 if True (console 分支），體 7843-7864，整體退 4 格
assert lines[7841].strip() == "if True:", repr(lines[7841])
assert "req_start = request_start_time" in lines[7865], repr(lines[7865])
body = lines[7842:7864]
for b in body:
    if b.strip():
        assert b.startswith(" " * 12), repr(b[:40])
newbody = [(b[4:] if b.strip() else b) for b in body]
lines[7841:7864] = newbody
print("B1a done")

# B1b: 5808 if True（單行 put），退 4 格
assert lines[5807].strip() == "if True:", repr(lines[5807])
assert "LIVE_API_SYSTEM_PROMPT_QUEUE.put_nowait" in lines[5808], repr(lines[5808])
lines[5807:5809] = [lines[5808][4:]]
print("B1b done")

open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("written")
