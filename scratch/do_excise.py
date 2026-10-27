import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = "vts_7L_test.py"
lines = open(path, encoding="utf-8").readlines()
print("orig:", len(lines))

spans = []
for ln in open("scratch/excise_list.txt", encoding="utf-8"):
    s, e, name = ln.split()
    if name == "save_local_audio_clip":
        print("SKIP (alive callers):", name)
        continue
    s, e = int(s), int(e)
    # 往上吞裝飾器（@行）
    while s - 2 >= 0 and re.match(r"^\s*@\w", lines[s - 2]):
        s -= 1
        print("  decorator absorbed for", name)
    # 斷言：起點是 def 行
    assert re.match(r"^(async )?def ", lines[s - 1].lstrip()), (name, lines[s - 1][:60])
    spans.append((s, e, name))

for s, e, name in sorted(spans, reverse=True):
    del lines[s - 1:e]
    print(f"deleted {s}-{e} {name}")

open(path, "w", encoding="utf-8", newline="").write("".join(lines))
print("new:", len(lines))
