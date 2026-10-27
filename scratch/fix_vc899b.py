import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "services/vts_client.py"
lines = open(p, encoding="utf-8").readlines()
assert lines[898].startswith("async def trigger_vts_expression"), repr(lines[898][:50])
assert "-> str:" in lines[899], repr(lines[899][:60])
sig = lines[898].rstrip() + " " + lines[899].split('"""')[0].strip() + "\n"
doc = '    """' + lines[899].split('"""', 1)[1]
if not doc.endswith("\n"):
    doc += "\n"
lines[898:900] = [sig, doc]
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("reconstructed:", repr(sig[:60]))
