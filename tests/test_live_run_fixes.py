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


def test_piano_volume_keeps_saved_window_geometry(tmp_path, monkeypatch):
    """調音量要併進設定檔，不能整檔清空（2026-10-25：讀不存在的 current_speed，開檔清空後才炸，
    視窗位置記憶每次開彈都被清掉）。"""
    import json
    import types
    src = open(os.path.join(ROOT, "test_virtual_piano.py"), encoding="utf-8").read()
    ns = {"os": os, "json": json, "SOUND_ENGINE": None}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "get_piano_settings_path", "load_piano_settings", "save_piano_settings", "set_piano_volume"):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "x", "exec"), ns)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    ns["save_piano_settings"]({"geometry": "800x600+10+10"})
    win = types.SimpleNamespace(current_volume=100, prev_volume=100, broadcast_piano_status=lambda *a: None,
                                set_status_text=lambda *a: None)
    ns["set_piano_volume"](win, 94)
    assert ns["load_piano_settings"]() == {"geometry": "800x600+10+10", "volume": 94}


def test_precise_sleep_exists_for_text_sheet_playback():
    """文字樂譜演奏路徑要用 precise_sleep；ef252eb2c 誤刪後走到就 NameError。"""
    import services.piano_engine as pe
    t = time.perf_counter()
    pe.precise_sleep(0.02)
    assert 0.018 <= time.perf_counter() - t < 0.2


def _run_executor(text, target, recent=None):
    """跑 background_tool_executor（假的派發），回 (結果, 派發過的工具)。"""
    import asyncio
    import collections
    from core.hard_command import parse_hard_command, build_slip_text, PIANO_CONTROL_TOOLS, split_original_request
    dispatched = []

    async def execute_tool_dispatch(fn, args, **k):
        dispatched.append(fn)

    async def _song_ack(*a, **k):
        pass

    ns = {"asyncio": asyncio, "time": time, "log_print": lambda *a, **k: None, "log_swallowed": lambda: None,
          "parse_hard_command": parse_hard_command, "build_slip_text": build_slip_text,
          "PIANO_CONTROL_TOOLS": PIANO_CONTROL_TOOLS, "split_original_request": split_original_request,
          "execute_tool_dispatch": execute_tool_dispatch, "_song_ack": _song_ack,
          "is_live_brain_active": lambda: False, "LIVE_API_SYSTEM_PROMPT_QUEUE": collections.deque(),
          "_HARD_CMD_RECENT": {} if recent is None else recent, "_HARD_CMD_DEDUPE_SEC": 20.0}
    for name in ("_hard_cmd_seen_recently", "background_tool_executor"):
        exec(compile(ast.Module(body=[_fn(name)], type_ignores=[]), name, "exec"), ns)

    async def go():
        r = await ns["background_tool_executor"](text, target=target, requester_name="")
        await asyncio.sleep(0)
        return r
    return asyncio.run(go()), dispatched


def test_viewers_cannot_control_the_piano():
    (hit, _, _), sent = _run_executor("7L 別彈了", "audience")
    assert hit is False and sent == []
    (hit, tool, _), sent = _run_executor("7L 別彈了", "dad")
    assert hit is True and tool == "pe.stop_virtual_piano" and sent == ["pe.stop_virtual_piano"]


def test_pause_resume_pause_is_not_blocked_by_dedupe():
    recent = {}
    for text, tool in (("暫停鋼琴", "pe.pause_virtual_piano"), ("繼續彈", "pe.resume_virtual_piano"),
                       ("暫停鋼琴", "pe.pause_virtual_piano")):
        _, sent = _run_executor(text, "dad", recent)
        assert sent == [tool], text
    _, sent = _run_executor("暫停鋼琴", "dad", recent)   # 同一則被主腦再送一次：照樣擋
    assert sent == []


def test_piano_ack_does_not_say_sing():
    lines = next(ast.literal_eval(n.value) for n in TREE.body
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_PIANO_ACK_LINES")
    assert lines and not any("唱" in l for l in lines)
    src = ast.get_source_segment(MAIN, _fn("background_tool_executor"))
    assert "piano=fn_name in (" in src


def test_replay_after_stop_is_not_killed_by_stale_heartbeat(monkeypatch):
    """停止後再點一首：舊心跳早就逾時，新視窗還沒開，不能被當成鋼琴已關閉（2026-10-24 實機整首沒彈）。"""
    import services.piano_engine as pe
    now = time.time()
    monkeypatch.setattr(pe, "is_piano_active", True)
    monkeypatch.setattr(pe, "current_piano_process", None)
    monkeypatch.setattr(pe, "LAST_PIANO_HEARTBEAT_TIME", now - 60)   # 上一首的心跳
    monkeypatch.setattr(pe, "LAST_PIANO_OPEN_TIME", now - 3)         # 剛發起這一首
    monkeypatch.setattr(pe, "is_piano_window_alive", lambda: False)  # 新視窗還在路上
    monkeypatch.setattr(pe, "save_persisted_piano_state", lambda *a, **k: None)
    assert pe.is_piano_active_and_alive() is True
    monkeypatch.setattr(pe, "LAST_PIANO_OPEN_TIME", now - 40)        # 過了寬限期還沒心跳：照樣判死
    assert pe.is_piano_active_and_alive() is False
    assert pe.LAST_PIANO_HEARTBEAT_TIME == 0.0                       # 判死時清掉舊心跳
