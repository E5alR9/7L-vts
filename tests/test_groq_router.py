# -*- coding: utf-8 -*-
"""core/groq_router.py 純函式測試（不打網路）"""
import inspect
from types import SimpleNamespace

from conftest import ROOT  # noqa: F401  (確保 sys.path)
from core import groq_router as gr


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
def test_contents_to_messages_text_only():
    contents = [
        SimpleNamespace(role="user", parts=[SimpleNamespace(text="你好"), SimpleNamespace(text="在嗎")]),
        SimpleNamespace(role="model", parts=[SimpleNamespace(text="在")]),
    ]
    msgs = gr.contents_to_messages(contents)
    assert msgs == [
        {"role": "user", "content": "你好\n在嗎"},
        {"role": "assistant", "content": "在"},
    ]


def test_contents_to_messages_returns_none_for_multimodal():
    # 含圖片 → 回 None（讓呼叫端退回 Gemini）
    img = [SimpleNamespace(role="user", parts=[
        SimpleNamespace(text="看這張", inline_data=SimpleNamespace(mime_type="image/png", data=b"..."))])]
    assert gr.contents_to_messages(img) is None
    # 含 function_call 軌跡 → 回 None
    fc = [SimpleNamespace(role="model", parts=[SimpleNamespace(function_call=SimpleNamespace(name="x", args={}))])]
    assert gr.contents_to_messages(fc) is None
    # 空 → None
    assert gr.contents_to_messages(None) is None
    assert gr.contents_to_messages([]) is None
    # 全無文字 → None
    assert gr.contents_to_messages([SimpleNamespace(role="user", parts=[])]) is None
