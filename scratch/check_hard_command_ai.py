# -*- coding: utf-8 -*-
"""檢查 A 架構 task_instruction 形式（Live 主腦下發的指令）不會被句首門擋掉。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.hard_command import parse_hard_command

CASES = [
    "幫老爸唱 Distrion - Alibi (ft. Heleen)",
    "請7L唱 晴天",
    "唱一首晴天",
    "點歌 加州旅館",
    "幫我彈 夢中的婚禮",
    "7L彈 月光",
    "唱 Never Gonna Give You Up",
    "幫老爸點歌 刀醬 dadada",
    "唱晴天",
    "唱 123456",
    "彈 沒離開過",
    # 應該要 MISS 的
    "你可以唱歌了？",
    "? 又我唱了????",
    "他唱歌很好聽",
    "你會唱幾首？",
    "唱一首歌",
    "別唱了",
    "他彈琴比我還快",
]

bad = []
for t in CASES:
    tool, args = parse_hard_command(t)
    print(f"{'HIT ' if tool else 'MISS'} {tool or '':22} {args} <= {t}")

# 預期
EXPECT_HIT = CASES[:11]
EXPECT_MISS = CASES[11:]
for t in EXPECT_HIT:
    if parse_hard_command(t)[0] is None:
        bad.append(("漏判", t))
for t in EXPECT_MISS:
    if parse_hard_command(t)[0] is not None:
        bad.append(("誤觸", t))
print("\nRESULT:", "ALL OK" if not bad else bad)
