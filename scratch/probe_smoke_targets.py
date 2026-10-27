import io, sys, traceback, inspect, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

mods = ["core.memory", "core.prompts", "core.llm_engine",
        "services.piano_engine", "services.vts_client", "services.tiktok_listener"]
import importlib
for name in mods:
    try:
        m = importlib.import_module(name)
        fns = [n for n, o in vars(m).items()
               if inspect.isfunction(o) and getattr(o, "__module__", "") == name and not n.startswith("_")]
        print(f"[OK] {name}  fns={len(fns)}  sample={fns[:14]}")
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
        traceback.print_exc(limit=2)
