# -*- coding: utf-8 -*-
"""取消計時器（2026-11-01 模擬版：老爸說「取消剛剛那個計時器」，沒有這個工具，她說取消了，時間到照響）。"""
import asyncio

import core.intent_router as ir
from core.live_timer_sensor import LiveTimerSensorHub
from core.tool_schema import INTERACTIONS_TOOLS, resolve_tool_name
from conftest import MAIN_SRC as MAIN, load_main


def _hub():
    h = LiveTimerSensorHub()
    h.add_timer(300, "記得喝水")
    h.add_timer(600, "去收衣服")
    return h


def test_cancel_latest_by_default():
    h = _hub()
    assert [t["message"] for t in h.cancel()] == ["去收衣服"]               # 「取消剛剛那個」：最近設的
    assert [t["message"] for t in h.get_active_timers()] == ["記得喝水"]


def test_cancel_by_keyword_and_all():
    h = _hub()
    assert [t["message"] for t in h.cancel(keyword="喝 水")] == ["記得喝水"]
    assert h.cancel(keyword="倒垃圾") == []                                  # 沒有這個：什麼都不動
    assert len(h.get_active_timers()) == 1
    h.add_timer(60, "看烤箱")
    assert len(h.cancel(everything=True)) == 2 and h.get_active_timers() == []
    assert h.cancel() == []                                                   # 沒在跑的：回空的，不炸


def test_dad_cancelling_the_latest_does_not_hit_a_viewers_newer_timer():
    h = LiveTimerSensorHub()
    h.add_timer(600, "收衣服", caller_user="老爸")
    h.add_timer(180, "阿呆的", caller_user="阿呆")
    assert [t["message"] for t in h.cancel(caller_user="老爸")] == ["收衣服"]   # 先找他自己設的（Fable 審查）
    assert [t["message"] for t in h.cancel(caller_user="老爸")] == ["阿呆的"]   # 自己的沒了才輪到別人的


def _text_fn(hub):
    events = []
    web = type("W", (), {"broadcast_event": staticmethod(lambda k, d: events.append(k))})
    ns = load_main("_cancel_timers_text", live_timer_hub=hub, web_dash=web)
    return ns["_cancel_timers_text"], events


def test_report_text_is_truthful():
    f, events = _text_fn(_hub())
    assert f({}) == "已取消計時器：「去收衣服」。" and events == ["timer_cancelled"]
    assert f({"keyword": "倒垃圾"}).startswith("沒有找到要取消的那個計時器，現在還在跑的是：「記得喝水」")
    assert f({"all": "false"}) == "已取消計時器：「記得喝水」。"            # 字串 "false" 不是全部取消（NV 會這樣回）
    assert f({}) == "現在沒有在跑的計時器，不用取消。"
    h = _hub()
    f2, _ = _text_fn(h)
    assert f2({"all": True}).count("「") == 2 and h.get_active_timers() == []


def test_cancel_sentences_are_not_new_timers():
    d = LiveTimerSensorHub.detect_timer_intent
    assert d("取消那個五分鐘後叫我喝水的計時器") is None and d("不用五分鐘後提醒我喝水了") is None
    assert d("五分鐘後叫我喝水") is not None


def test_declared_and_wired():
    assert resolve_tool_name("cancel_timer") == "cancel_timer"
    assert "cancel_timer" in [t["name"] for t in INTERACTIONS_TOOLS]
    assert '_cancel_timers_text(fn_args, caller_user=caller_user)' in MAIN   # 派發器帶著是誰要取消
    i = MAIN.index('            if fn_name == "cancel_timer":\n')         # 子智能體：觀眾的先擋、老爸的當場回報
    assert 'target == "audience"' in MAIN[i:i + 200] and '"report"' in MAIN[i:i + 600]


def test_intent_router_knows_cancel(monkeypatch):
    import core.groq_router as gr

    async def fake(messages, **k):
        return type("R", (), {"text": "cancel"})()
    monkeypatch.setattr(gr, "groq_chat", fake)
    for t in ("取消剛剛那個計時器", "把剛剛那個取消"):                          # 沒有「計時」兩個字的也會問
        assert asyncio.run(ir.classify(t)) == "cancel", t
    assert "取消已經設好的計時器" in asyncio.run(ir.slip_hint("取消剛剛那個計時器"))
