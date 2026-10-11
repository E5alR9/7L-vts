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
    "3. 「辦不到」只保留給具體的設備/應用操作（打開側欄、點按鈕、下載檔案、"
    "控制電腦、記住事情）。陪聊、提問、講故事、想點子、測試你，一律正常接話，"
    "絕不推說辦不到——陪老爸聊天就是你的工作。\n"
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


# 助手串指紋：人格版本關鍵句（對話串身份證；被刪/切走/人格改版就認得出來重建）。
# v2（2026-10-11）：v1 誠實背帶走火，連陪聊都拒；v2 只擋設備操作。
HELPER_MARKER = "陪老爸聊天就是你的工作"
# 上次認領的串名（回家一跳直達；被刪就當沒記過）。
_ADOPTED_NAME = ""


def _find_new_chat_button(c):
    """找新對話鈕（深搜＋正則，免焦點 Invoke 專用；絕不用 Click 動滑鼠）。"""
    for kw in ({"RegexName": "新對話", "searchDepth": 25},
               {"Name": "新對話", "searchDepth": 25},
               {"RegexName": "新對話"}):
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
            if nm and nm not in names:
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
    _names = _recent_chat_names(c, limit)
    if _ADOPTED_NAME and _ADOPTED_NAME in _names:
        _names = [_ADOPTED_NAME] + [n for n in _names if n != _ADOPTED_NAME]
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
    for kw in ({}, {"searchDepth": 25}):
        try:
            el = c.window_ctrl.EditControl(**kw)
            if el.Exists(2):
                try:
                    if el.GetValuePattern() or el.GetLegacyIAccessiblePattern():
                        return el
                except Exception:
                    pass
                return el
        except Exception:
            pass
    return None


def get_answer(question: str, timeout: float = ASK_TIMEOUT_SEC) -> str:
    """問一句拿一答（阻塞，調用方丟執行緒）。全程串行。
    每次先驗指紋：串被刪/被切走就重建（人格重塞），絕不在私人串亂問。"""
    q = normalize_question(question)
    if not q:
        raise ValueError("問題太短")
    _uninit = _com_init()
    try:
        with _lock:
            c = _controller()
            c.ensure_connected()
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
