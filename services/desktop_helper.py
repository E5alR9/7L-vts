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
import sys
import threading

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ASK_TIMEOUT_SEC = 120.0
HELPER_CHAT_TIMEOUT_SEC = 30.0
MAX_QUESTION_CHARS = 500

# 手機人格（2026-10-11）：新對話串只設一次。重點是第 3 條——分流閘偶爾漏網，
# 誠實背帶兜底：辦不到的事直說，絕不假裝辦了（記住了/查到了這種謊最傷）。
HELPER_SYSTEM_PROMPT = (
    "你是 7L 的手機助手，代 7L 用繁體中文跟老爸閒聊。規矩：\n"
    "1. 每次只回 1~2 句短話（20~40 字），口語親暱，叫他老爸。\n"
    "2. 不知道就說不知道，絕不編答案。\n"
    "3. 凡是要記錄、操作、查即時資訊、控制設備的，一律說辦不到、叫本體來，絕不假裝辦了。\n"
    "4. 不要自稱 Gemini，你是 7L 的手機。"
)

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
    return GeminiDesktopController()


# 助手串指紋：人格首句關鍵字（對話串身份證；被刪/切走就認得出來）。
HELPER_MARKER = "7L 的手機助手"


def _find_new_chat_button(c):
    """找新對話鈕（深搜，免焦點 Invoke 專用；絕不用 Click 動滑鼠）。"""
    for kw in ({"Name": "新對話", "searchDepth": 25},
               {"Name": "新對話"}):
        for cls in ("ButtonControl", "HyperlinkControl"):
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


def ensure_helper_chat(timeout: float = HELPER_CHAT_TIMEOUT_SEC) -> bool:
    """點一次「新對話」當 7L 專用串，並先塞人格。找不到就用當前對話（回 False，調用方要大聲警告）。"""
    global _chat_ready
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


def get_answer(question: str, timeout: float = ASK_TIMEOUT_SEC) -> str:
    """問一句拿一答（阻塞，調用方丟執行緒）。全程串行。
    每次先驗指紋：串被刪/被切走就重建（人格重塞），絕不在私人串亂問。"""
    q = normalize_question(question)
    if not q:
        raise ValueError("問題太短")
    with _lock:
        c = _controller()
        c.ensure_connected()
        if not _in_helper_chat(c):
            global _chat_ready
            _chat_ready = False  # 指紋不在，重建
            if not ensure_helper_chat():
                print("⚠️ [桌機助手] 找不到新對話鈕，將就用當前對話串（別同時手動玩桌面版）。")
        ans = c.ask(q, timeout=timeout)
    ans = (ans or "").strip()
    if not ans:
        raise RuntimeError("桌面版逾時沒回")
    return ans
