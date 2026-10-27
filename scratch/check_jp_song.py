import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
from core.hard_command import parse_hard_command

cases = [
    # (輸入, 期望工具, 期望歌名)
    ("唱 インフェルノシティ", "auto_sing_song", "インフェルノシティ"),  # 本次事故
    ("唱 ロンリーユニバース", "auto_sing_song", "ロンリーユニバース"),
    ("唱 幽霊東京", "auto_sing_song", "幽霊東京"),  # 漢字+假名混合
    ("唱pretender", "auto_sing_song", "pretender"),  # 無空格英文
    ("唱 First Love", "auto_sing_song", "First Love"),
    ("弾いて 残酷な天使のテーゼ", None, None),  # 日文動詞不是中文關鍵字→放行（主腦處理）
    ("唱", None, None),
    ("唱 歌", None, None),  # 泛指不攔
    ("唱 123", "auto_sing_song", "123"),
]
bad = 0
for text, tool, song in cases:
    t, a = parse_hard_command(text)
    got = a.get("song_name") if a else None
    ok = (t == tool and got == song)
    bad += not ok
    print(("OK " if ok else "FAIL"), repr(text), "->", t, repr(got))
print("ALL OK" if not bad else f"{bad} FAIL")
