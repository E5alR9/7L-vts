# -*- coding: utf-8 -*-
"""core/utils.speech_allowed — 直播對象閘門（只對觀眾發聲）"""
from conftest import ROOT  # noqa: F401
from core.utils import speech_allowed


def test_public_items_always_speak(monkeypatch):
    """觀眾看得到的管道（TikTok/主動發言/自主彈琴）永遠播出"""
    monkeypatch.delenv("OPERATOR_SPEECH", raising=False)
    assert speech_allowed(False) is True
    monkeypatch.setenv("OPERATOR_SPEECH", "0")
    assert speech_allowed(False) is True          # 靜默開關不影響公開內容


def test_private_items_silent_by_default(monkeypatch):
    """預設：操作者私訊（mic/鍵盤/Web/文字檔/提醒）不播出"""
    monkeypatch.delenv("OPERATOR_SPEECH", raising=False)
    assert speech_allowed(True) is False


def test_operator_speech_opt_in_values(monkeypatch):
    for val, want in (("1", True), ("true", True), ("TRUE", True), ("yes", True),
                      ("0", False), ("", False), ("maybe", False), ("no", False)):
        monkeypatch.setenv("OPERATOR_SPEECH", val)
        assert speech_allowed(True) is want, f"OPERATOR_SPEECH={val!r}"
    monkeypatch.delenv("OPERATOR_SPEECH", raising=False)
