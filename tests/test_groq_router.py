# -*- coding: utf-8 -*-
"""core/groq_router.py 純函式測試（不打網路）"""
import inspect
from types import SimpleNamespace

from conftest import ROOT  # noqa: F401  (確保 sys.path)
from core import groq_router as gr


class _FakeStream:
    """Groq 串流的替身：一塊一塊吐，gaps[i] 是第 i 塊之前要等幾秒。"""

    def __init__(self, pieces, gaps=(), finish="stop"):
        self.pieces, self.gaps, self.finish, self.closed = list(pieces), list(gaps), finish, False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        import asyncio
        for i, p in enumerate(self.pieces):
            if i < len(self.gaps) and self.gaps[i]:
                await asyncio.sleep(self.gaps[i])
            last = i == len(self.pieces) - 1
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p),
                                                           finish_reason=self.finish if last else None)],
                                  usage=None, x_groq=SimpleNamespace(usage=SimpleNamespace(total_tokens=7)) if last else None)

    async def close(self):
        self.closed = True


def _fake_reply(kw, text):
    """非串流照舊回整包；串流就一個字一塊吐。"""
    if kw.get("stream"):
        return _FakeStream(list(text) or [""])
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None), finish_reason="stop")],
                           usage=SimpleNamespace(total_tokens=1))


# ── 模型梯隊 ────────────────────────────────────────────────────────────────
def test_default_model_ladder_nonempty_and_unique():
    ladder = gr.DEFAULT_MODEL_LADDER
    assert isinstance(ladder, list) and ladder, "梯隊不可為空"
    assert all(isinstance(m, str) and m for m in ladder), "梯隊元素須為非空字串"
    assert len(set(ladder)) == len(ladder), "梯隊不可有重複模型"


# ── 工具名安全化 ───────────────────────────────────────────────────────────
def test_wire_name_sanitizes_dotted_tool_name():
    assert gr._wire_name("pe.play_virtual_piano") == "pe_play_virtual_piano"
    assert gr._wire_name("search_google") == "search_google"
    assert gr._wire_name("a-b_c.9") == "a-b_c_9"
    # OpenAI 規範：只能 [A-Za-z0-9_-]
    import re
    safe = gr._wire_name("ns.複雜 工具/名")
    assert re.fullmatch(r"[A-Za-z0-9_-]+", safe), f"仍含非法字元: {safe}"
    assert gr._wire_name("") == ""


# ── 工具宣告轉換（三種輸入格式 → OpenAI wire）──────────────────────────────
PROJECT_TOOL = {
    "type": "function",
    "name": "pe.play_virtual_piano",
    "description": "演奏鋼琴曲目",
    "parameters": {
        "type": "object",
        "properties": {"song_name": {"type": "string", "description": "歌名"}},
        "required": ["song_name"],
    },
}


def test_to_openai_tools_from_project_format():
    out = gr.to_openai_tools([PROJECT_TOOL])
    assert len(out) == 1
    wire = out[0]
    assert wire["type"] == "function"
    fn = wire["function"]
    assert fn["name"] == "pe.play_virtual_piano"      # 原名保留（安全化在 groq_chat 內做）
    assert fn["description"] == "演奏鋼琴曲目"
    assert fn["parameters"]["properties"]["song_name"]["type"] == "string"
    assert fn["parameters"]["required"] == ["song_name"]


def test_to_openai_tools_accepts_wire_format_passthrough():
    wire_in = {"type": "function", "function": {"name": "stop_virtual_piano", "description": "停", "parameters": {}}}
    out = gr.to_openai_tools([wire_in])
    assert out[0]["function"]["name"] == "stop_virtual_piano"
    # 空參數要補上合法預設，避免 Groq 400
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_to_openai_tools_handles_empty_and_none_entries():
    assert gr.to_openai_tools(None) == []
    assert gr.to_openai_tools([]) == []
    assert gr.to_openai_tools([None, {}, {"name": ""}]) == []


def test_to_openai_tools_flattens_gemini_function_declarations():
    decl = SimpleNamespace(name="search_google", description="搜尋",
                           parameters={"type": "object", "properties": {"query": {"type": "string"}}})
    tool = SimpleNamespace(function_declarations=[decl])
    out = gr.to_openai_tools([tool])
    assert [w["function"]["name"] for w in out] == ["search_google"]
    assert out[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_schema_to_json_nested_dict():
    schema = {"type": "object",
              "properties": {"a": {"type": "string", "description": "x",
                                   "properties": {"deep": {"type": "integer"}}}},
              "required": ["a"]}
    out = gr._schema_to_json(schema)
    assert out["type"] == "object"
    assert out["required"] == ["a"]
    assert out["properties"]["a"]["properties"]["deep"]["type"] == "integer"


# ── 環境變數讀取（惰性、可覆寫）────────────────────────────────────────────
def test_load_keys_splits_on_comma_space_semicolon(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", "k1,k2 k3;k4\nk5")
    assert gr._load_keys() == ["k1", "k2", "k3", "k4", "k5"]
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    assert gr._load_keys() == []


def test_load_ladder_default_and_override(monkeypatch):
    monkeypatch.delenv("GROQ_TEXT_MODELS", raising=False)
    assert gr._load_ladder() == gr.DEFAULT_MODEL_LADDER
    monkeypatch.setenv("GROQ_TEXT_MODELS", "m1, m2")
    assert gr._load_ladder() == ["m1", "m2"]


def test_rpm_limit_parsing(monkeypatch):
    monkeypatch.setenv("GROQ_REQUESTS_PER_MINUTE", "20")
    assert gr._rpm_limit() == 20
    monkeypatch.setenv("GROQ_REQUESTS_PER_MINUTE", "")
    assert gr._rpm_limit() == 0            # 0/未設 = 不限流
    monkeypatch.setenv("GROQ_REQUESTS_PER_MINUTE", "abc")
    assert gr._rpm_limit() == 0            # 非法值不炸、視為不限
    monkeypatch.setenv("GROQ_REQUESTS_PER_MINUTE", "-3")
    assert gr._rpm_limit() == 0


# ── GroqResponse 相容殼（呼叫端只看 .text / .function_calls）────────────────
def _make_resp(**kw):
    """依實際簽名 (text, function_calls, raw, model) 建構相容殼"""
    params = inspect.signature(gr.GroqResponse).parameters
    data = {"text": "", "function_calls": [], "raw": None, "model": "test-model"}
    data.update(kw)
    data = {k: v for k, v in data.items() if k in params}
    return gr.GroqResponse(**data)


def test_groqresponse_text_and_truthiness():
    r = _make_resp(text="嗨")
    assert r.text == "嗨"
    assert bool(r) is True
    empty = _make_resp()
    assert bool(empty) is False


# ── Gemini contents → OpenAI messages（多模態要交回 Gemini）─────────────────


def test_groq_chat_gives_up_at_the_total_deadline(monkeypatch):
    """單次逾時之外要有總時限：梯隊 × 26 把金鑰全卡住時，舊碼最壞好幾分鐘才回 None（2026-10-25 健檢）。"""
    import asyncio
    import time as _t
    calls = []

    class _Slow:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    calls.append(kw["model"])
                    await asyncio.sleep(5)

    monkeypatch.setattr(gr, "_get_clients", lambda: [_Slow() for _ in range(26)])
    monkeypatch.setattr(gr, "GROQ_KEYS", [f"k{i}" for i in range(26)])
    monkeypatch.setattr(gr, "MODEL_LADDER", ["m1", "m2", "m3"])

    async def keep(ladder):
        return ladder
    monkeypatch.setattr(gr, "_filter_unavailable", keep)
    monkeypatch.setattr(gr, "_log", lambda *a: None)
    t0 = _t.monotonic()
    r = asyncio.run(gr.groq_chat([{"role": "user", "content": "hi"}], timeout=0.2, total_timeout=0.7))
    assert r is None
    assert _t.monotonic() - t0 < 1.5 and len(calls) <= 5


def test_clients_share_one_connection_pool():
    """每把金鑰各建一個 AsyncGroq 要各載一次 SSL 設定：26 把 6 秒，而且是在第一次呼叫時同步建、整個程式凍住
    （2026-10-26 量的）。共用一個 HTTP 連線池。"""
    import core.groq_router as gr
    cs = gr.make_async_clients(["k1", "", "k2", "k3"])
    assert len(cs) == 3
    assert cs[0]._client is cs[1]._client is cs[2]._client
    assert [c.api_key for c in cs] == ["k1", "k2", "k3"]


def test_empty_reply_moves_to_the_next_model_and_gpt_oss_gets_low_reasoning(monkeypatch):
    """gpt-oss 不設 reasoning_effort 會想到 max_tokens 用完、回空字串；空回覆以前換下一把金鑰打同一個模型，
    把金鑰輪完才換模型（2026-10-27 實測）。"""
    import asyncio
    from types import SimpleNamespace
    calls = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    calls.append(kw)
                    text = "" if kw["model"].startswith("openai/gpt-oss") else "好喔"
                    return _fake_reply(kw, text)

    monkeypatch.setattr(gr, "_get_clients", lambda: [_Client() for _ in range(5)])
    monkeypatch.setattr(gr, "GROQ_KEYS", [f"k{i}" for i in range(5)])

    async def keep(ladder):
        return ladder
    monkeypatch.setattr(gr, "_filter_unavailable", keep)
    monkeypatch.setattr(gr, "_log", lambda *a: None)
    r = asyncio.run(gr.groq_chat([{"role": "user", "content": "hi"}], models=["openai/gpt-oss-120b", "qwen/qwen3.8-27b"],
                                 max_tokens=100))
    assert r.text == "好喔" and [c["model"] for c in calls] == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
    assert calls[0]["extra_body"] == {"reasoning_effort": "low"} and calls[0]["max_completion_tokens"] == 100 + gr.REASONING_EXTRA_TOKENS
    assert "extra_body" not in calls[1] and calls[1]["max_completion_tokens"] == 100
    assert not any("max_tokens" in c for c in calls)   # 舊名 Groq 標示淘汰
    assert "allam-2-7b" not in gr.DEFAULT_MODEL_LADDER


def test_token_limit_is_capped_at_what_the_model_can_generate(monkeypatch):
    """超過模型一次能生的上限，Groq 直接回 400（2026-10-30 實測 qwen3.8-27b 上限 16384）。"""
    import asyncio
    from types import SimpleNamespace
    calls = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    calls.append(kw)
                    return _fake_reply(kw, "好")

    monkeypatch.setattr(gr, "_get_clients", lambda: [_Client()])
    monkeypatch.setattr(gr, "GROQ_KEYS", ["k0"])
    monkeypatch.setitem(gr._models_cache, "caps", {"qwen/qwen3.8-27b": 16384})
    monkeypatch.setattr(gr, "_log", lambda *a: None)
    asyncio.run(gr.groq_chat([{"role": "user", "content": "hi"}], model="qwen/qwen3.8-27b", max_tokens=50000))
    asyncio.run(gr.groq_chat([{"role": "user", "content": "hi"}], model="qwen/qwen3.8-27b", max_tokens=300))
    assert [c["max_completion_tokens"] for c in calls] == [16384, 300]


class _GroqError(Exception):
    def __init__(self, status, msg):
        super().__init__(f"Error code: {status} - {msg}")
        self.status_code = status


def _failing_clients(monkeypatch, fail):
    """fail(金鑰序號, 模型) 回例外就丟、回 None 就正常回「好」；記下每次 (金鑰序號, 模型)。"""
    import asyncio
    from types import SimpleNamespace
    calls = []

    def make(i):
        class _C:
            class chat:
                class completions:
                    @staticmethod
                    async def create(**kw):
                        calls.append((i, kw["model"]))
                        err = fail(i, kw["model"])
                        if err:
                            raise err
                        return _fake_reply(kw, "好")
        return _C()

    clients = [make(i) for i in range(4)]
    monkeypatch.setattr(gr, "_get_clients", lambda: clients)
    monkeypatch.setattr(gr, "GROQ_KEYS", [f"k{i}" for i in range(4)])
    monkeypatch.setattr(gr, "_call_step", -1)   # 第一次從 k0 開始

    async def keep(ladder):
        return ladder
    monkeypatch.setattr(gr, "_filter_unavailable", keep)
    monkeypatch.setattr(gr, "_log", lambda *a: None)
    gr.reset()
    ask = lambda: asyncio.run(gr.groq_chat([{"role": "user", "content": "hi"}], models=["qwen/qwen3.8-27b", "openai/gpt-oss-20b"]))
    return calls, ask


def test_too_large_request_moves_to_the_next_model_without_benching_any_key(monkeypatch):
    """2026-10-30 實測：記憶濃縮塞 20000 字，qwen 回 413（輸入每分鐘 7000 token）。以前當限流：每把都撞一次、
    全部冷卻 30 秒，Groq 整個停擺。"""
    big = _GroqError(413, "Request too large for model `qwen/qwen3.8-27b` ... (ITPM): Limit 7000, Requested 13325")
    calls, ask = _failing_clients(monkeypatch, lambda i, m: big if m.startswith("qwen") else None)
    r = ask()
    assert r.text == "好" and calls == [(0, "qwen/qwen3.8-27b"), (0, "openai/gpt-oss-20b")]
    assert not gr._key_cooldown and not gr._model_cooldown


def test_rate_limit_benches_only_that_key_for_that_model_for_as_long_as_groq_says(monkeypatch):
    """每把金鑰是各自的組織，額度一個模型一份：一把撞限流，別把、別的模型照用。"""
    import time
    limited = _GroqError(429, "Rate limit reached ... requests per day (RPD): Limit 1000, Used 1000. Please try again in 7m12s.")
    calls, ask = _failing_clients(monkeypatch, lambda i, m: limited if i == 0 else None)
    r = ask()
    assert r.text == "好" and calls == [(0, "qwen/qwen3.8-27b"), (1, "qwen/qwen3.8-27b")]
    assert not gr._model_cooldown and set(gr._key_cooldown) == {("k0", "qwen/qwen3.8-27b")}
    assert 7 * 60 + 10 < gr._key_cooldown[("k0", "qwen/qwen3.8-27b")] - time.time() <= 7 * 60 + 12
    assert gr.is_available()


def test_bad_request_is_not_mistaken_for_a_retired_model(monkeypatch):
    """400 的訊息裡常有 model 和 invalid（例如生成上限給太大），以前會被當成模型下架、整台冷卻 10 分鐘。"""
    bad = _GroqError(400, "{'message': '`max_completion_tokens` must be less than or equal to `16384` ... for this model', "
                          "'type': 'invalid_request_error'}")
    calls, ask = _failing_clients(monkeypatch, lambda i, m: bad if m.startswith("qwen") else None)
    assert ask().text == "好" and calls == [(0, "qwen/qwen3.8-27b"), (0, "openai/gpt-oss-20b")]
    assert not gr._model_cooldown and not gr._key_cooldown


def test_missing_model_is_benched_for_ten_minutes(monkeypatch):
    gone = _GroqError(404, "The model `qwen/qwen3.8-27b` does not exist or you do not have access to it. model_not_found")
    calls, ask = _failing_clients(monkeypatch, lambda i, m: gone if m.startswith("qwen") else None)
    assert ask().text == "好"
    assert set(gr._model_cooldown) == {"qwen/qwen3.8-27b"}
    ask()
    assert calls[-1][1] == "openai/gpt-oss-20b" and sum(1 for c in calls if c[1].startswith("qwen")) == 1


def test_retry_wait_is_read_from_groqs_message():
    for text, want in [("Please try again in 1m26.4s.", 86.4), ("try again in 3.75s", 3.75),
                       ("try again in 2h3m0s", 7380.0), ("try again in 120ms", 1.0), ("no hint", 30.0)]:
        assert abs(gr._retry_after(Exception(text), text) - want) < 1e-6, text


def _stream_clients(monkeypatch, plan):
    """plan(金鑰序號, 模型) 回一個 _FakeStream；記下每次 (金鑰序號, 模型, 有沒有要串流)。"""
    calls, streams = [], []

    def make(i):
        class _C:
            class chat:
                class completions:
                    @staticmethod
                    async def create(**kw):
                        calls.append((i, kw["model"], kw.get("stream")))
                        s = plan(i, kw["model"])
                        streams.append(s)
                        return s
        return _C()

    clients = [make(i) for i in range(4)]
    monkeypatch.setattr(gr, "_get_clients", lambda: clients)
    monkeypatch.setattr(gr, "GROQ_KEYS", [f"k{i}" for i in range(4)])
    monkeypatch.setattr(gr, "_call_step", -1)
    monkeypatch.setattr(gr, "FIRST_CHUNK_SEC", 0.3)
    monkeypatch.setattr(gr, "STALL_SEC", 0.2)

    async def keep(ladder):
        return ladder
    monkeypatch.setattr(gr, "_filter_unavailable", keep)
    logs = []
    monkeypatch.setattr(gr, "_log", logs.append)
    gr.reset()
    return calls, streams, logs


def _ask(**kw):
    import asyncio
    return asyncio.run(gr.groq_chat([{"role": "user", "content": "hi"}],
                                    models=["qwen/qwen3.8-27b", "openai/gpt-oss-20b"], **kw))


def test_text_replies_come_by_stream_and_are_put_back_together(monkeypatch):
    calls, streams, _ = _stream_clients(monkeypatch, lambda i, m: _FakeStream(["你", "好", "呀"]))
    r = _ask()
    assert r.text == "你好呀" and r.model == "qwen/qwen3.8-27b"
    assert calls == [(0, "qwen/qwen3.8-27b", True)] and streams[0].closed


def test_a_stall_mid_reply_is_noticed_quickly_and_another_key_takes_over(monkeypatch):
    """2026-10-30 老爸：卡了要馬上知道，不要以為她還在跑。時限 10 秒，卡住 0.2 秒就換。"""
    import time
    stuck = lambda i, m: _FakeStream(["你", "好"], gaps=[0, 5]) if i == 0 else _FakeStream(["好", "喔"])
    calls, streams, logs = _stream_clients(monkeypatch, stuck)
    t = time.monotonic()
    r = _ask(timeout=10.0)
    assert r.text == "好喔" and time.monotonic() - t < 2.0
    assert [c[0] for c in calls] == [0, 1] and streams[0].closed
    assert any("卡住" in line and "換一把金鑰" in line for line in logs)


def test_no_first_chunk_is_a_stall_too(monkeypatch):
    calls, _, logs = _stream_clients(monkeypatch, lambda i, m: _FakeStream(["好"], gaps=[5]) if i == 0 else _FakeStream(["嗨"]))
    assert _ask(timeout=10.0).text == "嗨"
    assert any("沒吐出第一塊" in line for line in logs)


def test_a_model_that_stalls_twice_is_dropped_for_the_next_one(monkeypatch):
    plan = lambda i, m: _FakeStream(["好"], gaps=[5]) if m.startswith("qwen") else _FakeStream(["換", "人"])
    calls, _, logs = _stream_clients(monkeypatch, plan)
    r = _ask(timeout=10.0)
    assert r.text == "換人" and [c[1] for c in calls] == ["qwen/qwen3.8-27b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
    assert any("換下一個模型" in line for line in logs)


def test_slow_but_steady_reply_is_not_cut_off(monkeypatch):
    """一直有在吐，只是整段比卡住的門檻久：不算卡住。"""
    calls, _, _ = _stream_clients(monkeypatch, lambda i, m: _FakeStream(list("一二三四五六"), gaps=[0.1] * 6))
    assert _ask(timeout=10.0).text == "一二三四五六" and len(calls) == 1


def test_the_callers_overall_time_limit_still_holds(monkeypatch):
    """呼叫端給的時限比卡住門檻短（例如舞台判斷 2 秒）：照舊是逾時，不是卡住。"""
    calls, _, logs = _stream_clients(monkeypatch, lambda i, m: _FakeStream(["好"], gaps=[5]))
    assert _ask(timeout=0.25, total_timeout=0.6) is None
    assert not any("卡住" in line or "第一塊" in line for line in logs), logs
