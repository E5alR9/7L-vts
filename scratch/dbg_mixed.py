import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

import pytest
from core.hard_command import parse_mixed_command

for t in ["彈歌加唱舞", "唱放個大招給你看", "唱晴天聽聽看"]:
    try:
        print(repr(t), "->", parse_mixed_command(t))
    except Exception as e:
        print(repr(t), "RAISE", e)
