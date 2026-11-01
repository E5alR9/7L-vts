# -*- coding: utf-8 -*-
"""承諾追蹤：她答應要做、卻沒真的去做就提醒（core/promise_check，2026-11-01）。"""
import ast
import asyncio
import time

import core.promise_check as pc
from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE


def test_cheap_hint_filter():
    for s in ("等時間到了我一定會盯著你喝水", "我再幫你設一次", "好，我等一下唱晴天給你聽", "到時候我叫你起床"):
        assert pc.worth_checking(s), s
    for s in ("哈哈你好好笑", "老爸辛苦了", "[EXPRESSION: 我會] 晚安"):
        assert not pc.worth_checking(s), s


def test_parse_and_nudge_text():
    got = pc.parse('{"promise": true, "action": "到時候提醒喝水", "missing": "幾分鐘後"}')
    assert got == {"action": "到時候提醒喝水", "missing": "幾分鐘後"}
    assert pc.parse('{"promise": false, "action": "", "missing": ""}') is None and pc.parse("看不懂") is None
    t = pc.nudge_text("時間到了我會盯著你喝水", got)
    assert "到時候提醒喝水" in t and "先問老爸" in t and "invoke_subagent" in t


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _ns(action_ts=0.0, found=None):
    slips = []

    async def find(said):
        return found
    ns = {"promise_check": type("P", (), {"worth_checking": staticmethod(pc.worth_checking), "WAIT_SEC": 0.01,
                                          "find_promise": staticmethod(find), "nudge_text": staticmethod(pc.nudge_text)}),
          "asyncio": asyncio, "time": time, "_LAST_ACTION_TS": action_ts, "_AWAITING_RESULTS": {},
          "_RUNNING_SUBAGENT_TASKS": set(), "is_singing_active": lambda: False, "IS_SLEEPING": False,
          "_PROMISE_NUDGE": {"ts": 0.0}, "PROMISE_NUDGE_GAP_SEC": 60.0, "log_print": lambda *a: None,
          "send_brain_slip": slips.append, "_owner_name": lambda: "老爸"}
    exec(compile(ast.Module(body=[_fn("_check_promise")], type_ignores=[]), "x", "exec"), ns)
    return ns, slips


def test_promise_without_action_gets_one_nudge():
    found = {"action": "到時候提醒喝水", "missing": "幾分鐘後"}
    ns, slips = _ns(found=found)
    asyncio.run(ns["_check_promise"]("時間到了我一定會盯著你喝水", time.time()))
    assert len(slips) == 1 and "到時候提醒喝水" in slips[0]
    asyncio.run(ns["_check_promise"]("我再幫你設一次", time.time()))       # 60 秒內不再追
    assert len(slips) == 1


def test_no_nudge_when_she_actually_did_something_or_it_is_not_a_promise():
    found = {"action": "設計時器", "missing": ""}
    ns, slips = _ns(action_ts=time.time(), found=found)                   # 說的時候前後有叫工具
    asyncio.run(ns["_check_promise"]("我來幫你設計時器", time.time()))
    assert slips == []
    ns, slips = _ns(found=None)                                           # Groq 說不是承諾
    asyncio.run(ns["_check_promise"]("我會乖乖陪著你", time.time()))
    assert slips == []
    ns, slips = _ns(found=found)                                          # 字比對就不像：連 Groq 都不問
    asyncio.run(ns["_check_promise"]("哈哈好喔", time.time()))
    assert slips == []


def test_wiring():
    assert "spawn(_check_promise(spoken, LAST_SAY_TS))" in MAIN
    assert "_note_action()   # 承諾追蹤看這個" in ast.get_source_segment(MAIN, _fn("execute_tool_dispatch"))
