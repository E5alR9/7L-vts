import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\qiwai")
from gemini_desktop_controller import GeminiDesktopController

c = GeminiDesktopController()
c.find_window()

hits = []

def walk(ctrl, d):
    if d > 20 or len(hits) > 200:
        return
    try:
        kids = ctrl.GetChildren()
    except Exception:
        return
    for ch in kids:
        try:
            nm = ch.Name or ""
            cn = ch.ControlTypeName or ""
            inv = False
            try:
                inv = bool(ch.GetInvokePattern())
            except Exception:
                pass
            if inv and cn not in ("ButtonControl",):
                # 非窗體按鈕的可點項（側欄/選單候選）
                if len(nm) <= 30:
                    hits.append((cn, nm))
        except Exception:
            pass
        walk(ch, d + 1)

walk(c.window_ctrl, 0)
print("invokable_nonchrome:", len(hits))
seen = set()
for cn, nm in hits:
    if (cn, nm) not in seen:
        seen.add((cn, nm))
        print(" -", cn, ascii(nm))
