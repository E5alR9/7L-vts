# -*- coding: utf-8 -*-
"""驗證本能 prompt 內每個標籤都能被 worker 路由 + VTS_EXPRESSION_MAP 解析。"""
import sys, io, re
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, r"C:\Users\qiwai")
from services.vts_client import VTS_EXPRESSION_MAP

EXP_TAGS = ["臉紅", "害羞", "傲嬌", "開心", "星星眼", "期待", "生氣", "不爽",
            "哭哭", "難過", "黑化", "暈", "流汗", "無語", "著急", "吐舌",
            "比心", "花花", "問號", "麥克風", "打遊戲", "雙馬尾", "打招呼",
            "左抬手", "WINK", "震驚", "皺眉", "翻白眼"]
MOVE_TAGS = ["靠近", "遠離", "躲角落", "原位", "中間", "左邊", "右邊", "鋼琴旁"]

# worker 內的路由（vts_7L_test.py:5370-5377 原樣照抄）
def route_exp(tag):
    if any(k in tag.upper() for k in ["WINK", "眨眼", "單眼", "眨單眼"]):
        return "timer:trigger_wink"
    elif any(k in tag for k in ["驚訝", "惊", "震驚", "SHOCK"]):
        return "timer:trigger_shock"
    elif any(k in tag for k in ["皺眉", "困擾", "委屈", "FROWN"]):
        return "timer:trigger_frown"
    return "generic:trigger_vts_expression"


def resolve_map(t):
    t = t.strip().lower()
    found = VTS_EXPRESSION_MAP.get(t)
    if not found:
        for k, v in VTS_EXPRESSION_MAP.items():
            if k in t or t in k:
                found = v
                break
    return found


bad = []
covered_files = set()
for tag in EXP_TAGS:
    r = route_exp(tag)
    if r.startswith("timer"):
        print(f"OK   {tag:6} -> {r}")
    else:
        f = resolve_map(tag)
        status = "OK  " if f else "MISS"
        if not f:
            bad.append(tag)
        else:
            covered_files.add(f)
        print(f"{status} {tag:6} -> {r} => {f}")

# 全 19 檔是否都被覆蓋
all_files = set(VTS_EXPRESSION_MAP.values())
print(f"\n覆蓋檔數: {len(covered_files)}/{len(all_files)}")
missing = all_files - covered_files
if missing:
    print("未覆蓋:", missing)
    bad.append(f"files:{missing}")

# 走位：下游認得的關鍵字（move_vts_spatial 分支）
MOVE_KNOWN = ["鋼琴", "靠近", "貼近", "遠離", "躲角落", "角落", "hide",
              "中間", "正中間", "左邊", "左側", "left", "右邊", "右側",
              "right", "原位", "回到原位", "原本位置", "復原", "home", "reset"]
for tag in MOVE_TAGS:
    ok = any(k in tag or tag in k for k in MOVE_KNOWN)
    print(f"{'OK  ' if ok else 'MISS'} [MOVE: {tag}]")
    if not ok:
        bad.append(f"move:{tag}")

print("\nRESULT:", "ALL OK" if not bad else bad)
