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
    home = _FakeC([{"role": "user", "content": "你是 7L 查詢助手，陪老爸聊天就是你的工作。"},
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
