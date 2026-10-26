"""2026-10-24 子智能體審查修正的回歸測試：
非阻塞回報的排程（中間回應＋最後結果）、深思答案解析、NV 換模型與 404 停用、深思順序 Gemini 先、轉述保留事實、整段限時。"""
from types import SimpleNamespace
import ast
import asyncio
import os
import time
import types as pytypes

from google.genai import types

from core.tool_schema import resolve_tool_name

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
    ns.setdefault("usage", __import__("core.usage", fromlist=["usage"]))   # 主程式函式掛著 @usage.role_scope
    ns.setdefault("resolve_tool_name", resolve_tool_name)
    ns.setdefault("_SUBAGENT_MIRROR_TASK_RE", __import__("re").compile(_const_pattern("_SUBAGENT_MIRROR_TASK_RE")))
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


def _run_handler(cpu, nv, total_timeout=45.0, task="幫我查日圓匯率", origin="dad", targets=None, intent=None,
                 staged=(True, "auto_sing_song", {"song_name": "晴天"}), requester="", requesters=None):
    targets = [] if targets is None else targets

    requesters = [] if requesters is None else requesters

    async def run_stage_commands(cmds, **k):
        targets.append(("struct", k.get("target"), cmds))
        requesters.append(k.get("requester_name"))
        return staged

    async def background_tool_executor(*a, **k):
        targets.append(("cpu", k.get("target")))
        requesters.append(k.get("requester_name"))
        return cpu

    async def nv_interpret_task(*a, **k):
        targets.append(("nv", k.get("target")))
        requesters.append(k.get("requester_name"))
        if nv == "hang":
            await asyncio.sleep(10)
        return nv

    from core.hard_command import build_slip_text, structured_stage_command
    sess = _FakeSession()
    ns = _load("_run_subagent_task", "_handle_invoke_subagent", types=types, asyncio=asyncio, session=sess,
               ws_send_lock=asyncio.Lock(),
               background_tool_executor=background_tool_executor, nv_interpret_task=nv_interpret_task,
               build_slip_text=build_slip_text, _SUBAGENT_TOTAL_TIMEOUT=total_timeout,
               _BRAIN_INPUT_ORIGIN={"who": origin, "ts": 0.0}, _brain_requester=lambda: requester,
               structured_stage_command=structured_stage_command, run_stage_commands=run_stage_commands,
               AUDIENCE_STAGE_DECLINE=_const("AUDIENCE_STAGE_DECLINE"),
               UNASKED_STAGE_DECLINE=_const("UNASKED_STAGE_DECLINE"),
               _SUBAGENT_VISION_TASK_RE=__import__('re').compile(_const_pattern('_SUBAGENT_VISION_TASK_RE')))
    asyncio.run(ns["_handle_invoke_subagent"](sess, asyncio.Lock(), "invoke_subagent", "call-1", task, intent))
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


def test_subagent_acts_with_the_rights_of_whoever_prompted_the_brain():
    """觀眾說「收起鋼琴」被 CPU 擋下，哨兵把留言轉給主腦，主腦呼叫子智能體，
    舊碼一律當老爸下令，鋼琴真的被收掉（2026-10-25 實機）。"""
    targets = []
    _run_handler((False, "", {}), ("advice", "[婉拒]"), task="停止播放鋼琴", origin="audience", targets=targets)
    assert targets == [("cpu", "audience"), ("nv", "audience")]
    targets = []
    _run_handler((False, "", {}), ("advice", "[好]"), task="停止播放鋼琴", origin="dad", targets=targets)
    assert targets == [("cpu", "dad"), ("nv", "dad")]


def test_audience_turn_cannot_stop_the_stage_through_the_subagent():
    from core.hard_command import is_stage_control, build_slip_text
    dispatched = []

    async def dispatch(*a, **k):
        dispatched.append(a[0])

    async def tool_pass(*a, **k):
        return "pe.stop_virtual_piano", {}
    from core.utils import spawn
    ns = _load("nv_interpret_task", "_dispatch_in_background", spawn=spawn, asyncio=asyncio, resolve_subagent_chain=lambda: ["gemini"],
               promptkit=SimpleNamespace(subagent_system=lambda: ""), execute_tool_dispatch=dispatch, is_stage_control=is_stage_control,
               build_slip_text=build_slip_text, _gemini_tool_pass=tool_pass,
               AUDIENCE_STAGE_DECLINE=_const("AUDIENCE_STAGE_DECLINE"))

    async def go(target):
        r = await ns["nv_interpret_task"]("停止播放鋼琴", target=target)
        await asyncio.sleep(0)
        return r
    kind, text = asyncio.run(go("audience"))
    assert kind == "advice" and "只聽老爸" in text and dispatched == []
    kind, _ = asyncio.run(go("dad"))
    assert kind == "tool" and dispatched == ["pe.stop_virtual_piano"]


def test_dispatcher_refuses_stage_control_from_the_audience():
    from core.hard_command import is_stage_control
    ns = _load("execute_tool_dispatch", is_stage_control=is_stage_control,
               _AUDIENCE_DENIED_TOOLS=_const_frozenset("_AUDIENCE_DENIED_TOOLS"))
    for name in ("pe.stop_virtual_piano", "stop_virtual_piano", "pause_virtual_piano", "stop_singing", "stop_cover"):
        assert "權限不足" in asyncio.run(ns["execute_tool_dispatch"](name, {}, caller_target="audience"))


def _const_frozenset(name):
    node = next(n.value for n in TREE.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name)
    return frozenset(ast.literal_eval(node.args[0]))


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

    ns = _load("nv_interpret_task", asyncio=asyncio, resolve_subagent_chain=lambda: chain, promptkit=SimpleNamespace(subagent_system=lambda: ""),
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
               promptkit=SimpleNamespace(subagent_system=lambda: ""), execute_tool_dispatch=dispatch, summarize_search_to_speech=summarize,
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


def test_screen_task_is_handed_to_the_vision_brain():
    """主腦把「看螢幕」丟給子智能體：子智能體看不到畫面，以前只回「視覺大腦會回報」卻沒人去叫，
    她就一直不講話（2026-10-26 實機）。現在直接啟動看畫面，請她先說「我看看」；剛看過就不重看。"""
    import re as _re
    from core.hard_command import build_slip_text

    async def never(*a, **k):
        raise AssertionError("看畫面不該跑 CPU 或副腦")

    looked = []

    async def live_vision_tool_task():
        looked.append(True)

    def run(recent):
        sess = _FakeSession()
        ns = _load("_run_subagent_task", "_handle_invoke_subagent", types=types, asyncio=asyncio, time=time,
                   background_tool_executor=never, nv_interpret_task=never, build_slip_text=build_slip_text,
                   _SUBAGENT_TOTAL_TIMEOUT=45.0, _SUBAGENT_VISION_TASK_RE=_re.compile(_const_pattern("_SUBAGENT_VISION_TASK_RE")),
                   _vision_report_recent=lambda now: recent, live_vision_tool_task=live_vision_tool_task,
                   vc=pytypes.SimpleNamespace(GLOBAL_VTS=None))

        async def go():
            ns["spawn"] = lambda c: asyncio.ensure_future(c)
            await ns["_handle_invoke_subagent"](sess, asyncio.Lock(), "invoke_subagent", "c1", "看老爸螢幕上面有什麼")
            await asyncio.sleep(0)
        asyncio.run(go())
        return sess
    sess = run(False)
    assert looked == [True] and len(sess.sent) == 1
    assert sess.sent[0].scheduling == types.FunctionResponseScheduling.WHEN_IDLE
    assert "不要描述畫面" in sess.sent[0].response["result"] and "我看看" in sess.sent[0].response["result"]
    sess = run(True)                                      # 剛看過：不重看，照剛才的回報回答
    assert len(looked) == 1 and sess.sent[0].scheduling == types.FunctionResponseScheduling.SILENT


def test_background_tool_failures_are_logged(monkeypatch):
    """演奏中點小星星，CPU 有攔截，之後整個不見、日誌一行都沒有（2026-10-25 實機）：背景工具出錯要留日誌，帶工具名和參數。"""
    import core.utils as u
    logged = []
    monkeypatch.setattr(u, "log_print", lambda m, *a, **k: logged.append(m))
    u._BG_FAIL_LOG.clear()

    async def boom(*a, **k):
        raise RuntimeError("壞掉了")
    ns = _load("_dispatch_in_background", asyncio=asyncio, execute_tool_dispatch=boom, spawn=u.spawn)

    async def go():
        ns["_dispatch_in_background"]("pe.play_virtual_piano", {"song_name": "小星星"}, caller_target="dad")
        await asyncio.sleep(0.01)
    asyncio.run(go())
    assert logged and "pe.play_virtual_piano" in logged[0] and "小星星" in logged[0] and "壞掉了" in logged[0]


def test_brain_slips_have_one_exit_and_origin_is_noted_on_send():
    """紙條以前 14 處各自 put_nowait，「這張是誰觸發的」又在別處另外記（2026-10-25 健檢）。"""
    import collections
    q = collections.deque()
    ns = _load("send_brain_slip", "_note_brain_origin", time=time, log_swallowed=lambda: None,
               LIVE_API_SYSTEM_PROMPT_QUEUE=type("Q", (), {"put_nowait": q.append})(),
               _BRAIN_INPUT_ORIGIN={"who": "dad", "ts": 0.0})
    assert ns["send_brain_slip"]("觀眾說收起鋼琴", origin="audience") is True
    assert ns["send_brain_slip"]("[系統底層：計時到了]") is True
    assert list(q) == [("觀眾說收起鋼琴", "audience", "", ""), "[系統底層：計時到了]"]
    assert ns["_BRAIN_INPUT_ORIGIN"]["who"] == "dad"          # 排隊中不改身分，送出那一刻才記
    assert MAIN.count("LIVE_API_SYSTEM_PROMPT_QUEUE.put_nowait(") == 1   # 只剩出口裡那一處
    sender = ast.get_source_segment(MAIN, _fn("send_system_prompts_to_live"))
    assert sender.index("send_realtime_input(text=prompt)") < sender.index("_note_brain_origin(origin, said, name)")


def test_structured_stage_action_skips_text_parsing():
    """主腦填了結構化動作：照欄位直接執行，不再用正則猜她轉述的說法，也不交 AI 重新解讀（2026-10-25）。"""
    targets = []
    text, sched = _run_handler((True, "", {}), "hang", task="背景彈唱 Faded", targets=targets,   # 結構化路徑只回一則
                               intent={"action": "play_and_sing", "song": "Faded", "song2": "", "url": ""},
                               staged=(True, "mixed_play_sing", {"desc": "Faded＋Faded"}))
    assert targets == [("struct", "dad", [("pe.play_virtual_piano", {"song_name": "Faded"}),
                                          ("auto_sing_song", {"song_name": "Faded"})])]
    assert "Faded＋Faded" in text and sched == types.FunctionResponseScheduling.WHEN_IDLE
    # 沒填或填 other：照舊走文字流程
    targets = []
    _run_handler((True, "auto_sing_song", {"song_name": "晴天"}), None, task="唱晴天", targets=targets,
                 intent={"action": "other", "song": "", "song2": "", "url": ""})
    assert targets == [("cpu", "dad")]


def test_structured_stage_control_from_an_audience_turn_is_declined():
    targets = []
    text, sched = _run_handler((True, "", {}), None, task="收起鋼琴", origin="audience", targets=targets,
                               intent={"action": "stop_piano", "song": "", "song2": "", "url": ""},
                               staged=(False, "audience_denied", {}))
    assert targets[0][:2] == ("struct", "audience") and "只聽老爸" in text


def test_brain_does_not_replay_old_requests_on_unrelated_words():
    """Live 續接的對話留著以前的點歌：老爸說「7L 醒醒」她去彈小星星（2026-10-26 實機）。
    主腦自己要彈／唱時，對照觸發這輪的那句人話；沒人點就不執行、請她直接回那句話。"""
    from core.hard_command import PLAY_TOOLS, stage_request_unasked
    from core.memory import UNIFIED_DIALOGUE_MEMORY
    ns = _load("_note_brain_origin", "_her_words_before", "_brain_replaying_old_request", time=time,
               log_swallowed=lambda: None, stage_request_unasked=stage_request_unasked,
               _BRAIN_INPUT_ORIGIN={"who": "dad", "ts": 0.0, "said": "", "human": False})
    note, replaying = ns["_note_brain_origin"], ns["_brain_replaying_old_request"]
    note("dad", "7L 醒醒")
    assert replaying(["小星星"]) is True
    note("audience", "7L 還醒著嗎？")
    assert replaying(["晴天"]) is True
    note("dad", "彈首妳喜歡的")
    assert replaying(["小星星"]) is False
    note("", "")                                   # 系統通知觸發的（計時、自主閒聊）：不對照
    assert replaying(["小星星"]) is False and ns["_BRAIN_INPUT_ORIGIN"]["who"] == "dad"
    # 她先問「要不要我彈小星星？」，老爸回「好啊」也算點了
    UNIFIED_DIALOGUE_MEMORY.append({"speaker": "7L", "role": "assistant", "content": "要不要我彈小星星給你聽？",
                                    "time": time.time() - 5})
    try:
        note("dad", "好啊")
        assert replaying(["小星星"]) is False
    finally:
        UNIFIED_DIALOGUE_MEMORY.pop()


def test_stage_runner_declines_replays_before_doing_anything():
    from core.hard_command import PLAY_TOOLS
    done = []
    ns = _load("run_stage_commands", PLAY_TOOLS=PLAY_TOOLS, _brain_replaying_old_request=lambda songs: True,
               _BRAIN_INPUT_ORIGIN={"said": "7L 醒醒"}, _hard_cmd_seen_recently=lambda *a: done.append(a) or False)
    r = asyncio.run(ns["run_stage_commands"]([("pe.play_virtual_piano", {"song_name": "小星星"})], from_brain=True))
    assert r == (False, "unasked", {"song_name": "小星星"}) and done == []
    # 停鋼琴、停歌不是點歌，不對照
    ns["_brain_replaying_old_request"] = lambda songs: (_ for _ in ()).throw(AssertionError("不該對照"))
    ns.update(is_stage_control=lambda n: False, PIANO_CONTROL_TOOLS=frozenset(), _dispatch_in_background=lambda *a, **k: None,
              build_slip_text=lambda *a, **k: "", is_live_brain_active=lambda: False, time=time)
    assert asyncio.run(ns["run_stage_commands"]([("stop_singing", {})], from_brain=True))[0] is True


def test_subagent_tells_her_not_to_replay_and_skips_the_reinterpreter():
    targets = []
    text, sched = _run_handler((True, "", {}), "hang", task="彈小星星", targets=targets,
                               intent={"action": "play_piano", "song": "小星星", "song2": "", "url": ""},
                               staged=(False, "unasked", {"song_name": "小星星"}))
    assert [t[0] for t in targets] == ["struct"]
    assert "沒有人點歌" in text and "小星星" in text and sched == types.FunctionResponseScheduling.WHEN_IDLE


def test_subagent_acts_for_whoever_prompted_the_brain_by_name():
    """以前一律傳空字串：老爸用麥克風點歌，鋼琴隊列和她的應答都寫「點播的人」。"""
    ns = _load("_note_brain_origin", "_brain_requester", time=time, _owner_name=lambda: "老爸",
               _BRAIN_INPUT_ORIGIN={"who": "dad", "ts": 0.0, "said": "", "human": False, "name": ""})
    note, req = ns["_note_brain_origin"], ns["_brain_requester"]
    note("dad", "彈小星星")
    assert req() == "老爸"
    note("audience", "唱晴天", "歌迷阿華")
    assert req() == "歌迷阿華"
    note("audience", "大家好", "")                  # 好幾個觀眾一起：不知道是誰，走中性
    assert req() == ""
    note("", "")                                   # 系統通知觸發的
    assert req() == ""
    requesters = []
    text, _ = _run_handler((True, "auto_sing_song", {"song_name": "晴天"}), None, task="唱晴天",
                           requester="歌迷阿華", requesters=requesters)
    assert requesters == ["歌迷阿華"] and "歌迷阿華" in text


def test_tool_names_the_subagent_made_up_are_mapped_or_dropped():
    """副腦查匯率回了宣告裡沒有的 search_query，派發器不認得就默默沒做，她答應「我去查」之後就沒下文（2026-10-26 實機）。"""
    from core.tool_schema import resolve_tool_name, DECLARED_TOOL_NAMES
    assert resolve_tool_name("search_query") == "search_google"
    assert resolve_tool_name("web_search") == "search_google"
    assert resolve_tool_name("search_google") == "search_google"
    assert resolve_tool_name("play_virtual_piano") == "pe.play_virtual_piano"     # 少了前綴
    assert resolve_tool_name("pe_stop_virtual_piano") == "pe.stop_virtual_piano"  # 點寫成底線
    assert resolve_tool_name("make_coffee") == "" and resolve_tool_name("") == ""
    assert all(resolve_tool_name(n) == n for n in DECLARED_TOOL_NAMES)


def test_mirror_task_is_handed_to_the_mirror_once():
    """她說「照鏡子」又同時叫子智能體：子智能體不會照鏡子，以前白跑一趟再請她答應一次（2026-10-26 實機）。"""
    async def never(*a, **k):
        raise AssertionError("照鏡子不該跑 CPU 或副腦")
    started = []

    def run(can_start):
        sess = _FakeSession()
        ns = _load("_run_subagent_task", "_handle_invoke_subagent", types=types, asyncio=asyncio, time=time,
                   background_tool_executor=never, nv_interpret_task=never,
                   _SUBAGENT_VISION_TASK_RE=__import__("re").compile(_const_pattern("_SUBAGENT_VISION_TASK_RE")),
                   _start_mirror=lambda: started.append(1) or can_start)
        asyncio.run(ns["_handle_invoke_subagent"](sess, asyncio.Lock(), "invoke_subagent", "c1", "7L 照鏡子看今天的穿搭"))
        return sess.sent
    sent = run(True)
    assert len(sent) == 1 and sent[0].scheduling == types.FunctionResponseScheduling.WHEN_IDLE and "我照照看" in sent[0].response["result"]
    sent = run(False)                                    # 已經在照：安靜等回報
    assert len(sent) == 1 and sent[0].scheduling == types.FunctionResponseScheduling.SILENT and len(started) == 2
