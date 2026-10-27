import io, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def blob_eol(rev, path):
    d = subprocess.run(["git", "show", f"{rev}:{path}"],
                       capture_output=True).stdout
    crlf = d.count(b"\r\n")
    return crlf, d.count(b"\n") - crlf

def wt_eol(path):
    d = open(path, "rb").read()
    crlf = d.count(b"\r\n")
    return crlf, d.count(b"\n") - crlf

for p in ["vts_7L_test.py", "services/auto_cover_pipeline.py",
          "tests/test_sing_queue.py", "tests/test_hard_command.py",
          "core/hard_command.py"]:
    h = blob_eol("HEAD", p)
    w = wt_eol(p)
    hist = "CRLF" if h[0] > 0 else "LF"
    now = "CRLF" if w[0] > 0 else "LF"
    print(f"{p}: HEAD={hist} work={now} {'OK' if hist == now else '<<< MISMATCH'}")
