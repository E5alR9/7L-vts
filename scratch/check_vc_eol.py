import io, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def blob(rev, path):
    d = subprocess.run(["git", "show", f"{rev}:{path}"],
                       capture_output=True).stdout
    crlf = d.count(b"\r\n")
    lf = d.count(b"\n") - crlf
    return len(d.split(b"\n")), crlf, lf

for rev in ["HEAD~1", "HEAD"]:
    n, crlf, lf = blob(rev, "services/vts_client.py")
    print(f"{rev} vts_client: {n}行 CRLF={crlf} LF-only={lf}")
wt = open("services/vts_client.py", "rb").read()
print(f"worktree vts_client: CRLF={wt.count(bytes([13,10]))}")
