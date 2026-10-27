import io, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio_separator.separator import Separator

sep = Separator(
    output_dir="scratch/_rvc_test",
    output_format="WAV",
    model_file_dir=r"C:\Users\qiwai\models\roformer",
    log_level=20,
)
print("loading model (first run downloads ~100MB)...")
t0 = time.time()
sep.load_model("model_bs_roformer_ep_317_sdr_12.9755.ckpt")
print(f"model ready in {time.time()-t0:.1f}s")

src = "songs_library/cover_cache/5_20am_raw.wav"
print("separating:", src)
t0 = time.time()
outs = sep.separate(src)
print(f"done in {time.time()-t0:.1f}s")
for o in outs:
    print("OUT:", o, os.path.getsize(o) if os.path.exists(o) else "MISSING")
