# -*- coding: utf-8 -*-
"""Live 主腦的 say 閘（2026-10-29 老爸：以前她輸出就直接念，像沒有腦內聲音的人；改成先想、調度完再決定說）。
直接輸出＝腦內聲音只記不念；她呼叫 say(text) 的才念。"""
import ast
import asyncio
import re
import time
from types import SimpleNamespace

from google.genai import types

from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: E402


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _load(*names, **ns):
    for n in names:
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns


class _Session:
    def __init__(self):
        self.sent = []

    async def send_tool_response(self, function_responses):
        self.sent += function_responses


def _say_ns(singing=False, vision_busy=False):
    spoken, logs, after = [], [], []

    async def speak(vts, iq, text, who, reply_to, source, **k):
        if singing:
            return ""
        spoken.append((text, who, reply_to, source, k.get("from_live")))
        return text

    sess = _Session()
    ns = _load("_handle_say", "_send_say_response", "_note_inner_voice", re=re, time=time, asyncio=asyncio, types=types,
               _AWAITING_RESULTS={}, AWAIT_RESULT_MAX_SEC=75.0, LAST_SAY_TS=0.0,
               _autonomy_note_say=lambda t, now: "", AUTONOMY_SAY_MIN_GAP=60.0,
               _SAY_LOCK=asyncio.Lock(), GLOBAL_LIVE_SESSION=sess, _speak_brain_turn=speak, input_queue=None,
               _start_marker_tools=lambda t: t.replace("[TOOL:VISION]", "").strip(),
               _VISION_STATE={"busy": vision_busy}, _vision_wait_text=lambda t: t.split("～")[0] + "～",
               _BRAIN_INPUT_ORIGIN={"who": "dad"}, _live_reply_target=lambda: "dad",
               log_print=logs.append, log_swallowed=lambda *a: None, spawn=lambda c: (after.append(c), c.close()),
               _afterthought=lambda t: asyncio.sleep(0), _group_post=lambda *a: None, LAST_BRAIN_TURN_TS=0.0, LAST_BRAIN_REPLY_DONE_TS=0.0,
               eventlog=SimpleNamespace(get=lambda: SimpleNamespace(record=lambda *a, **k: logs.append(("ev", a)))))
    return ns, sess, spoken, logs, after


def test_say_is_spoken_through_the_normal_path_and_answered_silently():
    ns, sess, spoken, _, after = _say_ns()
    asyncio.run(ns["_handle_say"](sess, asyncio.Lock(), "c1", "[EXPRESSION: 開心] 老爸查到了！明天不會下雨", vts="V"))
    assert spoken == [("[EXPRESSION: 開心] 老爸查到了！明天不會下雨", "dad", "dad", "live_api", True)]
    r = sess.sent[0]
    assert r.name == "say" and r.id == "c1" and r.scheduling == types.FunctionResponseScheduling.SILENT   # 不再開一輪
    assert ns["LAST_BRAIN_TURN_TS"] > 0 and len(after) == 1        # 算她回話了；背後照樣再想一次


def test_say_keeps_order_and_skips_empty_or_silence():
    ns, sess, spoken, _, _ = _say_ns()

    async def go():
        lock = asyncio.Lock()
        await asyncio.gather(ns["_handle_say"](sess, lock, "a", "第一句"), ns["_handle_say"](sess, lock, "b", "第二句"),
                             ns["_handle_say"](sess, lock, "c", "[SILENCE]"))
    asyncio.run(go())
    assert [s[0] for s in spoken] == ["第一句", "第二句"] and len(sess.sent) == 3


def test_only_the_ack_is_said_while_a_result_is_pending():
    # 2026-10-29 實測：搜尋還沒開始她就 say「查好囉！明天陰天 20～23 度」，真結果回來又講一次不一樣的
    ns, sess, spoken, logs, _ = _say_ns()
    ns["_AWAITING_RESULTS"]["call-9"] = [time.time(), 0]

    async def go():
        lock = asyncio.Lock()
        await ns["_handle_say"](sess, lock, "a", "好，我去查！")
        await ns["_handle_say"](sess, lock, "b", "查好囉！明天陰天 20～23 度")      # 結果還沒回來：擋
        ns["_AWAITING_RESULTS"].pop("call-9")                                        # 結果交回去了
        await ns["_handle_say"](sess, lock, "c", "查到了！明天小雨轉多雲")
    asyncio.run(go())
    assert [s[0] for s in spoken] == ["好，我去查！", "查到了！明天小雨轉多雲"]
    assert "不要先講結果" in sess.sent[1].response["result"] and any("先別講" in str(x) for x in logs)
    ns["_AWAITING_RESULTS"]["stale"] = [time.time() - 200, 5]                        # 漏撤銷的不會永遠擋住
    asyncio.run(ns["_handle_say"](sess, asyncio.Lock(), "d", "老爸晚安"))
    assert spoken[-1][0] == "老爸晚安" and "stale" not in ns["_AWAITING_RESULTS"]


def test_two_tasks_at_once_each_result_can_be_said():
    """老爸一句話交兩件事，主腦分兩次叫子智能體（2026-10-29）：第一件回來能講，第二件沒回來前不能先編。"""
    ns, sess, spoken, _, _ = _say_ns()
    waiting = ns["_AWAITING_RESULTS"]

    async def run_task(task, intent, respond):
        await respond(f"[{task}的結果]", types.FunctionResponseScheduling.WHEN_IDLE)

    exec(compile(ast.Module(body=[_fn("_handle_invoke_subagent")], type_ignores=[]), "h", "exec"), ns)
    ns.update(_run_subagent_task=run_task, LIVE_SAY_GATE=False, _subagent_result_by_slip=lambda *a: None)

    async def go():
        lock = asyncio.Lock()
        waiting["weather"] = [time.time(), 0]
        waiting["timer"] = [time.time(), 0]
        await ns["_handle_say"](sess, lock, "a", "好，查天氣跟設計時器！")           # 答應：放行
        await ns["_handle_say"](sess, lock, "b", "明天晴天喔")                       # 兩件都還沒回來：擋
        await ns["_handle_invoke_subagent"](sess, lock, "invoke_subagent", "weather", "查天氣")
        await ns["_handle_say"](sess, lock, "c", "查到了，明天小雨")                 # 天氣回來了：放行
        await ns["_handle_say"](sess, lock, "d", "計時器也設好了")                   # 計時器還沒回來：擋
        await ns["_handle_invoke_subagent"](sess, lock, "invoke_subagent", "timer", "設計時器")
        await ns["_handle_say"](sess, lock, "e", "計時器設好了！")
    asyncio.run(go())
    assert [s[0] for s in spoken] == ["好，查天氣跟設計時器！", "查到了，明天小雨", "計時器設好了！"]
    assert waiting == {}


def test_say_before_seeing_the_screen_only_says_the_first_clause():
    ns, sess, spoken, _, _ = _say_ns(vision_busy=True)
    asyncio.run(ns["_handle_say"](sess, asyncio.Lock(), "v", "我看看～[TOOL:VISION] 老爸在看晴天教學耶"))
    assert spoken[0][0] == "我看看～"


def test_inner_voice_is_logged_not_spoken_and_ends_the_turn():
    ns, sess, spoken, logs, _ = _say_ns()
    ns["_note_inner_voice"]("老爸問天氣，我先叫子智能體查")
    assert spoken == [] and any("💭 [腦內]" in str(x) for x in logs) and ns["LAST_BRAIN_TURN_TS"] > 0
    for empty in ("", "|", " ｜ "):                              # 空的、或她沒話想時吐的「|」：不算她回了
        ns["LAST_BRAIN_TURN_TS"] = 0.0
        ns["_note_inner_voice"](empty)
        assert ns["LAST_BRAIN_TURN_TS"] == 0.0, empty
    # 腦內想完不算「這輪回完了」：點歌開唱前要等她真的 say（2026-10-29 實測兩次開場白都被唱歌蓋掉）
    ns["LAST_BRAIN_REPLY_DONE_TS"] = 0.0
    ns["_note_inner_voice"]("先想一下要說什麼")
    assert ns["LAST_BRAIN_REPLY_DONE_TS"] == 0.0
    recv = ast.get_source_segment(MAIN, next(n for n in ast.walk(TREE)
                                             if isinstance(n, ast.AsyncFunctionDef) and n.name == "receive_from_live"))
    assert '_note_inner_voice("")' not in recv


def _nudge_ns(said_after=False, singing=False):
    slips = []
    ns = _load("_nudge_if_unsaid", asyncio=asyncio, SAY_NUDGE_SEC=0.05, LAST_SAY_TS=0.0, IS_SLEEPING=False,
               is_singing_active=lambda: singing, log_print=lambda *a: None, _brain_requester=lambda: "老爸",
               send_brain_slip=slips.append)
    if said_after:
        ns["LAST_SAY_TS"] = time.time() + 1
    return ns, slips


def test_result_that_was_never_said_gets_one_reminder():
    # 2026-10-29 實測：查天氣＋計時器的結果回來，她只在腦內吐一個「|」，天氣結果整個不見
    ns, slips = _nudge_ns()
    asyncio.run(ns["_nudge_if_unsaid"]("[搜尋結果，要告訴老爸：明天多雲 20% 降雨]", time.time()))
    assert len(slips) == 1 and "say" in slips[0] and "明天多雲" in slips[0] and "老爸" in slips[0]
    ns, slips = _nudge_ns(said_after=True)                       # 她講了：不提醒
    asyncio.run(ns["_nudge_if_unsaid"]("[搜尋結果]", time.time()))
    assert slips == []
    ns, slips = _nudge_ns(singing=True)                          # 唱歌中：不提醒
    asyncio.run(ns["_nudge_if_unsaid"]("[搜尋結果]", time.time()))
    assert slips == []


def test_live_brain_gets_the_say_tool_and_rule_only_when_the_gate_is_on():
    from core import promptkit
    from core.tool_schema import LIVE_SAY_TOOLS, LIVE_API_TOOLS, REST_BRAIN_TOOLS
    names = [d.name for d in LIVE_SAY_TOOLS[0].function_declarations]
    assert names == ["invoke_subagent", "say"]
    say = LIVE_SAY_TOOLS[0].function_declarations[1]
    assert say.behavior == types.Behavior.NON_BLOCKING and say.parameters.required == ["text"]
    assert [d.name for d in LIVE_API_TOOLS[0].function_declarations] == ["invoke_subagent"]
    assert [d.name for d in REST_BRAIN_TOOLS[0].function_declarations] == ["invoke_subagent"]   # REST 大腦照舊直接講
    assert "腦內的聲音" in promptkit.brain_system("老爸", "7L", {}, "", say_gate=True)
    assert "腦內的聲音" not in promptkit.brain_system("老爸", "7L", {}, "")
    recv = ast.get_source_segment(MAIN, next(n for n in ast.walk(TREE)
                                             if isinstance(n, ast.AsyncFunctionDef) and n.name == "receive_from_live"))
    assert 'if fn_name == "say" and LIVE_SAY_GATE:' in recv and "_note_inner_voice(_turn_text)" in recv
    assert "tools=LIVE_SAY_TOOLS if LIVE_SAY_GATE else LIVE_API_TOOLS" in MAIN


def test_mic_holds_her_own_singing_back_but_lets_dad_through():
    """唱歌中喇叭的歌聲被 Live 聽成老爸在講話（2026-10-29 實機：她唱「我的心裡還有你」被記成老爸說的，她還回他）。
    跟她講話時一樣先不送，聲紋聽出是老爸才放行；不停歌，之後 SING_DAD_HOLD_SEC 秒照送讓他講完。
    離線量：她三首歌（人聲＋伴奏、衰減成回音）271 段只有 1 段像老爸、從沒連續 2 段（2 段才放行）。"""
    src = MAIN[MAIN.index("async def send_mic_audio"):MAIN.index("async def receive_from_live")]
    sing = src[src.index("elif is_singing_active():"):src.index("barge.reset()", src.index("elif is_singing_active():"))]
    assert "barge.feed(data)" in sing and "await barge.check(_now)" in sing
    assert "interrupt_current_speech" not in sing                         # 不停歌
    assert "sing_dad_open_until = _now + SING_DAD_HOLD_SEC" in sing and r"data = b'\x00' * len(data)" in sing


def test_reply_only_in_her_head_gets_one_reminder_to_say_it():
    """同日 3.8 主腦實機：老爸兩次說「妳唱得好可愛喔」，她都只在腦內回，一個字沒念。曾經直接把腦內那段念出來，
    老爸：感覺不太好，還是用 say 專門去說。現在不幫她念，提醒她一次「他聽不到，要回就 say」，講不講由她 say。"""
    now = time.time()
    pat = next(n.value.args[0].value for n in TREE.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_NOT_REPLYING_RE")
    ns = _load("_unsaid_reply_nudge", re=re, LIVE_SAY_GATE=True, REPLY_NUDGE_SEC=30.0, _REPLY_NUDGED={"ts": 0.0},
               _NOT_REPLYING_RE=re.compile(pat), _owner_name=lambda: "老爸",
               _BRAIN_INPUT_ORIGIN={"human": True, "ts": now - 3, "who": "dad"},
               LAST_SAY_TS=now - 60, LAST_BRAIN_TOOL_TS=now - 60)
    f = ns["_unsaid_reply_nudge"]
    reply = "[EXPRESSION: 愛心] 哼，這還用你說！不過被老爸誇獎，我心情還是挺好的～"
    slip = f(reply, now)
    assert "只在腦內回老爸" in slip and "say" in slip and "哼，這還用你說" in slip
    assert f(reply, now) == ""                                    # 同一句人話只提醒一次
    ns["_REPLY_NUDGED"]["ts"] = 0.0
    assert f("老爸在自言自語，先不用回", now) == ""                # 腦內決定不回：不提醒
    ns["LAST_BRAIN_TOOL_TS"] = now - 1
    assert f(reply, now) == ""                                    # 叫了工具：腦內是在盤算
    ns["LAST_BRAIN_TOOL_TS"] = now - 60
    ns["_BRAIN_INPUT_ORIGIN"]["human"] = False
    assert f(reply, now) == ""                                    # 系統紙條（感知、謝幕）：不提醒
    recv = ast.get_source_segment(MAIN, next(n for n in ast.walk(TREE)
                                             if isinstance(n, ast.AsyncFunctionDef) and n.name == "receive_from_live"))
    assert "send_brain_slip(_nudge)" in recv and "_say_unsaid_result" not in MAIN   # 不再幫她念腦內的話


def test_a_new_task_can_be_acknowledged_while_an_older_one_is_still_running():
    """2026-10-31 實測：還在查天氣時老爸又叫她設計時器，連「好，幫你設」都被當成第二句擋掉。"""
    ns, sess, spoken, _, _ = _say_ns()
    waiting = ns["_AWAITING_RESULTS"]

    async def go():
        lock = asyncio.Lock()
        waiting["weather"] = [time.time() - 5, 0]
        await ns["_handle_say"](sess, lock, "a", "我去查天氣！")
        await ns["_handle_say"](sess, lock, "b", "明天晴天喔")            # 天氣還沒回來：擋
        waiting["timer"] = [time.time(), 0]                              # 又交辦了一件
        await ns["_handle_say"](sess, lock, "c", "好，計時器幫你設！")   # 新的這件可以答應
        await ns["_handle_say"](sess, lock, "d", "計時器設好了")         # 還沒回來：擋
    asyncio.run(go())
    assert [s[0] for s in spoken] == ["我去查天氣！", "好，計時器幫你設！"]
