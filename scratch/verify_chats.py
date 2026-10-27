import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\qiwai")
from gemini_desktop_controller import GeminiDesktopController
import uiautomation as auto

c = GeminiDesktopController()
c.find_window()


def chat_names():
    names = []
    try:
        root = c.window_ctrl
        for depth in range(1):
            pass
        # 側欄對話：HyperlinkControl 逐個掃
        found = root.HyperlinkControl(searchDepth=12)
        seen = set()
        # uiautomation 的 HyperlinkControl() 只回第一個；用 FindAll 思路改走子樹遍歷
        def walk(ctrl, d):
            if d > 12 or len(names) > 60:
                return
            try:
                for ch in ctrl.GetChildren():
                    try:
                        if ch.ControlTypeName == "HyperlinkControl" and ch.Name and ch.Name not in seen:
                            seen.add(ch.Name)
                            names.append(ch.Name)
                    except Exception:
                        pass
                    walk(ch, d + 1)
            except Exception:
                pass
        walk(root, 0)
    except Exception as e:
        print("names ERR:", str(e)[:100])
    return names


def click_name(name, timeout=3):
    for cls in ("ButtonControl", "HyperlinkControl"):
        try:
            el = getattr(c.window_ctrl, cls)(Name=name, searchDepth=12)
            if el.Exists(timeout):
                try:
                    pat = el.GetInvokePattern()
                    if pat:
                        pat.Invoke()
                        return cls + "/invoke"
                except Exception:
                    pass
                try:
                    el.Click()
                    return cls + "/click"
                except Exception:
                    pass
        except Exception:
            pass
    return ""


before = chat_names()
print("chats_before:", len(before))
r = click_name("新對話")
print("new_chat_click:", r or "NOT_FOUND")
time.sleep(2.5)
after = chat_names()
print("chats_after:", len(after))
hist = c.get_conversation_history()
print("history_turns_now:", len(hist))

# 切回音樂測試串證明切換
r2 = click_name("Streamer Girl's Dad Song")
print("switch_click:", r2 or "NOT_FOUND")
time.sleep(2.5)
hist2 = c.get_conversation_history()
blob = "\n".join(m["content"] for m in hist2)
print("switched_to_music:", ("夜市" in blob or "美食" in blob))
