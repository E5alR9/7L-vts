# -*- coding: utf-8 -*-
"""VTuber 模式也開 Live 主腦（老爸 2026-10-26 決定）：不送麥克風、只吃紙條；主腦的話照觸發者決定對誰講。"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: E402


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _target(origin_who, mode, monkeypatch):
    monkeypatch.setenv("MODE", mode)
    ns = {"_BRAIN_INPUT_ORIGIN": {"who": origin_who}}
    exec(compile(ast.Module(body=[_fn("_live_reply_target")], type_ignores=[]), "x", "exec"), ns)
    return ns["_live_reply_target"]()


def test_reply_target_follows_who_asked(monkeypatch):
    assert _target("dad", "companion", monkeypatch) == "dad"
    assert _target("audience", "companion", monkeypatch) == "audience"   # 回觀眾的話公開講、老爸插話時可以丟
    assert _target("dad", "vtuber", monkeypatch) == "audience"           # VTuber 模式沒有私話對象（私話不播）


def test_live_brain_is_started_in_both_modes():
    main_fn = ast.get_source_segment(MAIN, _fn("main"))
    i = main_fn.index("spawn(continuous_live_worker(vts))")
    j = main_fn.index("if operator_input_enabled():")
    assert i < j     # 不在「老爸輸入」區塊裡


def test_mic_is_silent_without_operator_input():
    src = ast.get_source_segment(MAIN, _fn("continuous_live_worker"))
    assert "not operator_input_enabled()" in src


def test_vtuber_prompt_says_its_a_stream():
    import services.vts_client as vc
    from core import promptkit
    from core.memory import DEFAULT_CLOUD_KNOWLEDGE
    c = promptkit.brain_system("老爸", "7L", DEFAULT_CLOUD_KNOWLEDGE, vc.EXPRESSION_MENU_TEXT)
    v = promptkit.brain_system("老爸", "7L", DEFAULT_CLOUD_KNOWLEDGE, vc.EXPRESSION_MENU_TEXT, mode="vtuber")
    assert v.startswith(c) and "VTuber 直播模式" in v and "VTuber 直播模式" not in c
