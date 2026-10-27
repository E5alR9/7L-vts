import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = "vts_7L_test.py"
flakes = open("scratch/pyflakes_all.txt", encoding="utf-8").read().splitlines()

f_targets = {}   # line -> set(cols)
g_targets = {}   # line -> [names]
for ln in flakes:
    m = re.match(r"vts_7L_test\.py:(\d+):(\d+): (.*)", ln)
    if not m:
        continue
    no, col, msg = int(m.group(1)), int(m.group(2)), m.group(3)
    if msg.startswith("f-string is missing placeholders"):
        f_targets.setdefault(no, set()).add(col)
    m2 = re.match(r"`global (\w+)` is unused", msg)
    if m2:
        g_targets.setdefault(no, []).append(m2.group(1))

lines = open(path, encoding="utf-8").readlines()
nf = ng = 0

for no in sorted(f_targets):
    idx = no - 1
    line = lines[idx]
    for col in sorted(f_targets[no], reverse=True):
        # col 是 f-string 的 1-based 位置；刪掉該 f 前綴
        p = col - 1
        if line[p:p + 2] in ('f"', "f'"):
            # 保險：字串內容不可含單個 {（{{ 轉義也不行，語義會變）
            q = line[p + 1]
            end = line.find(q, p + 2)
            body = line[p + 2:end] if end > 0 else ""
            if "{" not in body:
                line = line[:p] + line[p + 1:]
                nf += 1
            else:
                print(f"SKIP f-string line {no}: 含大括號")
        else:
            print(f"SKIP f-string line {no} col {col}: 對不上")
    lines[idx] = line

for no in sorted(g_targets):
    idx = no - 1
    line = lines[idx]
    m = re.match(r"^(\s*)global\s+(.+?)(\s*(?:#[^\n]*)?\n)$", line)
    if not m:
        print(f"SKIP global line {no}: 格式不認得: {line.strip()[:60]}")
        continue
    indent, names, tail = m.group(1), m.group(2), m.group(3)
    rest = [n.strip() for n in names.split(",") if n.strip() not in g_targets[no]]
    ng += len(names.split(",")) - len(rest)
    lines[idx] = f"{indent}global {', '.join(rest)}{tail}" if rest else ""
    if not rest:
        print(f"整行刪 global line {no}")

open(path, "w", encoding="utf-8", newline="").write("".join(lines))
print(f"f-string 修 {nf} 處，global 清 {ng} 個")
