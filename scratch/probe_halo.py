import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())
from services.vts_client import VTS_EXPRESSION_MAP
print("halo file:", VTS_EXPRESSION_MAP.get("暈"))
print("has 暈:", "暈" in VTS_EXPRESSION_MAP)
