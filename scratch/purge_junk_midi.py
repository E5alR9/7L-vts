import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

JUNK_KEY = re.compile(r"加唱|混用|邊彈邊唱")
removed_files, removed_keys = [], []

for f in os.listdir("midi_sheets"):
    if f.endswith((".mid", ".midi")) and JUNK_KEY.search(f):
        os.remove(os.path.join("midi_sheets", f))
        removed_files.append(f)

cp = "midi_sheets/midi_catalog.json"
d = json.load(open(cp, encoding="utf-8"))
for k in [k for k in d.keys() if JUNK_KEY.search(k)]:
    # 只刪指向已刪檔案的條目；指向正常檔的保留（別名也許有用）
    v = str(d[k])
    if not os.path.exists(v) or JUNK_KEY.search(os.path.basename(v)):
        del d[k]
        removed_keys.append(k)
json.dump(d, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("removed files:", removed_files)
print("removed keys:", removed_keys)
print("catalog now:", len(d))
