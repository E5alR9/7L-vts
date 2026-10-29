# -*- coding: utf-8 -*-
"""桌機助手（2026-10-11）：7L 的手機——桌面版 Gemini 代辦雜事。

定位：加法，不動核心。V7 主腦/Live/管線一個字不改；這個模組拿掉，
CPU 關鍵字打不中而已，其他全部照跑。

能力（v1，只做問答；作曲/下載是下一步）：
- 同一個「7L 助手」對話串問答（開場點一次新對話，當前對話找不到就將就用＋大聲警告）
- 全程免焦點（已驗：SetValue＋Invoke＋輪詢，前景視窗不動）
- 問答串行（COM＋同一個聊天室， overlapped 會互串）

限制（老實寫在這裡）：
- 單輪 15~60 秒，無 streaming；V7 不等它（fire-and-forget，答了才播報）
- 用戶同時手動玩桌面版會互串——私測階段別同時碰
- 超時/異常一律拋錯給調用方，由調用方決定怎麼跟觀眾交代
"""
import os
import re
import sys
import threading
from core.paths import ROOT_DIR

REPO_ROOT = ROOT_DIR
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ASK_TIMEOUT_SEC = 120.0
HELPER_CHAT_TIMEOUT_SEC = 15.0   # 開新串時先塞人格，等它回這麼久（不等完也照問）
MAX_QUESTION_CHARS = 500

# 手機人格（2026-10-11）：新對話串只設一次。重點是第 3 條——分流閘偶爾漏網，
# 誠實背帶兜底：辦不到的事直說，絕不假裝辦了（記住了/查到了這種謊最傷）。
# 2026-10-27 老爸：不用繁瑣的提示詞，規矩一多反而讓它陷入幻覺，直接問就好。這一句只當暗號（認得出是助手串，
# 免得把問題打進老爸自己的對話），之後每一題都原句直接問。
HELPER_SYSTEM_PROMPT = "這是查詢助手串，之後我會直接問問題。"

_lock = threading.Lock()
_chat_ready = False


def normalize_question(q: str) -> str:
    """純函數：去空白＋截斷＋過短判空。"""
    t = (q or "").strip()
    if len(t) < 2:
        return ""
    return t[:MAX_QUESTION_CHARS]


def _controller():
    try:
        from gemini_desktop_controller import GeminiDesktopController
    except Exception as e:
        raise RuntimeError(f"找不到 gemini_desktop_controller.py（它必須在倉庫根目錄）：{e}")
    return _patch_controller(GeminiDesktopController())

# ── 桌面版介面中英文都認（2026-10-27：app 1.16.0 是英文介面，「新對話」「傳送訊息」「你說了」全找不到）──
_NEW_CHAT_RE = "^(新對話|New chat)$"
_PROMPT_BOX_RE = ".*(prompt|提示|輸入|Ask Gemini|詢問 Gemini).*"
_SEND_RE = "(?i)^(傳送訊息|send message)$"
_MODE_PICKER_RE = "(?i).*(mode picker|模式).*"
_USER_MARKS = ("你說了", "You said")
_GEMINI_MARKS = ("Gemini 說了", "Gemini said")
# 對話區裡不是對話內容的字（輸入框提示、免責聲明）
_NOT_CONTENT = {"Ask Gemini", "詢問 Gemini", "Gemini is AI and can make mistakes.", "Gemini 可能會出錯，請查證。",
                "Show thinking", "顯示思路", "Conversation with Gemini", "與 Gemini 的對話"}
# 側欄的功能連結不是對話（認領舊串時以前把它們當對話點進去，停在 Customize 頁）
_NAV_LINKS = {"New chat", "Library", "Images", "Scheduled", "Customize", "Videos", "New notebook", "Gems", "Explore Gems",
              "新對話", "媒體庫", "圖片", "排程", "自訂", "影片", "新增筆記本", "探索 Gem"}
# 7L 代答用最快的模型：停在 4 Argon High 時一句「收到」轉一分多鐘沒回；切 3.5 Flash-Lite 3.8 秒就回（2026-10-27 實測）
DESKTOP_MODEL_RE = ".*Flash-Lite.*"
GEMINI_APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Gemini")


def _press(el, order=("invoke", "legacy", "expand")) -> bool:
    """按下控制項：先用不動滑鼠的方式（Invoke／預設動作／展開），都不行才真的點（老爸同意可以動滑鼠）。"""
    for how in order:
        try:
            if how == "invoke":
                el.GetInvokePattern().Invoke()
            elif how == "legacy":
                el.GetLegacyIAccessiblePattern().DoDefaultAction()
            else:
                el.GetExpandCollapsePattern().Expand()
            return True
        except Exception:
            continue
    try:
        el.Click(simulateMove=False)
        return True
    except Exception:
        return False


def _send_button(c):
    try:
        el = c.window_ctrl.ButtonControl(RegexName=_SEND_RE, searchDepth=32)
        return el if el.Exists(2) else None
    except Exception:
        return None


def _history(c):
    """對話紀錄（中英文標籤都認）：[{'role': 'user'|'gemini', 'content': ...}]。"""
    try:
        container = c._get_chat_container()
    except Exception:
        container = None
    if not container:
        return []
    turns, role, lines = [], None, []
    for t in c._collect_text_nodes(container):
        mark = next((m for m in _USER_MARKS if t.startswith(m)), None)
        gmark = next((m for m in _GEMINI_MARKS if t.startswith(m)), None)
        if mark or gmark:
            new_role = "user" if mark else "gemini"
            rest = t[len(mark or gmark):].strip()
            if role == new_role and (not rest or rest in lines):
                continue          # 英文版同一句會有「You said 內容」和「You said」兩個標籤
            if role and lines:
                turns.append({"role": role, "content": "\n".join(lines)})
            role, lines = new_role, ([rest] if rest else [])
        elif role and t not in lines and t not in _NOT_CONTENT:
            lines.append(t)
    if role and lines:
        turns.append({"role": role, "content": "\n".join(lines)})
    return turns


def _set_prompt(c, text: str) -> None:
    """寫進聊天輸入框：原廠只用 Legacy 寫法，失敗就直接報錯；那個寫法現在常回「元件不可用」
    （COMError -2147220992，2026-10-27 實測），ValuePattern 照樣寫得進去（寫完送出鈕會出現）。"""
    el = c.get_input_field()
    for how in ("value", "legacy"):
        try:
            if how == "value":
                el.GetValuePattern().SetValue(text)
            else:
                el.GetLegacyIAccessiblePattern().SetValue(text)
            return
        except Exception:
            continue
    el.SendKeys(text)


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def _reply_to(turns, prompt: str):
    """對話紀錄裡「最後一句我方的話是 prompt」時，回它後面那則 Gemini 回覆（還沒回回 None）。"""
    key = _norm(prompt)[:40]
    users = [i for i, t in enumerate(turns) if t["role"] == "user"]
    if not key or not users or not _norm(turns[users[-1]]["content"]).startswith(key):
        return None
    after = [t["content"] for t in turns[users[-1] + 1:] if t["role"] == "gemini" and t["content"]]
    return after[-1] if after else None


def _send(c, text: str, wait: float = 4.0) -> None:
    """填進輸入框、等送出鈕出現再按。按不到就拋錯（呼叫端改走 API）。
    原廠 send_prompt 找不到鈕會改按 Enter：鍵盤送到的是老爸當下在用的視窗，桌面版這邊什麼都沒送，
    還白等到逾時（2026-10-29 實機：問題卡在輸入框沒送出，等了 40 秒）。"""
    import time as _t
    prev = _foreground()
    try:
        _set_prompt(c, text)
        deadline = _t.time() + wait
        while _t.time() < deadline:
            btn = _send_button(c)
            if btn is not None and _press(btn, order=("invoke", "legacy")):
                return
            _t.sleep(0.3)
        raise RuntimeError("桌面版送出鈕按不到，問題沒送出去")
    finally:
        _give_back_focus(prev, getattr(c, "hwnd", None))


def _foreground():
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _give_back_focus(prev, gemini_hwnd) -> None:
    """寫進輸入框會把焦點搶到 Gemini（2026-10-29 實測：問完 Gemini 跳到最前面擋畫面，老爸打字也會打進去）。
    送出後把焦點還給原本在用的視窗，Gemini 放回最底下。"""
    try:
        import ctypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        fg = u.GetForegroundWindow()
        if prev and fg and fg != prev:
            me, them = k.GetCurrentThreadId(), u.GetWindowThreadProcessId(fg, None)
            u.AttachThreadInput(me, them, True)   # 跨程序搶回前景的標準做法
            try:
                u.SetForegroundWindow(prev)
                u.BringWindowToTop(prev)
            finally:
                u.AttachThreadInput(me, them, False)
        if gemini_hwnd:
            u.SetWindowPos(gemini_hwnd, 1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)   # HWND_BOTTOM，不搶焦點
    except Exception:
        pass


def _ask(c, prompt: str, timeout: float = 60.0, poll_interval: float = 0.3) -> str:
    """送出問題、等 Gemini 回完（連讀兩次文字一樣就算回完；讀一次本身要 0.3 秒，以前要連三次一樣、多等 2～3 秒）。
    原廠 ask 數「Gemini 回覆變多了沒」，但桌面版只把最近 5 輪留在畫面上：串一長數量就卡在 5，
    回答明明出來了還一直等到逾時（2026-10-29 計時實測：每句白等 24 秒）。改認「剛送的那句後面的回覆」。"""
    import time as _t
    before = [(t["role"], t["content"]) for t in c.get_conversation_history()]
    c.send_prompt(prompt)   # _patch_controller 換成 _send（按不到送出鈕就報錯，不亂按 Enter）
    start, last = _t.time(), ""
    while _t.time() - start < timeout:
        _t.sleep(poll_interval)
        try:
            turns = c.get_conversation_history()
        except Exception:
            continue          # 回答一個字一個字長出來時元件會換掉，讀到一半拋 COMError：下一輪再讀
        if [(t["role"], t["content"]) for t in turns] == before:
            continue          # 畫面還沒動（同一句問兩次時，舊的回答不能當這次的）
        text = _reply_to(turns, prompt)
        if not text:
            continue
        if text == last:
            return text
        last = text
    if last:
        return last
    raise TimeoutError("等待 Gemini 回覆逾時！")


def _patch_controller(c):
    """原廠控制器（根目錄 gemini_desktop_controller.py）只認中文介面：找元件的幾個方法換成中英文都認的。"""
    _orig_get_input = c.get_input_field

    def _get_input():
        el = _find_input_box(c)
        if el is not None:
            return el
        return _orig_get_input()
    c.get_input_field = _get_input
    c.set_prompt_text = lambda text: _set_prompt(c, text)
    c.send_prompt = lambda text: _send(c, text)
    c.get_send_button = lambda: _send_button(c)
    c.get_conversation_history = lambda: _history(c)
    c.ask = lambda prompt, timeout=60.0, poll_interval=0.3: _ask(c, prompt, timeout, poll_interval)
    return c


def _ensure_model(c) -> bool:
    """模型切到 DESKTOP_MODEL_RE（已經是就不動）。切不成回 False（照當前模型問）。"""
    import time as _t
    try:
        picker = c.window_ctrl.ButtonControl(RegexName=_MODE_PICKER_RE, searchDepth=32)
        if not picker.Exists(2):
            return False
        if re.match(DESKTOP_MODEL_RE, picker.Name or ""):
            return True
        _press(picker, order=("expand", "invoke", "legacy"))   # 「按下」不報錯但打不開選單（2026-10-27 實測）
        _t.sleep(1.0)
        item = c.window_ctrl.MenuItemControl(RegexName=DESKTOP_MODEL_RE, searchDepth=40)
        if not item.Exists(2):
            return False
        _press(item)
        _t.sleep(1.0)
        print(f"🔁 [桌機助手] 模型切到 {item.Name.split(' ')[0] if item.Name else 'Flash-Lite'}")
        return True
    except Exception:
        return False


# 視窗縮小、被蓋住時 Chromium 會把頁面暫停：問題送出去後一直停在「正在搜尋網路」，視窗一還原 1 秒就生完
# （2026-10-29 實測）。開 Gemini 時帶這幾個參數，它在背後也照常跑，就不用把視窗叫到最前面擋老爸的畫面。
GEMINI_BG_FLAGS = ["--disable-renderer-backgrounding", "--disable-background-timer-throttling",
                   "--disable-backgrounding-occluded-windows", "--disable-features=CalculateNativeWinOcclusion"]


def _gemini_has_bg_flags() -> bool:
    try:
        import psutil
        for p in psutil.process_iter(["exe", "cmdline"]):
            if (p.info["exe"] or "").lower().startswith(GEMINI_APP_DIR.lower()) and \
                    "--disable-backgrounding-occluded-windows" in " ".join(p.info["cmdline"] or []):
                return True
    except Exception:
        pass
    return False


def _launch_gemini_app(wait: float = 25.0) -> bool:
    """打開桌面版 Gemini（帶 GEMINI_BG_FLAGS），等視窗出來、頁面載入。
    7L 由 V7.bat 開，不在沙盒裡，直接開就好（以前用 explorer 開是為了沙盒，但 explorer 帶不了參數）。"""
    import subprocess
    import time as _t
    exe = os.path.join(GEMINI_APP_DIR, "Gemini.exe")
    if not os.path.exists(exe):
        return False
    subprocess.Popen([exe] + GEMINI_BG_FLAGS, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    deadline = _t.time() + wait
    while _t.time() < deadline:
        _t.sleep(1.0)
        try:
            if _controller().find_window():
                _t.sleep(4.0)       # 等頁面載入
                return True
        except Exception:
            pass
    return False


def restart_gemini_app(wait: float = 25.0) -> bool:
    """關掉桌面版 Gemini 再開（老爸同意：分頁亂掉、自己修不回來就重開）。"""
    import time as _t
    try:
        import psutil
        for p in psutil.process_iter(["exe"]):
            try:
                if (p.info["exe"] or "").lower().startswith(GEMINI_APP_DIR.lower()):
                    p.kill()
            except Exception:
                pass
    except Exception:
        return False
    _t.sleep(2.0)
    ok = _launch_gemini_app(wait)
    if ok:
        print("🔄 [桌機助手] 桌面版 Gemini 已重開")
    return ok


_BG_RESTARTED = False


def _keep_behind(hwnd) -> None:
    """縮小的視窗讀不到輸入框（UIA 當它不在畫面上）：還原但放到所有視窗最底下、不搶焦點，不擋老爸的畫面。"""
    import ctypes
    u = ctypes.windll.user32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
    u.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)   # HWND_BOTTOM，SWP_NOSIZE|NOMOVE|NOACTIVATE


def _connect():
    """要用桌面版前先看桌面上有沒有（老爸指定 2026-10-27）：沒開就自動打開；最小化就還原到最底層（不搶焦點、不擋畫面）。
    開著但沒帶背景參數（老爸自己開的）：重開一次帶上，不然在背後會停住。打不開才拋「找不到」（調用方改走 API）。"""
    global _BG_RESTARTED
    c = _controller()
    try:
        c.ensure_connected()
    except RuntimeError:
        print("📱 [桌機助手] 桌面上沒有桌面版 Gemini，自動打開")
        if not _launch_gemini_app():
            raise RuntimeError("找不到桌面版 Gemini，也打不開")
        c = _controller()
        c.ensure_connected()
    if not _BG_RESTARTED and not _gemini_has_bg_flags():
        _BG_RESTARTED = True
        print("📱 [桌機助手] 桌面版沒帶背景參數（縮小／被蓋住會停住），重開一次帶上")
        if restart_gemini_app():
            c = _controller()
            c.ensure_connected()
    try:
        _keep_behind(c.hwnd)
    except Exception:
        pass
    return c


def _ensure_chat_view(c):
    """自我修正：找不到聊天輸入框（停在 Customize、Library 這些頁）→ 按 New chat；還不行 → 重開 Gemini。
    回可用的控制器；修不回來拋錯（調用方走 Live 兜底）。"""
    import time as _t
    if _find_input_box(c) is not None:
        return c
    btn = _find_new_chat_button(c)
    if btn is not None and _press(btn):
        _t.sleep(2.0)
        if _find_input_box(c) is not None:
            print("🔧 [桌機助手] 不在聊天頁，已按 New chat 回來")
            return c
    print("⚠️ [桌機助手] 找不到聊天輸入框，重開桌面版 Gemini")
    global _chat_ready
    _chat_ready = False
    if not restart_gemini_app():
        raise RuntimeError("找不到 Gemini 聊天輸入框，重開也失敗")
    c = _controller()
    c.ensure_connected()
    btn = _find_new_chat_button(c)
    if btn is not None:
        _press(btn)
        _t.sleep(2.0)
    if _find_input_box(c) is None:
        raise RuntimeError("重開 Gemini 後還是找不到聊天輸入框")
    return c


# 助手串指紋：人格版本關鍵句（對話串身份證；被刪/切走/人格改版就認得出來重建）。
# v2（2026-10-11）：v1 誠實背帶走火，連陪聊都拒；v2 只擋設備操作。
# v3（2026-10-11）：去角色化，桌面版只是工具，7L 自己回話。舊串自動重建。
# 不提 7L（老爸 2026-10-27：桌面版只是代替 Live 做穩定思考的，不用知道 7L）
HELPER_MARKER = "查詢助手串"
# 上次認領的串名（回家一跳直達；被刪就當沒記過）。
_ADOPTED_NAME = ""


def _find_new_chat_button(c):
    """找新對話鈕（深搜＋正則，免焦點 Invoke 專用；絕不用 Click 動滑鼠）。"""
    for kw in ({"RegexName": _NEW_CHAT_RE, "searchDepth": 25},):
        for cls in ("HyperlinkControl", "ButtonControl"):
            try:
                el = getattr(c.window_ctrl, cls)(**kw)
                if el.Exists(2):
                    try:
                        if el.GetInvokePattern():
                            return el
                    except Exception:
                        pass
            except Exception:
                pass
    return None


def _ensure_sidebar_open(c) -> bool:
    """側欄開關（2026-10-11）：沒指紋先開側欄再找。找*側欄*鈕 Expand；
    找不到/已開都算過（冪等），只回報有沒有動過手。」"""
    try:
        btn = c.window_ctrl.ButtonControl(RegexName=".*側欄.*", searchDepth=25)
        if not btn.Exists(3):
            return False
        try:
            pat = btn.GetExpandCollapsePattern()
            if pat:
                pat.Expand()
                return True
        except Exception:
            pass
        try:
            pat = btn.GetInvokePattern()
            if pat:
                pat.Invoke()
                return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def _recent_chat_names(c, limit=5):
    """掃近期對話名（置頂前幾個，RegexName 枚舉 foundIndex）。"""
    names = []
    for i in range(1, limit * 4 + 1):
        if len(names) >= limit:
            break
        try:
            h = c.window_ctrl.HyperlinkControl(RegexName=".+", foundIndex=i)
            if not h.Exists(1):
                continue
            nm = (h.Name or "").strip()
            if nm and nm not in names and nm not in _NAV_LINKS:
                names.append(nm)
        except Exception:
            break
    return names


def _adopt_recent_helper_chat(c, limit=5) -> bool:
    """認領舊助手串（2026-10-11）：開側欄→掃近期→逐個切入驗指紋。
    找到就停在那個串回 True；都沒有回 False（調用方建新的）。
    全程免焦點 Invoke；一次只動一個，log 交代行蹤。」"""
    import time as _t
    try:
        _ensure_sidebar_open(c)
    except Exception:
        pass
    if _in_helper_chat(c):
        return True  # 就站在自己家，不用動
    global _ADOPTED_NAME
    # 只回上次記住的助手串（2026-10-27 以前會逐個點開最近的對話驗指紋：慢、又會翻老爸的私人對話）
    _names = [_ADOPTED_NAME] if _ADOPTED_NAME and _ADOPTED_NAME in _recent_chat_names(c, limit) else []
    for nm in _names:
        try:
            el = c.window_ctrl.HyperlinkControl(RegexName="^" + re.escape(nm) + "$")
            if not el.Exists(2):
                continue
            invoked = False
            try:
                pat = el.GetInvokePattern()
                if pat:
                    pat.Invoke()
                    invoked = True
            except Exception:
                pass
            if not invoked:
                continue
            _t.sleep(2.0)
            if _in_helper_chat(c):
                print(f"✅ [桌機助手] 認領舊助手串（免新建）。")
                _ADOPTED_NAME = nm
                return True
        except Exception:
            continue
    return False


def ensure_helper_chat(timeout: float = HELPER_CHAT_TIMEOUT_SEC) -> bool:
    """點一次「新對話」當 7L 專用串，並先塞人格。找不到就用當前對話（回 False，調用方要大聲警告）。"""
    global _chat_ready, _ADOPTED_NAME
    if _chat_ready:
        return True
    c = _controller()
    c.ensure_connected()
    btn = _find_new_chat_button(c)
    if btn is None:
        return False
    try:
        btn.GetInvokePattern().Invoke()
    except Exception:
        return False
    _chat_ready = True
    _ADOPTED_NAME = ""  # 新串還沒名字，下次靠指紋掃
    import time as _t
    _t.sleep(1.5)
    _ensure_model(c)
    try:
        c.ask(HELPER_SYSTEM_PROMPT, timeout=timeout)
    except Exception:
        pass
    return True


def _in_helper_chat(c) -> bool:
    """純檢查（不寫入）：當前對話串里有人格指紋嗎？被刪/被切走就回 False。"""
    try:
        blob = "\n".join((m.get("content") or "") for m in c.get_conversation_history())
        return HELPER_MARKER in blob
    except Exception:
        return False


def _com_init():
    """COM 公寓初始化（2026-10-11：V7 經 to_thread 調用時，工作線程沒 CoInitialize，
    UIA 直接啞巴——主線程驗證全過、V7 裡全瞎就是這麼來的）。回 uninit 回調或 None。"""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        return comtypes.CoUninitialize
    except Exception:
        return None


def _find_input_box(c):
    """輸入框深搜（默認→25 層；樹狀態會變，淺的找不到就往深處打）。
    回 control 或 None（調用方接著走原廠 get_input_field 兜底）。"""
    for kw in ({"RegexName": _PROMPT_BOX_RE, "searchDepth": 30}, {"RegexClassName": ".*ql-editor.*", "searchDepth": 30}):
        try:
            el = c.window_ctrl.EditControl(**kw)
            if el.Exists(2) and not el.IsOffscreen:
                try:
                    if el.GetValuePattern() or el.GetLegacyIAccessiblePattern():
                        return el
                except Exception:
                    pass
                return el
        except Exception:
            pass
    return None


def prewarm() -> bool:
    """7L 開機時先開好助手串、切好模型（第一次深度思考／閒聊才不用多等約 30 秒）。不問問題。"""
    global _chat_ready
    _uninit = _com_init()
    try:
        with _lock:
            c = _connect()
            c = _ensure_chat_view(c)
            if not _in_helper_chat(c):
                _chat_ready = False
                ensure_helper_chat()
                c = _ensure_chat_view(c)
            _ensure_model(c)
        print("📱 [桌機助手] 桌面版 Gemini 預熱好了（助手串、模型都就緒）")
        return True
    except Exception as e:
        print(f"⚠️ [桌機助手] 桌面版預熱沒成功（{e}），用到時再試")
        return False
    finally:
        try:
            if _uninit:
                _uninit()
        except Exception:
            pass


def get_answer(question: str, timeout: float = ASK_TIMEOUT_SEC) -> str:
    """問一句拿一答（阻塞，調用方丟執行緒）。全程串行。
    每次先驗指紋：串被刪/被切走就重建（人格重塞），絕不在私人串亂問。"""
    q = normalize_question(question)
    if not q:
        raise ValueError("問題太短")
    _uninit = _com_init()
    try:
        with _lock:
            c = _connect()
            c = _ensure_chat_view(c)
            if not _in_helper_chat(c):
                # 指紋不在：先開側欄認領舊串，認不到才建新（免空串垃圾）。
                _adopted = False
                try:
                    _adopted = _adopt_recent_helper_chat(c)
                except Exception:
                    pass
                if not _adopted:
                    global _chat_ready
                    _chat_ready = False  # 指紋不在，重建
                    if not ensure_helper_chat():
                        print("⚠️ [桌機助手] 找不到新對話鈕，將就用當前對話串（別同時手動玩桌面版）。")
            c = _ensure_chat_view(c)   # 認領／開新串時可能切到別頁：問之前再確認一次
            _ensure_model(c)
            # 輸入框深搜補丁（2026-10-11）：原廠默認深度在某些樹狀態下找不到，
            # 找不到就拋錯走 Live 兜底，絕不空轉。
            try:
                _orig_get_input = c.get_input_field

                def _patched_get_input():
                    el = _find_input_box(c)
                    if el is not None:
                        return el
                    return _orig_get_input()

                c.get_input_field = _patched_get_input
            except Exception:
                pass
            ans = c.ask(q, timeout=timeout)
    finally:
        try:
            if _uninit:
                _uninit()
        except Exception:
            pass
    ans = (ans or "").strip()
    if not ans:
        raise RuntimeError("桌面版逾時沒回")
    return ans
