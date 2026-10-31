# -*- coding: utf-8 -*-
"""AI 狀態唯一轉換點 core.stage_state.set_ai_state＋「在講／在唱」全程式一份（2026-10-23；10-26 從主程式搬到 core）。"""
import ast
import os
import types

import pytest

from conftest import ROOT  # noqa: F401
import core.stage_state as stage
import services.auto_cover_pipeline as acp


def _vts_src():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def st(monkeypatch):
    """乾淨的舞台狀態：IDLE、沒有監聽、沒有唱歌旗、沒在播。"""
    monkeypatch.setattr(stage, "AI_STATE", "IDLE")
    monkeypatch.setattr(stage, "_STATE_LISTENERS", [])
    monkeypatch.setattr(stage, "_SINGING_PROBE", None)
    monkeypatch.setattr(stage, "IS_MP3_PLAYING", False)
    return stage


def test_set_ai_state_transition_notifies_listeners(st):
    seen = []
    st.on_ai_state_change(lambda old, new, reason: seen.append((old, new, reason)))
    assert st.set_ai_state("THINKING", "處理對話") is True
    assert st.ai_state() == "THINKING" and seen == [("IDLE", "THINKING", "處理對話")]


def test_set_ai_state_same_state_is_noop(st):
    seen = []
    st.on_ai_state_change(lambda *a: seen.append(a))
    assert st.set_ai_state("IDLE") is False and seen == []


def test_set_ai_state_only_from_guard(st):
    st.set_ai_state("SINGING")
    assert st.set_ai_state("IDLE", only_from="TALKING") is False
    assert st.ai_state() == "SINGING"  # 不是 TALKING 就不碰
    assert st.set_ai_state("IDLE", only_from=("TALKING", "SINGING")) is True
    assert st.ai_state() == "IDLE"


def test_a_broken_listener_does_not_stop_the_transition(st):
    st.on_ai_state_change(lambda *a: 1 / 0)
    assert st.set_ai_state("TALKING") is True and st.ai_state() == "TALKING"


def test_main_logs_and_broadcasts_each_transition():
    """主程式登記的監聽：記一行日誌、廣播給後台（高頻事件不進回放歷史）。"""
    logs, events = [], []
    wd = types.SimpleNamespace(broadcast_event=lambda t, d, keep_history=True: events.append((t, d, keep_history)))
    from core import eventlog
    ns = {"log_print": logs.append, "web_dash": wd, "eventlog": eventlog, "log_swallowed": lambda: None}
    fn = next(n for n in ast.parse(_vts_src()).body if isinstance(n, ast.FunctionDef) and n.name == "_on_ai_state_change")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "x", "exec"), ns)
    ns["_on_ai_state_change"]("IDLE", "THINKING", "處理對話")
    assert len(logs) == 1 and "IDLE → THINKING" in logs[0] and "處理對話" in logs[0]
    ev = eventlog.get().recent("stage")[-1]                       # 也記進流水帳
    assert ev["text"] == "IDLE→THINKING" and ev["meta"] == {"reason": "處理對話"}
    t, d, keep = events[0]
    assert t == "system_state_update" and keep is False
    assert d["ai_state"] == "thinking" and d["prev"] == "idle"
    assert "stage.on_ai_state_change(_on_ai_state_change)" in _vts_src()


def test_nobody_keeps_their_own_copy_of_the_state():
    """主程式、鋼琴都不准再留一份 AI 狀態或唱歌旗（鋼琴以前自己一份，看不到主程式的 TALKING）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("vts_7L_test.py", os.path.join("services", "piano_engine.py")):
        src = open(os.path.join(root, rel), encoding="utf-8").read()
        assert "current_ai_state" not in src, rel
        top = [t.id for n in ast.parse(src).body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        assert "IS_SINGING_ACTIVE" not in top, rel


def test_singing_and_talking_come_from_one_place(st, monkeypatch):
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", False)
    st.register_singing_probe(lambda: acp.IS_SINGING_ACTIVE)
    assert not st.singing() and not st.talking()
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", True)
    assert st.singing() and st.talking() and st.voice_out()
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", False)
    st.IS_MP3_PLAYING = True                    # 在播 TTS：聲音在出來
    assert st.voice_out() and st.talking() and not st.singing()
    st.IS_MP3_PLAYING = False
    st.set_ai_state("TALKING")                  # 狀態先切、第一段聲音還在合成：也算在講
    assert st.talking() and not st.voice_out()


def test_after_talking_she_goes_back_to_what_is_on_stage():
    """講完話回到台上的狀態：以前播完一律設 IDLE，彈琴時狀態一直是 IDLE（2026-10-26）。"""
    src = _vts_src()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_state_after_talking")
    pe = types.SimpleNamespace(is_piano_active=False)
    ns = {"pe": pe, "is_singing_active": lambda: False}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "x", "exec"), ns)
    assert ns["_state_after_talking"]() == "IDLE"
    pe.is_piano_active = True
    assert ns["_state_after_talking"]() == "PIANO"
    ns["is_singing_active"] = lambda: True
    assert ns["_state_after_talking"]() == "SINGING"
    assert src.count("set_ai_state(_state_after_talking()") == 6   # 語音被取消、合成錯誤也回台上的狀態（2026-10-31 Fable 審查）


def test_pipeline_routes_state_through_core(st):
    acp._core_set_ai_state("SINGING", "測試")
    assert st.ai_state() == "SINGING"
    acp._core_set_ai_state("IDLE", "測試", only_from="TALKING")
    assert st.ai_state() == "SINGING"
    acp._core_set_ai_state("IDLE", "測試", only_from="SINGING")
    assert st.ai_state() == "IDLE"


def test_broadcast_without_history_keeps_replay(monkeypatch):
    import services.web_dashboard as web_dash
    monkeypatch.setattr(web_dash, "RECENT_EVENTS", [])
    monkeypatch.setattr(web_dash, "CONNECTED_CLIENTS", set())
    web_dash.broadcast_event("system_state_update", {"ai_state": "talking"}, keep_history=False)
    assert web_dash.RECENT_EVENTS == []
    web_dash.broadcast_event("chat_sent", {"text": "hi"})
    assert [e["type"] for e in web_dash.RECENT_EVENTS] == ["chat_sent"]


def test_wait_change_wakes_on_a_change_and_times_out_otherwise(st):
    """等她講完、等看板留言：以前每 0.2～1 秒醒來看一次，現在舞台一變就叫醒（2026-10-26）。"""
    import asyncio
    import time

    async def go():
        t0 = time.time()
        assert await st.wait_change(0.2) is False and time.time() - t0 >= 0.19   # 沒變：等滿
        waiter = asyncio.ensure_future(st.wait_change(5.0))
        await asyncio.sleep(0.05)
        st.set_ai_state("TALKING")                                              # 換狀態就叫醒
        assert await waiter is True
        waiter = asyncio.ensure_future(st.wait_change(5.0))
        await asyncio.sleep(0.05)
        st.stop_playback()                                                      # 停播也叫醒
        assert await waiter is True
        waiter = asyncio.ensure_future(st.wait_change(5.0))
        await asyncio.sleep(0.05)
        import threading
        threading.Thread(target=st.notify_change).start()                       # 別的執行緒通知也行
        assert await waiter is True
        assert not st._WAITERS                                                  # 等完都清掉
    asyncio.run(go())
