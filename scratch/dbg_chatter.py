import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
import core.hard_command as h
print("chatter pat:", h._TRAIL_CHATTER.pattern)
print("sub:", repr(h._TRAIL_CHATTER.sub("", "放個大招給你看")))
print("clean:", repr(h._clean_title("放個大招給你看")))
print("parse:", h.parse_hard_command("唱放個大招給你看"))
