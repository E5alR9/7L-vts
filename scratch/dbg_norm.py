import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
from core.prompts import TextCleanEngine as C
r = C.normalize_spoken_form("唱《晴天》吧")
print(ascii(r), len(r))
