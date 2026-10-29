# -*- coding: utf-8 -*-
"""有唱、彈的字就直接判斷（老爸 2026-10-29：不要等 Live 判斷完再丟給下一棒判斷）。"""
import ast
import asyncio
import re
import time
from types import SimpleNamespace

from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: E402
from core.hard_command import structured_stage_command


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _const_pattern(name):
    return next(n.value.args[0].value for n in TREE.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == name)


def _ns(judge_reply="", cpu=(None, {})):
    """執行器＋判斷器＋帳本，CPU 正則和 Groq 換成假的；回 (ns, 執行過的指令, 問過判斷的句子)。"""
    ran, asked = [], []

    async def run_stage_commands(cmds, **k):
        ran.append((cmds, k.get("said")))
        return True, cmds[0][0], cmds[0][1]

    async def groq_chat(messages, **k):
        asked.append(messages[-1]["content"])
        return SimpleNamespace(text=judge_reply)

    ns = {"re": re, "json": __import__("json"), "time": time, "asyncio": asyncio, "to_tw": lambda s: s,
          "log_print": lambda *a, **k: None, "log_swallowed": lambda: None, "groq_chat": groq_chat,
          "usage": __import__("core.usage", fromlist=["usage"]), "structured_stage_command": structured_stage_command,
          "parse_hard_command": lambda t: cpu, "run_stage_commands": run_stage_commands,
          "_offer_accept_cmds": lambda *a: [], "_STAGE_JUDGED": {}, "STAGE_JUDGE_WAIT_SEC": 0.3,
          "_STAGE_JUDGE_SYSTEM": "判斷", "_SING_PLAY_RE": re.compile(_const_pattern("_SING_PLAY_RE")),
          "_STAGE_JUDGE_ACTIONS": next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n, ast.Assign)
                                       and getattr(n.targets[0], "id", "") == "_STAGE_JUDGE_ACTIONS")}
    for n in ("_stage_said_key", "_stage_mark", "_stage_already_handled", "_judge_stage_request",
              "background_tool_executor"):
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns, ran, asked


def test_regex_miss_with_sing_or_play_goes_straight_to_the_judge():
    ns, ran, asked = _ns('{"action": "play_and_sing", "song": "晴天", "song2": ""}')
    hit, tool, _ = asyncio.run(ns["background_tool_executor"]("7L 來點周杰倫那首晴天，邊彈邊唱給我聽", target="dad"))
    assert asked == ["7L 來點周杰倫那首晴天，邊彈邊唱給我聽"]
    assert ran == [([("pe.play_virtual_piano", {"song_name": "晴天"}), ("auto_sing_song", {"song_name": "晴天"})],
                    "7L 來點周杰倫那首晴天，邊彈邊唱給我聽")]
    assert asyncio.run(ns["_stage_already_handled"]("7L 來點周杰倫那首晴天，邊彈邊唱給我聽"))   # 主腦晚到：不再做


def test_talking_about_singing_is_judged_as_nothing():
    ns, ran, asked = _ns('{"action": "none", "song": ""}')
    hit, _, _ = asyncio.run(ns["background_tool_executor"]("我昨天在 KTV 唱了一整晚", target="dad"))
    assert hit is False and ran == [] and asked
    assert not asyncio.run(ns["_stage_already_handled"]("我昨天在 KTV 唱了一整晚"))   # 主腦照常自己決定


def test_no_sing_or_play_word_never_calls_the_judge():
    ns, ran, asked = _ns('{"action": "sing", "song": "晴天"}')
    asyncio.run(ns["background_tool_executor"]("今天天氣好好喔", target="dad"))
    assert asked == [] and ran == []


def test_cpu_never_guesses_the_song_when_sing_or_play_is_there():
    # 老爸 10-29 更正：CPU 只看有沒有唱／彈，有就整句交給 Groq（以前「彈一下那首小星星」被正則猜成歌名「一下那首小星星」）
    ns, ran, asked = _ns('{"action": "play_piano", "song": "小星星"}', cpu=("pe.play_virtual_piano", {"song_name": "一下那首小星星"}))
    asyncio.run(ns["background_tool_executor"]("7L 可以幫我彈一下那首小星星嗎", target="dad"))
    assert asked and ran[0][0] == [("pe.play_virtual_piano", {"song_name": "小星星"})]
    ns, ran, asked = _ns('{"action": "stop_singing"}', cpu=("stop_singing", {}))   # 停止也是 Groq 判
    asyncio.run(ns["background_tool_executor"]("7L 別唱了", target="dad"))
    assert asked and ran[0][0] == [("stop_singing", {})]
    ns, ran, asked = _ns('{"action": "sing", "song": "x"}', cpu=("pe.stop_virtual_piano", {}))   # 沒唱／彈：照舊 CPU
    asyncio.run(ns["background_tool_executor"]("收起鋼琴", target="dad"))
    assert asked == [] and ran[0][0] == [("pe.stop_virtual_piano", {})]


def test_bad_or_missing_judge_reply_does_nothing():
    for reply in ("", "好的", '{"action": "sing"}', '{"action": "dance", "song": "x"}'):
        ns, ran, _ = _ns(reply)
        asyncio.run(ns["background_tool_executor"]("唱一下嘛", target="dad"))
        assert ran == [], reply


def test_brain_waits_for_a_pending_judgment():
    ns, _, _ = _ns()

    async def go():
        ns["_stage_mark"]("唱晴天", "pending")
        waiting = asyncio.ensure_future(ns["_stage_already_handled"]("唱晴天"))
        await asyncio.sleep(0.05)
        ns["_stage_mark"]("唱晴天", "hit")
        return await waiting
    assert asyncio.run(go()) is True


def test_voice_is_judged_before_the_brains_tool_call():
    """2026-10-29 實機：麥克風「唱小星星」，主腦的工具呼叫比她開口早到、先排了，Groq 那條看到已處理就沒判。
    現在收到工具呼叫先收尾老爸的話、當場記「判斷中」，主腦那邊等 Groq；語音那條不能等自己。"""
    import time as _t
    ns, ran, asked = _ns('{"action": "sing", "song": "小星星"}')
    ns["_stage_mark"]("唱 小 星 星 。", "pending")      # 收尾時記的
    t0 = _t.time()
    asyncio.run(ns["background_tool_executor"]("唱 小 星 星 。", target="dad", voice=True))
    assert _t.time() - t0 < 0.2 and asked and ran[0][0] == [("auto_sing_song", {"song_name": "小星星"})]
    assert asyncio.run(ns["_stage_already_handled"]("唱小星星"))   # 空格、句號不影響：主腦那條看得到
    recv = ast.get_source_segment(MAIN, _fn("receive_from_live"))
    assert recv.index("_flush_user_speech()", recv.index("_fcs = list(")) < recv.index("for _fc in _fcs:")
    assert '_stage_mark(user_spoken, "pending")' in MAIN


def test_wiring():
    sub = ast.get_source_segment(MAIN, _fn("_run_subagent_task"))
    assert "await _stage_already_handled(_said)" in sub and '_stage_mark(_said, "hit")' in sub
    assert "background_tool_executor(user_spoken, target=\"dad\", requester_name=owner, voice=True)" in MAIN
