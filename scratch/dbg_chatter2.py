import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
import core.hard_command as h
print("module:", h.__file__)
s = "放個大招給你看"
print("len:", len(s))
m = h._TRAIL_CHATTER.search(s)
print("match:", repr(m.group(0)) if m else None, "len:", len(m.group(0)) if m else 0)
r = h._clean_title(s)
print("clean:", ascii(r), "len:", len(r) if r else 0)
t, a = h.parse_hard_command("唱" + s)
print("tool:", t, "song:", ascii((a or {}).get("song_name")), "len:", len((a or {}).get("song_name") or ""))
