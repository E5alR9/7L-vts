import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "tests/test_hard_command.py"
lines = open(p, encoding="utf-8").readlines()
assert lines[170].startswith("def test_japanese_titles_hit"), repr(lines[170][:50])
lines[170:171] = ["def test_japanese_titles_hit():\n",
                  '    """2026-10-10 直播事故：全片假名歌名被判無內容而漏接。"""\n']
open(p, "w", encoding="utf-8", newline="").write("".join(lines))
print("rewrote")
