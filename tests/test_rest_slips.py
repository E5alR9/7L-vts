"""沒有 Live 主腦時紙條由 REST 大腦接（2026-10-26）；老爸的話一律走紙條。"""
import ast
import asyncio
import os
import re
import types as pytypes
from collections import deque

from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE, load_main  # noqa: E402


def _load(*names, **ns):
    ns.setdefault("usage", __import__("core.usage", fromlist=["usage"]))   # 主程式函式掛著 @usage.role_scope
    return load_main(*names, **ns)


def test_slip_unpacking_handles_people_and_system_slips():
    f = _load("_unpack_slip")["_unpack_slip"]
    assert f("[系統提示：謝幕]") == ("[系統提示：謝幕]", "", "", "")
    assert f(("老爸說嗨", "dad", "嗨")) == ("老爸說嗨", "dad", "嗨", "")
    assert f(("小明說嗨", "audience", "嗨", "小明")) == ("小明說嗨", "audience", "嗨", "小明")


def test_rest_brain_has_the_same_tool_without_the_live_only_behavior():
    from core.tool_schema import LIVE_API_TOOLS, REST_BRAIN_TOOLS
    live = LIVE_API_TOOLS[0].function_declarations[0]
    rest = REST_BRAIN_TOOLS[0].function_declarations[0]
    assert live.name == rest.name == "invoke_subagent"
    assert live.behavior == types.Behavior.NON_BLOCKING and rest.behavior is None
    assert live.description == rest.description and live.parameters == rest.parameters


class _Stop(BaseException):
    pass


def _run_worker(states, slips, dupes=()):
    """states：每圈 use_rest_brain() 回的值；slips：佇列裡的紙條。回 (交給 REST 的, 記下的身分, 剩下的紙條數)。"""
    states = iter(states)
    answered, origins = [], []
    q = asyncio.Queue()
    for x in slips:
        q.put_nowait(x)

    def use_rest():
        try:
            return next(states)
        except StopIteration:
            raise _Stop()

    async def answer(vts, iq, prompt, origin):
        answered.append((prompt, origin))

    async def no_sleep(_s):
        return None

    async def wait_for(aw, timeout):
        if q.empty():
            aw.close()
            raise asyncio.TimeoutError()
        return await aw

    ns = _load("_unpack_slip", "_take_slip", "rest_slip_worker", use_rest_brain=use_rest, LIVE_API_SYSTEM_PROMPT_QUEUE=q,
               _LIVE_SLIP_RETRY=deque(), _slip_is_dupe=lambda p, now: p in dupes, _record_slip=lambda *a, **k: None, time=pytypes.SimpleNamespace(time=lambda: 0.0),
               _note_brain_origin=lambda o, s, n: origins.append((o, s, n)), _rest_answer_slip=answer,
               asyncio=pytypes.SimpleNamespace(sleep=no_sleep, wait_for=wait_for, TimeoutError=asyncio.TimeoutError))
    try:
        asyncio.run(ns["rest_slip_worker"](None, None))
    except _Stop:
        pass
    return answered, origins, q.qsize()


def test_slips_wait_for_live_while_it_is_up():
    answered, _, left = _run_worker([False, False], ["[系統提示：謝幕]"])
    assert answered == [] and left == 1


def test_rest_brain_answers_slips_when_live_is_gone_and_skips_duplicates():
    answered, origins, left = _run_worker([True, True, True, True],
                                          [("[黑板同步] 老爸傳來文字訊息：嗨", "dad", "嗨", ""), "[重複]", "[系統提示：謝幕]"],
                                          dupes=("[重複]",))
    assert answered == [("[黑板同步] 老爸傳來文字訊息：嗨", "dad"), ("[系統提示：謝幕]", "")]
    assert origins == [("dad", "嗨", ""), ("", "", "")] and left == 0   # 權限照遞紙條的人


def _answer(first, calls, subagent_says):
    """REST 大腦第一次回 first＋calls；子智能體照 subagent_says 依序回報。回 (每次問她的內容, 念出來的話)。"""
    asked, spoken = [], []

    async def rest_chat(system, user, **k):
        asked.append((user, k.get("tools")))
        return pytypes.SimpleNamespace(text=first if len(asked) == 1 else f"第{len(asked)}次", calls=calls if len(asked) == 1 else [])

    async def rest_speak(vts, iq, raw, origin):
        if raw:
            spoken.append((raw, origin))
        return raw

    async def run_subagent(task, intent, respond):
        for text, sched, more in subagent_says:
            await respond(text, sched, _more=more)

    async def build(owner, char):
        return "系統提示詞"

    ns = _load("_rest_answer_slip", rest_chat=rest_chat, _rest_speak=rest_speak, _run_subagent_task=run_subagent,
               build_brain_system_prompt=build, _owner_name=lambda: "老爸", types=types,
               get_unified_memory_context=lambda **k: "（最近對話）",
               pe=pytypes.SimpleNamespace(get_piano_realtime_prompt=lambda: "（鋼琴）"),
               STREAMER_MIND_MODELS=["m"], REST_BRAIN_MODELS=["m"], REST_BRAIN_TOOLS=["T"])
    asyncio.run(ns["_rest_answer_slip"](None, None, "[黑板同步] 老爸傳來文字訊息：查天氣", "dad"))
    return asked, spoken


def test_rest_brain_relays_results_the_subagent_wants_said():
    speak, quiet = types.FunctionResponseScheduling.WHEN_IDLE, types.FunctionResponseScheduling.SILENT
    asked, spoken = _answer("好，我去查！", [("invoke_subagent", {"task_instruction": "查天氣", "action": "other"})],
                            [("[先答應一聲]", speak, True), ("[已排程]", quiet, False), ("[搜尋結果：晴]", speak, False)])
    assert asked[0] == ("[黑板同步] 老爸傳來文字訊息：查天氣", ["T"])   # 第一次有給工具
    assert len(asked) == 2                     # 她已經答應過、SILENT 的不再問；只有結果要她講
    assert "[妳剛才說：好，我去查！]" in asked[1][0] and "[搜尋結果：晴]" in asked[1][0] and asked[1][1] is None
    assert spoken == [("好，我去查！", "dad"), ("第2次", "dad")]


def test_rest_brain_asks_her_to_ack_when_she_called_the_tool_without_a_word():
    speak = types.FunctionResponseScheduling.WHEN_IDLE
    asked, spoken = _answer("", [("invoke_subagent", {"task_instruction": "彈小星星", "action": "play_piano"})],
                            [("[請妳口頭答應]", speak, False)])
    assert len(asked) == 2 and "[妳剛才說：（還沒說話）]" in asked[1][0]
    assert spoken == [("第2次", "dad")]


def _speak(raw, origin, singing=False, calls=None):
    queued, memory = [], []

    async def execute_actions(vts, text, iq, **k):
        if calls is not None:
            calls.append(k)
        return re.sub(r"\[EXPRESSION:[^\]]*\]", "", text)

    async def put(item):
        queued.append(item)

    ns = _load("_speak_brain_turn", "_rest_speak", re=re, time=__import__("time"), _save_viewer_updates=lambda t: 0, normalize_silence_token=lambda t: re.sub(r"\[SILENCE\]", "[PASS]", t),
               _start_marker_tools=lambda t: t, _owner_name=lambda: "老爸", _BRAIN_INPUT_ORIGIN={"name": "小明"},
               execute_actions=execute_actions, is_singing_active=lambda: singing,
               speech_queue=pytypes.SimpleNamespace(put=put), _brain_text_for_memory=lambda t: t,
               append_to_unified_memory=lambda **k: memory.append(k))
    out = asyncio.run(ns["_rest_speak"](None, None, raw, origin))
    return out, queued, memory


def test_rest_speech_goes_public_unless_it_answers_dad():
    out, queued, memory = _speak("[EXPRESSION: 花花] 晚安～", "audience")
    assert out == "晚安～"
    assert queued[0]["target"] == "audience" and queued[0]["private"] is False
    assert memory[0]["source"] == "rest_brain" and memory[0]["target"] == "直播間"
    _, queued, memory = _speak("好喔", "dad")
    assert queued[0]["target"] == "dad" and queued[0]["private"] is True and memory[0]["target"] == "老爸"


def test_brain_turn_runs_tags_with_the_triggering_persons_rights():
    # 觀眾那輪的標籤照觀眾權限跑、計時器記觀眾名字（2026-10-27 以前 Live 一律照老爸的權限）
    calls = []
    _speak("[TIMER: 5|喝水] 好", "audience", calls=calls)
    assert calls[0] == {"caller_target": "audience", "caller_user": "小明"}
    calls.clear()
    _speak("好", "dad", calls=calls)
    assert calls[0] == {"caller_target": "dad", "caller_user": "老爸"}


def test_rest_speech_respects_silence_and_singing():
    assert _speak("[SILENCE]", "audience") == ("", [], [])
    out, queued, memory = _speak("好聽嗎", "audience", singing=True)
    assert queued == [] and memory                       # 唱歌中不插話，但記得她想說什麼


def _dad_message(source, text, audio=None):
    slips, cpu, board = [], [], []

    async def background_tool_executor(t, **k):
        cpu.append(t)

    def spawn(c):
        asyncio.get_event_loop().create_task(c)

    async def go():
        ns = _load("process_chat_message", check_immediate_shutdown=lambda t: False, touch_interaction=lambda: None,
                   _owner_name=lambda: "老爸", live_timer_hub=pytypes.SimpleNamespace(detect_timer_intent=lambda t: None),
                   add_to_streamer_mind_board=lambda **k: board.append(k), background_tool_executor=background_tool_executor,
                   spawn=spawn, send_brain_slip=lambda s, **k: slips.append((s, k)),
                   asyncio=asyncio, IS_MIC_ENABLED=True, Optional=__import__("typing").Optional,
                   asks_to_remember_model_position=lambda t: False,
                   _related_memories_block=lambda q: asyncio.sleep(0, result=""))
        await ns["process_chat_message"](None, None, text, audio, source=source)
        await asyncio.sleep(0)
    asyncio.run(go())
    return slips, cpu, board


def test_dad_text_and_speech_become_dad_slips_whether_or_not_live_is_up():
    slips, cpu, board = _dad_message("text_file", "彈小星星")
    assert slips == [("[黑板同步] 老爸傳來文字訊息：彈小星星", {"origin": "dad", "said": "彈小星星"})]
    assert cpu == ["彈小星星"] and board[0]["handled"] is True
    slips, cpu, _ = _dad_message("mic", "幫我看一下", audio="UklGRg==")
    assert "語音辨識" in slips[0][0] and slips[0][1]["origin"] == "dad" and cpu == []   # 語音不跑 CPU 硬指令
    slips, _, _ = _dad_message("tiktok_dad", "大家好")
    assert slips[0][0] == "[文字輸入] 老爸 (在直播間留言)：大家好"


def test_dad_asking_to_remember_the_model_position_is_done_from_his_words():
    """「7L 記住位置」以前只有她答應時剛好說到這幾個字才會存（2026-10-26 實機她說「記在大腦最深處」，沒存）。"""
    from core.hard_command import asks_to_remember_model_position
    assert asks_to_remember_model_position("7L 記住位置") and asks_to_remember_model_position("幫我記住現在大小")
    assert not asks_to_remember_model_position("記住我說的話")
