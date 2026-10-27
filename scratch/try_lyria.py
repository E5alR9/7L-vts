import base64
import io
import os
import sys
import time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv
load_dotenv()
keys = []
for k in os.getenv("GEMINI_API_KEY", "").splitlines():
    k = k.strip().strip("'\",")
    if len(k) > 10:
        keys.append(k)

from google import genai
c = genai.Client(api_key=keys[0])
prompt = ("Create a cheerful 30-second pop song, 120 BPM, acoustic guitar and "
          "synth, warm young female vocals singing in Mandarin Chinese about "
          "a virtual streamer daughter singing for her dad late at night.")
t0 = time.time()
try:
    it = c.interactions.create(model="lyria-3-clip-preview", input=prompt)
except Exception as e:
    print("CALL_ERR:", str(e)[:500])
    raise SystemExit(0)
print(f"done in {time.time()-t0:.1f}s")
audio = getattr(it, "output_audio", None)
print("has_audio:", bool(audio and getattr(audio, "data", None)))
if audio and getattr(audio, "data", None):
    raw = base64.b64decode(audio.data)
    open("scratch/_lyria_test.mp3", "wb").write(raw)
    print("mp3 bytes:", len(raw))
print("LYRICS:")
print(getattr(it, "output_text", None) or "(none)")
