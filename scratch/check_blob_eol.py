import io, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def blob(rev):
    d = subprocess.run(["git", "show", f"{rev}:vts_7L_test.py"],
                       capture_output=True).stdout
    crlf = d.count(b"\r\n")
    lf = d.count(b"\n") - crlf
    return len(d.split(b"\n")), crlf, lf

for rev in ["62e247ea3", "HEAD", "e01cc8420"]:
    n, crlf, lf = blob(rev)
    print(f"{rev}: {n}行 CRLF={crlf} LF-only={lf}")
wt = open("vts_7L_test.py", "rb").read()
print(f"worktree: {len(wt.split(chr(10).encode()))}行 CRLF={wt.count(bytes([13,10]))}")
