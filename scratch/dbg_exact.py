import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
import core.hard_command as h
print("module:", h.__file__)
s = "唱放個大招給你看看吧"
print("in len:", len(s), ascii(s))
t, a = h.parse_hard_command(s)
print("tool:", t, "song:", ascii((a or {}).get("song_name")))
