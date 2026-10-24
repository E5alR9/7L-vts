"""2026-10-24 實機測試修正的回歸測試：
內心戲段落被念出來、自我插話砍掉自己、提醒工具沒宣告、主腦工具呼叫漏接、硬指令重複執行、鋼琴暫停被當播完。"""
import ast
import os
import time

from core.prompts import TextCleanEngine as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
TREE = ast.parse(MAIN)


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_inner_monologue_sections_are_not_spoken():
    for raw in ("開大腦🧠心想中：\n老爸要我提醒他帶傘，我要傲嬌答應！\n開口說話：\n哼哼，包在我身上！",
                "在大腦中思考：老爸要我提醒他帶傘。\n開口說話：\n哼哼，包在我身上！"):
        thought, rest = T.extract_thought(raw)
        assert "帶傘" in thought
        assert rest.strip() == "哼哼，包在我身上！"


def test_self_interrupt_is_awaited_before_new_speech_is_queued():
    src = ast.get_source_segment(MAIN, _fn("execute_actions"))
    assert "await interrupt_current_speech(clear_queue=True" in src
    assert "asyncio.create_task(interrupt_current_speech(clear_queue=True" not in src


def test_timer_tag_with_tool_prefix_is_parsed():
    import re
    pat = next(n.args[0].value for n in ast.walk(_fn("execute_actions")) if isinstance(n, ast.Call)
               and ast.unparse(n.func) == "re.finditer" and isinstance(n.args[0], ast.Constant) and "TIMER" in n.args[0].value)
    m = re.search(pat, "[TOOL:TIMER: 86400|提醒老爸帶傘]", re.I)
    assert m and m.group(1) == "86400"


def test_set_timer_is_declared_to_the_model():
    it = next(n for n in TREE.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "INTERACTIONS_TOOLS")
    names = [t["name"] for t in ast.literal_eval(it.value)]
    assert "set_timer" in names


def test_main_brain_reads_tool_call_messages():
    src = ast.get_source_segment(MAIN, _fn("receive_from_live"))
    assert "'tool_call'" in src or '"tool_call"' in src


def test_hard_command_dedupe_window():
    ns = {"_HARD_CMD_RECENT": {}, "_HARD_CMD_DEDUPE_SEC": 20.0}
    exec(compile(ast.Module(body=[_fn("_hard_cmd_seen_recently")], type_ignores=[]), "x", "exec"), ns)
    f = ns["_hard_cmd_seen_recently"]
    now = time.time()
    assert f("pe.play_virtual_piano", {"song_name": "First Love"}, now) is False
    assert f("pe.play_virtual_piano", {"song_name": "First Love"}, now + 5) is True     # 主腦又叫一次：擋
    assert f("pe.play_virtual_piano", {"song_name": "晴天"}, now + 5) is False          # 不同歌照放
    assert f("pe.play_virtual_piano", {"song_name": "First Love"}, now + 25) is False   # 過窗再點可以


def test_brain_initiated_subagent_does_not_echo_slips():
    src = ast.get_source_segment(MAIN, _fn("receive_from_live"))
    assert "from_brain=True" in src


def test_piano_pause_is_not_mistaken_for_song_end():
    import services.piano_engine as pe
    src = open(os.path.join(ROOT, "services", "piano_engine.py"), encoding="utf-8").read()
    assert "if IS_PIANO_PAUSED or time.time() < _PIANO_RESUME_GRACE_UNTIL:" in src
    assert hasattr(pe, "pause_virtual_piano") and hasattr(pe, "resume_virtual_piano")


def test_piano_window_handles_pause_resume_ipc():
    src = open(os.path.join(ROOT, "test_virtual_piano.py"), encoding="utf-8").read()
    assert 'elif cmd == "pause":' in src and 'elif cmd == "resume":' in src


def test_precise_sleep_exists_for_text_sheet_playback():
    """文字樂譜演奏路徑要用 precise_sleep；ef252eb2c 誤刪後走到就 NameError。"""
    import services.piano_engine as pe
    t = time.perf_counter()
    pe.precise_sleep(0.02)
    assert 0.018 <= time.perf_counter() - t < 0.2
