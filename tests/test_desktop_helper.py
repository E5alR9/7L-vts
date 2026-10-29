# -*- coding: utf-8 -*-
"""桌機助手串指紋（2026-10-11：串被刪/被切走就重建，絕不在私人串亂問）。
services.desktop_helper 無重依賴，直接 import 測。"""
from conftest import ROOT  # noqa: F401
from services import desktop_helper as dh


class _FakeC:
    def __init__(self, turns):
        self._turns = turns

    def get_conversation_history(self):
        return self._turns


def test_marker_const_in_persona():
    assert dh.HELPER_MARKER and dh.HELPER_MARKER in dh.HELPER_SYSTEM_PROMPT


def test_in_helper_chat():
    home = _FakeC([{"role": "user", "content": "這是查詢助手串，陪老爸聊天就是你的工作。"},
                   {"role": "gemini", "content": "好喔！"}])
    assert dh._in_helper_chat(home) is True
    stranger = _FakeC([{"role": "user", "content": "請用一句話總結台灣的特色美食。"},
                       {"role": "gemini", "content": "夜市很熱鬧。"}])
    assert dh._in_helper_chat(stranger) is False
    assert dh._in_helper_chat(_FakeC([])) is False

    class _Boom:
        def get_conversation_history(self):
            raise RuntimeError("app closed")

    assert dh._in_helper_chat(_Boom()) is False


class _FakeInput:
    def __init__(self, ok=True):
        self._ok = ok

    IsOffscreen = False   # 畫面上看得到（藏起來的輸入框不算找到，2026-10-27）

    def Exists(self, t):
        return self._ok

    def GetValuePattern(self):
        if not self._ok:
            raise Exception("nope")
        return object()

    def GetLegacyIAccessiblePattern(self):
        raise Exception("nope")


class _FakeWinInput:
    """searchDepth < 20 裝死（樹深），25 才找得到——測深搜梯子。"""

    def EditControl(self, **kw):
        if (kw.get("searchDepth") or 0) >= 20:
            return _FakeInput(True)
        return _FakeInput(False)


class _FakeWinNoInput:
    def EditControl(self, **kw):
        return _FakeInput(False)


class _FakeCInput:
    def __init__(self, win):
        self.window_ctrl = win


def test_find_input_box_ladder():
    assert dh._find_input_box(_FakeCInput(_FakeWinInput())) is not None
    assert dh._find_input_box(_FakeCInput(_FakeWinNoInput())) is None


def test_com_init_safe():
    uninit = dh._com_init()
    assert uninit is None or callable(uninit)
    if callable(uninit):
        uninit()  # 配對釋放不炸就行


# ── 讀回答：認「剛送的那句後面的回覆」，不數回覆變多沒（2026-10-29）──────────────
class _FakeChat:
    """桌面版只把最近 5 輪留在畫面上：送出後最舊的一輪掉出去，Gemini 回覆數量一直是 5。"""
    def __init__(self, replies):
        self.turns = []
        for i in range(5):
            self.turns += [{"role": "user", "content": f"舊問題{i}"}, {"role": "gemini", "content": f"舊回答{i}"}]
        self.replies = list(replies)   # 每次輪詢時畫面上的回答（模擬一個字一個字長出來）

    def get_conversation_history(self):
        if self.turns[-2]["content"] == "台灣最高的山？" and self.replies:
            self.turns[-1]["content"] = self.replies.pop(0)
        return [dict(t) for t in self.turns]

    def send_prompt(self, text):
        self.turns = self.turns[2:] + [{"role": "user", "content": text}, {"role": "gemini", "content": ""}]


def test_ask_reads_the_reply_after_our_question_even_when_old_turns_scroll_off():
    from services import desktop_helper as dh
    c = _FakeChat(["玉", "玉山", "玉山，海拔 3952 公尺。", "玉山，海拔 3952 公尺。", "玉山，海拔 3952 公尺。"])
    assert sum(t["role"] == "gemini" for t in c.get_conversation_history()) == 5
    assert dh._ask(c, "台灣最高的山？", timeout=5, poll_interval=0.01) == "玉山，海拔 3952 公尺。"


def test_reply_to_ignores_an_old_answer_to_some_other_question():
    from services import desktop_helper as dh
    turns = [{"role": "user", "content": "舊問題"}, {"role": "gemini", "content": "舊回答"},
             {"role": "user", "content": "台灣最高的山？"}]
    assert dh._reply_to(turns, "台灣最高的山？") is None          # 還沒回
    turns.append({"role": "gemini", "content": "玉山"})
    assert dh._reply_to(turns, "台灣 最高的山？") == "玉山"        # 空白不同也認得
    assert dh._reply_to(turns, "別的問題") is None
