"""2026-10-24 子智能體審查修正的回歸測試：
非阻塞回報的排程（中間回應＋最後結果）、深思答案解析、NV 換模型與 404 停用、深思順序 Gemini 先、轉述保留事實、整段限時。"""
import ast
import asyncio
import os
import time
import types as pytypes

from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
TREE = ast.parse(MAIN)


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _const(name):
    return next(ast.literal_eval(n.value) for n in TREE.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name)


def _const_pattern(name):
    """re.compile(r"...") 這種模組常數：取出裡面的正則字串。"""
    return next(n.value.args[0].value for n in TREE.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == name)


def _load(*names, **ns):
    ns.setdefault("log_print", lambda *a, **k: None)
    for n in names:
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns


def test_think_reply_uses_text_after_think_not_the_thinking():
    f = _load("_extract_think_reply")["_extract_think_reply"]
    assert f("[THINK]想一下[/THINK][REPLY]辦驚喜派對[/REPLY]") == ("想一下", "辦驚喜派對")
    # 實機：Gemini 沒寫 [REPLY]，舊碼把「分析意圖：…」當答案交給主腦
    assert f("[THINK]分析意圖：老爸想幫媽媽慶生[/THINK]\n訂一束花加手寫卡片") == ("分析意圖：老爸想幫媽媽慶生", "訂一束花加手寫卡片")
    assert f("[THINK]分析意圖：老爸想幫媽媽慶生[/THINK]")[1] == ""
    assert f("[THINK]被截斷的思考")[1] == ""
    assert f("[REPLY]沒收尾的結論") == ("", "沒收尾的結論")
    assert f("沒標籤的回答") == ("", "沒標籤的回答")


def test_invoke_subagent_is_non_blocking():
    from google.genai import types
    from core.tool_schema import LIVE_API_TOOLS
    decl = LIVE_API_TOOLS[0].function_declarations[0]
    assert decl.name == "invoke_subagent" and decl.behavior == types.Behavior.NON_BLOCKING


class _FakeSession:
    def __init__(self):
        self.sent = []

    async def send_tool_response(self, function_responses):
        self.sent += function_responses


def _run_handler(cpu, nv, total_timeout=45.0, task="幫我查日圓匯率"):
    async def background_tool_executor(*a, **k):
        return cpu

    async def nv_interpret_task(*a, **k):
        if nv == "hang":
            await asyncio.sleep(10)
        return nv

    from core.hard_command import build_slip_text
    sess = _FakeSession()
    ns = _load("_handle_invoke_subagent", types=types, asyncio=asyncio, session=sess, ws_send_lock=asyncio.Lock(),
               background_tool_executor=background_tool_executor, nv_interpret_task=nv_interpret_task,
               build_slip_text=build_slip_text, _SUBAGENT_TOTAL_TIMEOUT=total_timeout,
               _SUBAGENT_VISION_TASK_RE=__import__('re').compile(_const_pattern('_SUBAGENT_VISION_TASK_RE')))
    asyncio.run(ns["_handle_invoke_subagent"]("invoke_subagent", "call-1", task))
    assert all(r.id == "call-1" for r in sess.sent)
    if cpu[0]:
        assert len(sess.sent) == 1                       # 硬指令不到 1 秒：一則就好
    else:
        # 要等副腦：先回中間回應讓她開口答應（實測主腦呼叫時不開口），結果回來再補最後一則
        assert len(sess.sent) == 2
        assert sess.sent[0].will_continue is True
        assert sess.sent[0].scheduling == types.FunctionResponseScheduling.WHEN_IDLE
        assert "答應" in sess.sent[0].response["result"]
        assert not sess.sent[1].will_continue
    return sess.sent[-1].response["result"], sess.sent[-1].scheduling


def test_hard_commands_ask_for_one_ack_without_tool_names():
    text, sched = _run_handler((True, "auto_sing_song", {"song_name": "晴天"}), None)
    assert sched == types.FunctionResponseScheduling.WHEN_IDLE
    assert "晴天" in text and "auto_sing_song" not in text
    assert "[SILENCE]" in text                           # 她已經答應過就不要再講
    text, sched = _run_handler((True, "mixed_play_sing", {"desc": "晴天＋稻香"}), None)
    assert "晴天＋稻香" in text and "mixed_play_sing" not in text


def test_dispatched_tool_result_is_silent_after_the_ack():
    _, sched = _run_handler((False, "", {}), ("tool", "[系統底層：已畫圖。]"))
    assert sched == types.FunctionResponseScheduling.SILENT


def test_results_to_say_wait_until_idle():
    for kind in ("report", "advice"):
        text, sched = _run_handler((False, "", {}), (kind, "[搜尋結果：1 美元約 159.4 日圓]"))
        assert sched == types.FunctionResponseScheduling.WHEN_IDLE
        assert "159.4" in text
    text, sched = _run_handler((False, "", {}), ("miss", ""))
    assert sched == types.FunctionResponseScheduling.WHEN_IDLE
    assert "不要自己編" in text


def test_subagent_has_a_total_time_limit():
    t = time.time()
    text, sched = _run_handler((False, "", {}), "hang", total_timeout=0.1)
    assert time.time() - t < 3
    assert sched == types.FunctionResponseScheduling.WHEN_IDLE
    assert "放棄" in text


def test_relay_text_keeps_facts():
    rule = _const("_SUBAGENT_RELAY_RULE")
    ns = _load("_subagent_report_text", "_subagent_advice_text", _SUBAGENT_RELAY_RULE=rule)
    for s in (ns["_subagent_report_text"]("", "1 美元約換 159.4 日圓"), ns["_subagent_advice_text"]("", "訂花")):
        assert "不要照唸" not in s
        assert "數字" in s and "不要自己補" in s


def _interpret(chain, calls, tool=(None, None), gemini_think=("advice", "[答案]"), nv_think=("advice", "[NV 答案]")):
    def mk(name, result):
        async def f(*a, **k):
            calls.append(name)
            if isinstance(result, Exception):
                raise result
            return result
        return f

    ns = _load("nv_interpret_task", asyncio=asyncio, resolve_subagent_chain=lambda: chain, load_prompt=lambda n: "",
               _gemini_tool_pass=mk("gemini_tool", tool), _nv_tool_pass=mk("nv_tool", tool),
               _gemini_think_pass=mk("gemini_think", gemini_think), _nv_think_pass=mk("nv_think", nv_think))
    return asyncio.run(ns["nv_interpret_task"]("想一個老媽生日的驚喜點子"))


def test_auto_thinks_with_gemini_first_and_nv_only_as_backup():
    calls = []
    assert _interpret(["gemini", "nv"], calls) == ("advice", "[答案]")
    assert calls == ["gemini_tool", "gemini_think"]
    calls = []
    assert _interpret(["gemini", "nv"], calls, gemini_think=RuntimeError("503")) == ("advice", "[NV 答案]")
    assert calls == ["gemini_tool", "gemini_think", "nv_think"]


def test_search_result_is_a_report_to_be_spoken():
    async def dispatch(*a, **k):
        return "1 美元 = 159.4 日圓"

    async def summarize(q, raw, user_role_name=""):
        return "現在 1 美元約換 159.4 日圓"

    rule = _const("_SUBAGENT_RELAY_RULE")
    ns = _load("nv_interpret_task", "_subagent_report_text", asyncio=asyncio, resolve_subagent_chain=lambda: ["gemini"],
               load_prompt=lambda n: "", execute_tool_dispatch=dispatch, summarize_search_to_speech=summarize,
               _SUBAGENT_RELAY_RULE=rule)

    async def tool_pass(*a, **k):
        return "search_google", {"query": "日圓匯率"}
    ns["_gemini_tool_pass"] = tool_pass
    kind, text = asyncio.run(ns["nv_interpret_task"]("查日圓匯率"))
    assert kind == "report" and "159.4" in text


def test_nv_model_and_404_pauses_nv():
    assert _const("_NV_SUBAGENT_MODEL") != "nvidia/nemotron-3-super-120b-a12b"   # 2026-10-24 已 404
    assert "os.getenv" not in ast.get_source_segment(MAIN, _fn("_nv_tool_pass"))  # 模型名寫死在程式，不讀 .env
    ns = _load("_nv_subagent_down", "_nv_subagent_note_error", time=time,
               _NV_SUBAGENT_DOWN_SEC=600.0, _NV_SUBAGENT_DOWN_UNTIL=0.0)
    ns["_nv_subagent_note_error"](pytypes.SimpleNamespace(status_code=429), "m")
    assert not ns["_nv_subagent_down"]()
    ns["_nv_subagent_note_error"](pytypes.SimpleNamespace(status_code=404), "m")
    assert ns["_nv_subagent_down"]()


def test_screen_task_gets_one_silent_reply():
    import re as _re
    from core.hard_command import build_slip_text

    async def never(*a, **k):
        raise AssertionError("看畫面不該跑 CPU 或副腦")

    sess = _FakeSession()
    ns = _load("_handle_invoke_subagent", types=types, asyncio=asyncio, session=sess, ws_send_lock=asyncio.Lock(),
               background_tool_executor=never, nv_interpret_task=never, build_slip_text=build_slip_text,
               _SUBAGENT_TOTAL_TIMEOUT=45.0, _SUBAGENT_VISION_TASK_RE=_re.compile(_const_pattern("_SUBAGENT_VISION_TASK_RE")))
    asyncio.run(ns["_handle_invoke_subagent"]("invoke_subagent", "c1", "看老爸螢幕上面有什麼"))
    assert len(sess.sent) == 1
    assert sess.sent[0].scheduling == types.FunctionResponseScheduling.SILENT
    assert "不要描述畫面" in sess.sent[0].response["result"]
