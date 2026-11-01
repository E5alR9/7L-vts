# -*- coding: utf-8 -*-
"""語意指令分流：老爸打的字像要她做事，紙條提醒她交辦（core/intent_router，2026-11-01）。"""
import asyncio

import core.intent_router as ir
from conftest import MAIN_SRC as MAIN


def _fake_groq(answer, calls):
    async def f(messages, **k):
        calls.append(messages[-1]["content"])
        return type("R", (), {"text": answer})()
    return f


def test_plain_chat_never_asks_groq(monkeypatch):
    import core.groq_router as gr
    calls = []
    monkeypatch.setattr(gr, "groq_chat", _fake_groq("timer", calls))
    for t in ("今天好累喔", "妳好可愛", "晚安", "哈"):
        assert asyncio.run(ir.classify(t)) is None
    assert calls == []                                                            # 沒有那些字：連問都不問


def test_hint_when_groq_says_it_is_a_task(monkeypatch):
    import core.groq_router as gr
    calls = []
    monkeypatch.setattr(gr, "groq_chat", _fake_groq("timer", calls))
    assert asyncio.run(ir.classify("等等提醒我喝水")) == "timer" and calls == ["等等提醒我喝水"]
    h = asyncio.run(ir.slip_hint("等等提醒我喝水"))
    assert "設計時器" in h and "先問幾分鐘" in h and "invoke_subagent" in h
    assert asyncio.run(ir.slip_hint("幫我記住我喜歡貓", handled_by_cpu=True)) == ""   # 程式已經直接存了
    monkeypatch.setattr(gr, "groq_chat", _fake_groq("none", []))
    assert asyncio.run(ir.slip_hint("我剛查了一下天氣")) == ""


def test_groq_down_adds_nothing(monkeypatch):
    import core.groq_router as gr

    async def dead(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(gr, "groq_chat", dead)
    assert asyncio.run(ir.slip_hint("幫我查一下明天天氣")) == ""


def test_wired_into_typed_slips_only():
    assert MAIN.count("await _intent_hint(user_input, owner)") == 2
    assert "if not user_audio_b64:\n            slip += await _intent_hint(user_input, owner)" in MAIN
