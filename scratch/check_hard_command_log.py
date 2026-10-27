# -*- coding: utf-8 -*-
"""把 2026-10-09 直播 log 的真實句子倒回 CPU 拆解，確認不再誤觸。"""
import sys, io, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.hard_command import parse_hard_command

REAL = [
    # (句子, 預期是否命中)
    ("唱 Distrion - Alibi (ft. Heleen)", True),
    ("你可以唱歌了？", False),
    ("? 又我唱了????", False),
    ("送出了 1 個 Treasure Clover！請向他熱情道謝並給予即時互動！", False),
    ("你可以唱歌了？", False),
    ("幫我唱 晴天", True),
    ("點歌 晴天", True),
    ("彈一首 夢中的婚禮", True),
]

bad = 0
for text, want in REAL:
    tool, args = parse_hard_command(text)
    got = tool is not None
    flag = "OK " if got == want else "BAD"
    if got != want:
        bad += 1
    print(f"{flag} want={'HIT' if want else 'MISS'} got={'HIT' if want == got else ''}"
          f"{'MISS' if got == want else ''} tool={tool} args={args} <= {text}")

print("RESULT:", "ALL OK" if bad == 0 else f"{bad} MISMATCH")
