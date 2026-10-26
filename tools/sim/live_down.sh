#!/bin/bash
# 正常關機（記憶會寫回），並列出這輪日誌裡的錯誤。用法：bash tools/sim/live_down.sh 日誌名
L="${SIM_LOG_DIR:-$TEMP/vtslint}/$1"
curl -s -m 5 -X POST http://127.0.0.1:7860/api/shutdown >/dev/null
for i in $(seq 1 40); do curl -s -m 1 http://127.0.0.1:7860/ -o /dev/null && sleep 1 || { echo "7L 已關閉"; break; }; done
echo "錯誤/警告摘要："
PYTHONIOENCODING=utf-8 python - "$L" <<'PY'
import re, sys, collections
s = open(sys.argv[1], encoding="utf-8", errors="replace").read()
s = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)
c = collections.Counter(); ex = {}
for l in re.split(r"[\r\n]", s):
    l = re.sub(r"^\[[/|\-]\]\s.*?\]\s{2,}", "", l.strip())
    if re.search(r"❌|Traceback|Error|Exception|NameError|AttributeError|吞錯", l) and "通道就緒" not in l:
        k = re.sub(r"\d+(\.\d+)?", "#", l)[:60]; c[k] += 1; ex.setdefault(k, l[:170])
for k, n in c.most_common(12): print(f"  {n:3d} × {ex[k]}")
if not c: print("  （沒有）")
PY
