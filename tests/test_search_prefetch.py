# -*- coding: utf-8 -*-
"""猜到要查就先查（services/web_search.prefetch／take_prefetch，2026-11-01）。不連網。"""
import asyncio
import time

import core.intent_router as ir
import services.web_search as ws
from conftest import MAIN_SRC as MAIN


def _reset(monkeypatch, calls):
    monkeypatch.setattr(ws, "search_google", lambda q, depth="basic": calls.append(q) or f"結果：{q}")
    monkeypatch.setitem(ws._PREFETCH, "future", None)


def test_same_question_takes_the_prefetched_result(monkeypatch):
    calls = []
    _reset(monkeypatch, calls)
    ws.prefetch("7L 幫我查一下明天台中會不會下雨")
    fut = ws.take_prefetch("幫老爸查明天台中會不會下雨")
    assert fut is not None and fut.result(5) == "結果：明天台中會不會下雨" and calls == ["明天台中會不會下雨"]
    assert ws.take_prefetch("幫老爸查明天台中會不會下雨") is None              # 用一次就清掉


def test_different_or_old_or_mixed_tasks_do_not_take_it(monkeypatch):
    calls = []
    _reset(monkeypatch, calls)
    ws.prefetch("幫我查一下現在日幣匯率多少")
    assert ws.take_prefetch("查一下今年金馬獎最佳影片") is None               # 講的不是同一件
    assert ws.take_prefetch("查日幣匯率然後設一個 20 秒的計時器") is None      # 夾著別件事
    assert ws.take_prefetch("查現在日幣匯率", now=time.time() + 60) is None   # 放太久
    ws.prefetch("查美金匯率，然後五分鐘後提醒我喝水")                          # 夾著別件事：不先查
    assert ws._PREFETCH["text"] == "幫我查一下現在日幣匯率多少"


def test_prefetch_query_uses_the_real_year():
    from datetime import datetime
    now = datetime(2026, 11, 1)
    assert ws._prefetch_query("幫我查一下今年金馬獎最佳影片", now) == "2026年金馬獎最佳影片"
    assert ws._prefetch_query("幫我查最近有什麼新上映的電影", now) == "最近有什麼新上映的電影 2026年11月"
    assert ws._prefetch_query("查一下iPhone 17多少錢", now) == "iPhone 17多少錢"


def test_router_starts_prefetch_only_for_search(monkeypatch):
    import core.groq_router as gr
    seen = []
    monkeypatch.setattr(ir, "ON_SEARCH", seen.append)
    for label, text in (("search", "幫我查明天天氣"), ("timer", "等等提醒我喝水")):
        async def fake(messages, _l=label, **k):
            return type("R", (), {"text": _l})()
        monkeypatch.setattr(gr, "groq_chat", fake)
        asyncio.run(ir.slip_hint(text))
    assert seen == ["幫我查明天天氣"]


def test_wired_into_subagent_and_startup():
    assert "intent_router.ON_SEARCH = _search_prefetch" in MAIN
    i = MAIN.index("_pre = take_prefetch(task_ins)")
    assert i < MAIN.index("# —— 第一棒：工具判定（按鏈順序）——")               # 先看先查好的，才做工具判定
    assert 'target != "audience"' in MAIN[i:i + 80]
