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
    home = _FakeC([{"role": "user", "content": "你是 7L 的手機助手，代 7L 用繁體中文跟老爸閒聊。"},
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
