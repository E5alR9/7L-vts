"""REST 大腦（2026-10-26）：沒有 Live 主腦時講話用的那一次 API 呼叫。"""
import asyncio
import types as pytypes

import core.rest_brain as rb


def _resp(text="", calls=()):
    parts = [pytypes.SimpleNamespace(text=text, thought=False)] if text else []
    return pytypes.SimpleNamespace(
        candidates=[pytypes.SimpleNamespace(content=pytypes.SimpleNamespace(parts=parts))],
        function_calls=[pytypes.SimpleNamespace(name=n, args=a) for n, a in calls], text=text)


def _setup(monkeypatch, groq=None, gemini=None):
    """groq：Groq 要回的字（None＝失敗）；gemini：依序每次呼叫的結果（Exception 就丟出去）。回呼叫紀錄。"""
    log = {"groq": 0, "gemini": [], "reported": []}

    async def fake_groq(messages, **k):
        log["groq"] += 1
        return pytypes.SimpleNamespace(text=groq, function_calls=None, model="qwen") if groq else None

    results = iter(gemini or [])

    async def fake_gemini(key, model, parts, cfg, timeout):
        log["gemini"].append((key, model, len(parts), cfg.tools))
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(rb.groq_router, "groq_chat", fake_groq)
    monkeypatch.setattr(rb, "_gemini_once", fake_gemini)
    monkeypatch.setattr(rb, "report_gemini_key_error", lambda k, e, m: log["reported"].append((k, m)) or False)
    monkeypatch.setattr(rb, "key_cooling", lambda k, m: False)
    return log


def test_plain_text_goes_to_groq_first(monkeypatch):
    log = _setup(monkeypatch, groq="嗨嗨～")
    r = asyncio.run(rb.rest_chat("妳是 7L。", "小明：晚安", models=["m1"], keys=["k1"]))
    assert (r.text, r.model) == ("嗨嗨～", "Groq/qwen") and log["gemini"] == []


def test_gemini_takes_over_when_groq_fails_and_skips_a_broken_pair(monkeypatch):
    log = _setup(monkeypatch, groq=None, gemini=[RuntimeError("429 quota"), _resp("晚安呀")])
    r = asyncio.run(rb.rest_chat("妳是 7L。", "小明：晚安", models=["m1", "m2"], keys=["k1", "k2"]))
    assert r.text == "晚安呀" and len(log["gemini"]) == 2
    assert len(log["reported"]) == 1                 # 限流的那組記冷卻


def test_tools_and_audio_skip_groq_and_calls_come_back(monkeypatch):
    log = _setup(monkeypatch, groq="不該用到", gemini=[_resp("好！", [("invoke_subagent", {"action": "play_piano"})])])
    r = asyncio.run(rb.rest_chat("", "彈小星星", models=["m1"], keys=["k1"], tools=["T"], audio_wav=b"RIFF"))
    assert log["groq"] == 0
    assert r.calls == [("invoke_subagent", {"action": "play_piano"})] and r.text == "好！"
    assert log["gemini"][0][2] == 2 and log["gemini"][0][3] == ["T"]   # 文字＋聲音兩段、工具有帶


def test_empty_answers_move_on_and_all_failing_gives_none(monkeypatch):
    _setup(monkeypatch, groq=None, gemini=[_resp(""), RuntimeError("x"), RuntimeError("y")])
    assert asyncio.run(rb.rest_chat("", "嗨", models=["m"], keys=["k"], attempts=3)) is None


def test_total_timeout_gives_none(monkeypatch):
    _setup(monkeypatch, groq=None)

    async def slow(*a):
        await asyncio.sleep(5)

    monkeypatch.setattr(rb, "_gemini_once", slow)
    assert asyncio.run(rb.rest_chat("", "嗨", models=["m"], keys=["k"], total_timeout=0.2)) is None


def test_pairs_put_cooling_ones_last_and_rotate_models(monkeypatch):
    monkeypatch.setattr(rb, "key_cooling", lambda k, m: k == "hot")
    monkeypatch.setattr(rb, "sort_keys_by_load", lambda ks: sorted(ks))
    pairs = rb.gemini_pairs(["m1", "m2"], 4, keys=["hot", "a", "b"])
    assert pairs == [("a", "m1"), ("b", "m2"), ("a", "m2"), ("hot", "m1")]
    assert rb.gemini_pairs([], 3, keys=["a"]) == [] and rb.gemini_pairs(["m"], 3, keys=[]) == []
