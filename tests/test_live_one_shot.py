# -*- coding: utf-8 -*-
"""Live API 問一句拿一句（2026-10-25 收斂）：畫面哨兵、發言哨兵以前各抄一份
「挑 key → 連線 → 送 → 收轉寫 → 限流記冷卻」，現在共用 core.llm_engine.live_one_shot。"""
import ast
import asyncio
import os
import re
from types import SimpleNamespace

import pytest

from conftest import ROOT
import core.llm_engine as le


def _content(text=None, done=False):
    return SimpleNamespace(output_transcription=SimpleNamespace(text=text) if text else None,
                           turn_complete=done, generation_complete=False)


class _Session:
    def __init__(self, replies, log, hang=False):
        self.replies, self.log, self.hang = replies, log, hang

    async def send_realtime_input(self, **kw):
        self.log.append(("send", sorted(kw)))

    async def receive(self):
        if self.hang:
            await asyncio.sleep(10)
        for r in self.replies:
            yield SimpleNamespace(server_content=r)


class _Connect:
    def __init__(self, behavior, log):
        self.behavior, self.log = behavior, log

    async def __aenter__(self):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        if self.behavior == "hang":
            return _Session([], self.log, hang=True)
        return _Session([_content(t) for t in self.behavior] + [_content(done=True)], self.log)

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def fake_live(monkeypatch):
    """script: key -> 回覆片段 list ／ Exception ／ "hang"。回 (script, log)。"""
    script, log = {}, []

    def client(api_key):
        def connect(model, config):
            log.append(("connect", api_key, model))
            return _Connect(script[api_key], log)
        return SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect)))
    monkeypatch.setattr(le, "genai", SimpleNamespace(Client=client))
    monkeypatch.setattr(le, "GEMINI_KEYS", [])
    monkeypatch.setattr(le, "log_print", lambda *a, **k: None)
    le._KEY_COOLDOWN.clear()
    yield script, log
    le._KEY_COOLDOWN.clear()


def _run(coro):
    return asyncio.run(coro)


def test_returns_transcript_and_sends_image_first(fake_live):
    script, log = fake_live
    script["K1"] = ["[LOOK_", "SERIOUS]"]
    out = _run(le.live_one_shot("sys", "看畫面", ["K1"], image_jpeg=b"jpg"))
    assert out == "[LOOK_SERIOUS]"
    assert [e for e in log if e[0] == "send"] == [("send", ["video"]), ("send", ["text"])]


def test_rate_limited_key_is_cooled_and_next_key_answers(fake_live):
    script, log = fake_live
    script["K1"] = Exception("429 RESOURCE_EXHAUSTED retry in 20s")
    script["K2"] = ["[SILENCE]"]
    assert _run(le.live_one_shot("sys", "q", ["K1", "K2"])) == "[SILENCE]"
    assert le.key_cooling("K1", le.LIVE_ONE_SHOT_MODEL)
    log.clear()
    _run(le.live_one_shot("sys", "q", ["K1", "K2"]))                 # 冷卻中的 K1 直接跳過
    assert [e[1] for e in log if e[0] == "connect"] == ["K2"]


def test_unaccepted_answer_asks_next_key(fake_live):
    script, _ = fake_live
    script["K1"] = ["今天天氣真好"]
    script["K2"] = ["[NO_CHANGE]"]
    out = _run(le.live_one_shot("sys", "q", ["K1", "K2"], accept=lambda t: "NO_CHANGE" in t))
    assert out == "[NO_CHANGE]"


def test_timeout_moves_on_and_all_fail_returns_empty(fake_live):
    script, _ = fake_live
    script["K1"] = "hang"
    script["K2"] = []                                                    # 連上但沒回字
    script["K3"] = Exception("connection reset")
    assert _run(le.live_one_shot("sys", "q", ["K1", "K2", "K3"], timeout=0.1)) == ""
    assert le._KEY_COOLDOWN == {}                                       # 不是限流就不冷卻


def test_max_keys_limits_attempts(fake_live):
    script, log = fake_live
    for k in ("K1", "K2", "K3"):
        script[k] = Exception("boom")
    _run(le.live_one_shot("sys", "q", ["K1", "K2", "K3"], max_keys=2))
    assert [e[1] for e in log if e[0] == "connect"] == ["K1", "K2"]


# —— 主程式兩個哨兵改用共用版之後的判讀 ——

def _sentries(answer):
    src = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    calls = []

    async def fake_one_shot(system_text, prompt, pool, **kw):
        calls.append((prompt, kw))
        accept = kw.get("accept")
        return answer if (answer and (accept is None or accept(answer))) else ""
    ns = {"live_one_shot": fake_one_shot, "re": re, "KEYS_VISION": ["V"], "KEYS_AUDIENCE_LIVE": ["A"],
          "GEMINI_KEYS": ["G"]}
    for n in ast.parse(src).body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name in (
                "check_screen_change_via_live_api", "judge_subconscious_intent_via_live_api"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
    return ns, calls


def test_screen_sentry_reads_decision():
    ns, calls = _sentries("[LOOK_SERIOUS]")
    assert _run(ns["check_screen_change_via_live_api"](b"x" * 2000, "寫程式"))
    assert calls[0][1]["image_jpeg"] == b"x" * 2000
    assert not _run(ns["check_screen_change_via_live_api"](b"x" * 10, "寫程式"))   # 太小的圖不問
    assert len(calls) == 1
    ns, _ = _sentries("[NO_CHANGE]")
    assert not _run(ns["check_screen_change_via_live_api"](b"x" * 2000, "寫程式"))
    ns, _ = _sentries("隨便講講")                                        # 答非所問＝沒變化
    assert not _run(ns["check_screen_change_via_live_api"](b"x" * 2000, "寫程式"))


def test_intent_sentry_parses_decision():
    ns, _ = _sentries("[SPEAK: target=老爸, focus=點歌, song=晴天]")
    got = _run(ns["judge_subconscious_intent_via_live_api"]("記憶", "老爸：唱晴天"))
    assert got == {"should_speak": True, "target": "老爸", "focus": "點歌", "song": "晴天",
                   "raw": "[SPEAK: target=老爸, focus=點歌, song=晴天]"}
    ns, _ = _sentries("[SILENCE]")
    assert _run(ns["judge_subconscious_intent_via_live_api"]("記憶", "咳嗽"))["should_speak"] is False
    ns, _ = _sentries("")                                               # Live 全忙：放行給主腦判斷
    assert _run(ns["judge_subconscious_intent_via_live_api"]("記憶", "x"))["raw"] == "FALLBACK_ALLOW"


def test_live_one_shot_not_copied_back_into_main():
    src = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    for n in ast.parse(src).body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name in (
                "check_screen_change_via_live_api", "judge_subconscious_intent_via_live_api"):
            assert "live.connect" not in ast.get_source_segment(src, n)
