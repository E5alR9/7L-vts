# -*- coding: utf-8 -*-
"""神態導演常駐 session：不斷不重連、壞了才重建（2026-10-11）。
主檔太重不直接 import，用 AST 抽出來跑，genai/types 用樁。"""
import ast
import asyncio
import os
from types import SimpleNamespace


def _load(fx):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)

    class _FakeSession:
        def __init__(self, fx):
            self._fx = fx
            self.sent = []

        async def send_realtime_input(self, text=None, **kw):
            if self._fx.get("send_fail"):
                raise RuntimeError("ws dead")
            self.sent.append(text)

        async def receive(self):
            if self._fx.get("recv_fail"):
                raise RuntimeError("ws dead")
            for line in self._fx.get("lines", ["[0.0s: 臉紅]", "[1.2s: 吐舌]"]):
                yield SimpleNamespace(server_content=SimpleNamespace(
                    output_transcription=SimpleNamespace(text=line + "\n"),
                    turn_complete=False, generation_complete=False))
            yield SimpleNamespace(server_content=SimpleNamespace(
                output_transcription=None, turn_complete=True, generation_complete=False))

    class _FakeCM:
        def __init__(self, fx, key):
            self._fx, self._key = fx, key

        async def __aenter__(self):
            fx["connects"] += 1
            if self._key in fx.get("enter_fail_keys", set()):
                raise RuntimeError("403 quota")
            sess = _FakeSession(self._fx)
            fx.setdefault("sessions", []).append(sess)
            return sess

        async def __aexit__(self, *a):
            fx["exits"] = fx.get("exits", 0) + 1
            return False

    class _FakeLive:
        def __init__(self, fx, key):
            self._fx, self._key = fx, key

        def connect(self, model=None, config=None):
            fx["models"] = fx.get("models", []) + [model]
            return _FakeCM(self._fx, self._key)

    class _FakeAio:
        def __init__(self, fx, key):
            self.live = _FakeLive(fx, key)

    class _FakeClient:
        def __init__(self, api_key=None):
            self._key = api_key

        @property
        def aio(self):
            return _FakeAio(fx, self._key)

    fake_genai = SimpleNamespace(Client=_FakeClient)
    fake_types = SimpleNamespace(
        Modality=SimpleNamespace(AUDIO="AUDIO"),
        AudioTranscriptionConfig=lambda **k: ("ATTC", k),
        Content=lambda **k: ("Content", k),
        Part=lambda **k: ("Part", k),
        LiveConnectConfig=lambda **k: ("CFG", k),
    )
    logs = []
    ns = {
        "usage": __import__("core.usage", fromlist=["usage"]),
        "time": __import__("time"),
        "asyncio": asyncio,
        "genai": fake_genai,
        "types": fake_types,
        "log_print": logs.append,
        "get_dynamic_live_key_candidates": lambda keys: list(keys),
        "report_gemini_key_error": lambda *a, **k: False,
        "KEYS_AUDIENCE_LIVE": [],
        "GEMINI_KEYS": ["K1", "K2", "K3"],
        "LIVE_MODEL": __import__("core.llm_engine", fromlist=["LIVE_MODEL"]).LIVE_MODEL,
        "_DIRECTOR_STATE": {"session": None, "cm": None, "key_idx": 0},
        "_DIRECTOR_LOCK": asyncio.Lock(),
        "_DIRECTOR_TIMELINE_CACHE": {},
        "_DIRECTOR_CACHE_MAX": 200,
    }
    import re as _re
    ns["re"] = _re
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name in (
                "_director_ensure_session", "_director_drop_session",
                "live_api_direct_sentence_emotions", "_director_drain_then_release"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
        if isinstance(n, ast.FunctionDef) and n.name == "_director_cache_key":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    # ensure 內調 drop：同命名空間已就位，無需重綁
    return funcs, ns, fx, logs


def test_persistent_session_reused():
    funcs, ns, fx, logs = _load({"connects": 0})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        r1 = await f("你這什麼問題啊，本少女活得好好的。", 4.0)
        r2 = await f("謝謝你的禮物，超開心的。", 3.0)
        return r1, r2

    r1, r2 = asyncio.run(go())
    assert fx["connects"] == 1  # 兩句只握手一次（舊碼兩次）
    assert r1 == [(0.0, "EXPRESSION", "臉紅"), (1.2, "EXPRESSION", "吐舌")]
    assert r2 == r1
    assert len(fx["sessions"]) == 1 and len(fx["sessions"][0].sent) == 2
    assert fx.get("models") == ["gemini-3.8-live"]


def test_broken_session_dropped_and_reconnected():
    funcs, ns, fx, logs = _load({"connects": 0})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        r1 = await f("第一句正常。", 4.0)
        fx["send_fail"] = True
        r2 = await f("第二句撞上斷線。", 4.0)
        assert ns["_DIRECTOR_STATE"]["session"] is None  # 壞 session 已丟
        fx["send_fail"] = False
        r3 = await f("第三句重連成功。", 4.0)
        return r1, r2, r3

    r1, r2, r3 = asyncio.run(go())
    assert r1 != [] and r2 == [] and r3 != []
    assert fx["connects"] == 2  # 中間只重連一次
    assert fx.get("exits", 0) >= 1  # 舊 cm 有確實 __aexit__


def test_short_text_never_connects():
    funcs, ns, fx, logs = _load({"connects": 0})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        assert await f("嗨", 4.0) == []
        assert await f("長度夠但時間太短的句子測試", 1.0) == []
        assert await f("", 5.0) == []

    asyncio.run(go())
    assert fx["connects"] == 0


def test_connect_failure_rotates_key():
    funcs, ns, fx, logs = _load({"connects": 0, "enter_fail_keys": {"K1"}})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        return await f("首連失敗要換鑰匙。", 4.0)

    r = asyncio.run(go())
    assert r != []
    assert fx["connects"] == 2  # K1 炸→K2 成
    assert ns["_DIRECTOR_STATE"]["key_idx"] == 2  # 下次從 K3 開始


# ── 結果快取（2026-10-11：同文案只導一次，按時長縮放）──────────────────────
def test_cache_key_ignores_duration():
    funcs, _, _, _ = _load({"connects": 0})
    k = funcs["_director_cache_key"]
    assert k("  你好呀  ") == k("你好呀")
    assert k("你好呀") != k("你不好呀")


def test_repeat_text_served_from_cache_rescaled():
    funcs, ns, fx, logs = _load({"connects": 0})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        r1 = await f("同樣的話講兩次，表情要對上。", 4.0)
        n_sent_after_first = len(fx["sessions"][0].sent)
        r2 = await f("同樣的話講兩次，表情要對上。", 8.0)  # 時長翻倍
        return r1, r2, n_sent_after_first

    r1, r2, n_sent = asyncio.run(go())
    assert r1 == [(0.0, "EXPRESSION", "臉紅"), (1.2, "EXPRESSION", "吐舌")]
    assert r2 == [(0.0, "EXPRESSION", "臉紅"), (2.4, "EXPRESSION", "吐舌")]  # 按比例
    assert fx["connects"] == 1
    assert len(fx["sessions"][0].sent) == n_sent == 1  # 第二次沒問大腦


def test_different_text_rederives_same_session():
    funcs, ns, fx, logs = _load({"connects": 0})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        await f("第一句不同的話。", 4.0)
        return await f("第二句完全不同的話。", 4.0)

    r = asyncio.run(go())
    assert r != []
    assert fx["connects"] == 1  # 同 session，不重連
    assert len(fx["sessions"][0].sent) == 2  # 但問了兩次


def test_empty_timeline_cached_too():
    funcs, ns, fx, logs = _load({"connects": 0, "lines": []})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        r1 = await f("大腦無感的一句話測試。", 4.0)
        r2 = await f("大腦無感的一句話測試。", 4.0)
        return r1, r2

    r1, r2 = asyncio.run(go())
    assert r1 == [] and r2 == []
    assert len(fx["sessions"][0].sent) == 1  # 空結果也記住，不白問第二次


def test_cache_evicts_oldest():
    funcs, ns, fx, logs = _load({"connects": 0})
    ns["_DIRECTOR_CACHE_MAX"] = 2
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        for i in range(3):
            await f(f"第{i}句完全不同的話內容。", 4.0)

    asyncio.run(go())
    assert len(ns["_DIRECTOR_TIMELINE_CACHE"]) == 2


def test_tail_after_generation_complete_does_not_leak_into_next_sentence():
    """2026-10-24 實機：generation_complete 後還有音訊與 turn_complete，舊碼留在連線上，
    下一句先讀到上一句的尾巴→空結果、之後整個錯位。現在背景把尾巴讀完才放鎖。"""
    funcs, ns, fx, logs = _load({"connects": 0, "gen_complete_tail": True})
    f = funcs["live_api_direct_sentence_emotions"]

    async def go():
        r1 = await f("你這什麼問題啊，本少女活得好好的。", 4.0)
        r2 = await f("謝謝你的禮物，超開心的喔喔。", 3.0)
        await asyncio.sleep(0)  # 讓背景排空任務跑完
        return r1, r2

    r1, r2 = asyncio.run(go())
    assert r1 == [(0.0, "EXPRESSION", "臉紅"), (1.2, "EXPRESSION", "吐舌")]
    assert r2 == [(0.0, "EXPRESSION", "臉紅"), (1.2, "EXPRESSION", "吐舌")]   # 舊碼這裡會是 []
    assert fx["connects"] == 1
    assert not ns["_DIRECTOR_LOCK"].locked()
