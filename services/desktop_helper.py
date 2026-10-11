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
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ASK_TIMEOUT_SEC = 120.0
HELPER_CHAT_TIMEOUT_SEC = 30.0
MAX_QUESTION_CHARS = 500

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


def ensure_helper_chat(timeout: float = HELPER_CHAT_TIMEOUT_SEC) -> bool:
    """點一次「新對話」當 7L 專用串。找不到就用當前對話（回 False，調用方要大聲警告）。"""
    global _chat_ready
    if _chat_ready:
        return True
    c = _controller()
    c.ensure_connected()
    deadline = time.time() + timeout
    try:
        import uiautomation as auto  # noqa: F401 （controller 相依，這裡只借名字找鈕）
        btn = None
        try:
            b = c.window_ctrl.ButtonControl(Name="新對話")
            if b.Exists(2):
                btn = b
        except Exception:
            pass
        if btn is None:
            try:
                h = c.window_ctrl.HyperlinkControl(Name="新對話")
                if h.Exists(2):
                    btn = h
            except Exception:
                pass
        if btn is not None:
            try:
                pat = btn.GetInvokePattern()
                if pat:
                    pat.Invoke()
                else:
                    btn.Click()
            except Exception:
                pass
            _chat_ready = True
            return True
    except Exception:
        pass
    _ = deadline
    return False


def get_answer(question: str, timeout: float = ASK_TIMEOUT_SEC) -> str:
    """問一句拿一答（阻塞，調用方丟執行緒）。全程串行。"""
    q = normalize_question(question)
    if not q:
        raise ValueError("問題太短")
    with _lock:
        c = _controller()
        c.ensure_connected()
        if not ensure_helper_chat():
            print("⚠️ [桌機助手] 找不到新對話鈕，將就用當前對話串（別同時手動玩桌面版）。")
        ans = c.ask(q, timeout=timeout)
    ans = (ans or "").strip()
    if not ans:
        raise RuntimeError("桌面版逾時沒回")
    return ans
