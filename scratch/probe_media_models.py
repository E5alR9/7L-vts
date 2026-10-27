import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv
load_dotenv()
import re
keys = [v.strip() for v in os.getenv("GEMINI_API_KEY", "").splitlines() if v.strip()]
# 去掉引號/逗號殘留
clean = []
for k in keys:
    k = k.strip().strip("'\",")
    if len(k) > 10:
        clean.append(k)
print("keys:", len(clean))

from google import genai
c = genai.Client(api_key=clean[0])
names = []
try:
    for m in c.models.list():
        n = (m.name or "").replace("models/", "")
        if any(s in n for s in ["lyria", "veo", "tts", "omni", "live"]):
            names.append(n)
except Exception as e:
    print("list ERR:", str(e)[:200])
print("MATCHED:")
for n in sorted(set(names)):
    print(" -", n)
print("has generate_videos:", hasattr(c.models, "generate_videos"))
