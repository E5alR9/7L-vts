# -*- coding: utf-8 -*-
"""助手串認領（2026-10-11：沒指紋先開側欄找，找不到才新建，免空串垃圾）。
services.desktop_helper 無重依賴，直接 import＋假 controller 測。"""
import re

from conftest import ROOT  # noqa: F401
from services import desktop_helper as dh


PERSONA_TURNS = [{"role": "user", "content": "你是 7L 的手機助手，陪老爸聊天就是你的工作。"},
                 {"role": "gemini", "content": "好喔！"}]


class _FakePat:
    def __init__(self, box, name):
        self._box = box
        self._name = name

    def Invoke(self):
        self._box["current"] = self._name
        self._box["invoked"].append(self._name)


class _FakeEl:
    def __init__(self, box, name, exists=True, invokable=True):
        self._box = box
        self._name = name
        self._exists = exists
        self._invokable = invokable

    def Exists(self, t):
        return self._exists

    @property
    def Name(self):
        return self._name

    def GetInvokePattern(self):
        if not self._invokable:
            raise Exception("no pattern")
        box, name = self._box, self._name

        class _P:
            def Invoke(self):
                box["current"] = name
                box["invoked"].append(name)

        return _P()


class _FakeSideBtn:
    def __init__(self, box):
        self._box = box

    def Exists(self, t):
        return True

    def GetExpandCollapsePattern(self):
        box = self._box

        class _E:
            def Expand(self):
                box["expanded"] = True

        return _E()

    def GetInvokePattern(self):
        raise Exception("toggle has no invoke")


class _FakeWindow:
    def __init__(self, chats, side_present=True):
        self._chats = chats
        self._box = {"current": next(iter(chats)) if chats else "",
                     "invoked": [], "expanded": False}
        self._side_present = side_present

    def HyperlinkControl(self, RegexName=None, foundIndex=1, **kw):
        pat = re.compile(RegexName or "")
        matched = [n for n in self._chats if pat.search(n)]
        idx = (foundIndex or 1) - 1
        if idx < 0 or idx >= len(matched):
            return _FakeEl(self._box, "", exists=False)
        return _FakeEl(self._box, matched[idx])

    def ButtonControl(self, RegexName=None, Name=None, **kw):
        import re as _re2
        if RegexName and "側欄" in RegexName and self._side_present:
            return _FakeSideBtn(self._box)
        if Name == "新對話":
            return _FakeEl(self._box, "新對話")
        return _FakeEl(self._box, "", exists=False)


class _FakeC:
    def __init__(self, chats, side_present=True):
        self._chats = chats
        self.window_ctrl = _FakeWindow(chats, side_present)

    def get_conversation_history(self):
        return self._chats.get(self.window_ctrl._box["current"], [])


def test_recent_chat_names_order_and_cap():
    c = _FakeC({"A": [], "B": [], "C": [], "D": []})
    assert dh._recent_chat_names(c, 3) == ["A", "B", "C"]
    assert dh._recent_chat_names(_FakeC({}), 3) == []


def test_ensure_sidebar_open():
    c = _FakeC({"A": []})
    assert dh._ensure_sidebar_open(c) is True
    assert c.window_ctrl._box["expanded"] is True
    c2 = _FakeC({"A": []}, side_present=False)
    assert dh._ensure_sidebar_open(c2) is False


def test_adopt_finds_helper_chat():
    dh._ADOPTED_NAME = "助手串"  # 上次認領過，回家一跳直達
    c = _FakeC({"閒聊A": [{"role": "user", "content": "今天天氣真好"}],
                "助手串": PERSONA_TURNS,
                "音樂": []})
    try:
        assert dh._adopt_recent_helper_chat(c, limit=5) is True
        assert c.window_ctrl._box["current"] == "助手串"
        assert c.window_ctrl._box["invoked"] == ["助手串"]
    finally:
        dh._ADOPTED_NAME = ""


def test_adopt_without_memory_scans():
    dh._ADOPTED_NAME = ""
    c = _FakeC({"閒聊A": [{"role": "user", "content": "今天天氣真好"}],
                "助手串": PERSONA_TURNS})
    try:
        assert dh._adopt_recent_helper_chat(c, limit=5) is True
        assert c.window_ctrl._box["current"] == "助手串"
        assert c.window_ctrl._box["invoked"][-1] == "助手串"
        assert dh._ADOPTED_NAME == "助手串"  # 記住，下次直達
    finally:
        dh._ADOPTED_NAME = ""


def test_adopt_miss_returns_false():
    dh._ADOPTED_NAME = ""
    c = _FakeC({"閒聊A": [{"role": "user", "content": "今天天氣真好"}]})
    try:
        assert dh._adopt_recent_helper_chat(c, limit=5) is False
        assert c.window_ctrl._box["current"] == "閒聊A"  # 沒亂動
    finally:
        dh._ADOPTED_NAME = ""
