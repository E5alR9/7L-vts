# -*- coding: utf-8 -*-
"""模型用量（core/usage.py，2026-10-26）：誰叫的、哪個模型、成功沒、限流、時間、token。"""
import asyncio
import types

import pytest

from core import usage


@pytest.fixture(autouse=True)
def _clean():
    usage.reset()
    yield
    usage.reset()


def test_summary_groups_by_role_and_model_within_window():
    usage.note("m1", True, role="看板哨兵", ms=100, ts=5000.0)
    usage.note("m1", False, role="看板哨兵", rate_limited=True, ms=300, ts=5100.0)
    usage.note("m2", True, role="主腦", tokens=50, ts=5200.0)
    usage.note("m1", True, role="看板哨兵", ts=1000.0)                     # 超出一小時：不算
    rows = usage.summary(3600, now=5300.0)
    assert rows[0] == {"role": "看板哨兵", "model": "m1", "calls": 2, "fails": 1, "rate_limited": 1,
                       "tokens": 0, "avg_ms": 200}
    assert rows[1]["role"] == "主腦" and rows[1]["tokens"] == 50


def test_role_comes_from_context_and_resets():
    async def low_level():
        usage.note("m", default_role="Groq")

    @usage.role_scope("REST 大腦")
    async def caller():
        await low_level()

    async def go():
        await caller()
        await low_level()                                  # 出了範圍：回到預設名字
    asyncio.run(go())
    assert [r["role"] for r in usage.summary(60)] == ["Groq", "REST 大腦"] or \
        sorted(r["role"] for r in usage.summary(60)) == ["Groq", "REST 大腦"]


def test_timed_records_success_failure_and_rate_limit():
    with usage.timed("m", role="r") as u:
        u.tokens = 7
    with usage.timed("m", role="r") as u:
        u.ok = False                                       # 回空字串之類：算失敗
    with pytest.raises(RuntimeError):
        with usage.timed("m", role="r"):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
    r = usage.summary(60)[0]
    assert (r["calls"], r["fails"], r["rate_limited"], r["tokens"]) == (3, 2, 1, 7)


def test_rest_chat_gemini_call_is_recorded_under_the_callers_role(monkeypatch):
    from core import rest_brain

    class FakeModels:
        async def generate_content(self, model, contents, config):
            return types.SimpleNamespace(function_calls=[], text="好喔", usage_metadata=types.SimpleNamespace(total_token_count=42),
                                         candidates=[types.SimpleNamespace(content=types.SimpleNamespace(
                                             parts=[types.SimpleNamespace(text="好喔", thought=False)]))])

    class FakeClient:
        def __init__(self, api_key):
            self.aio = types.SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(rest_brain.genai, "Client", FakeClient)
    monkeypatch.setattr(rest_brain, "gemini_pairs", lambda models, attempts, keys=None: [("K", "gemini-x")])

    @usage.role_scope("看畫面")
    async def call():
        return await rest_brain.rest_chat("", "看一下", models=["gemini-x"], groq_first=False)
    r = asyncio.run(call())
    assert r.text == "好喔"
    assert usage.summary(60) == [{"role": "看畫面", "model": "gemini-x", "calls": 1, "fails": 0, "rate_limited": 0,
                                  "tokens": 42, "avg_ms": usage.summary(60)[0]["avg_ms"]}]


def test_report_shape():
    usage.note("m", role="r")
    rep = usage.report(3600)
    assert rep["window_sec"] == 3600 and rep["total_since_start"] == 1 and rep["rows"][0]["role"] == "r"
