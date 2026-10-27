import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
import services.vts_client as v
ks = list(v.VTS_EXPRESSION_MAP.keys())
print("n =", len(v.VTS_EXPRESSION_MAP))
print("sample =", ks[:8])
