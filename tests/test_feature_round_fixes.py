# -*- coding: utf-8 -*-
"""2026-10-26 功能實測找到的問題：Live 主腦記不住觀眾、收琴後 Gemini 判斷的點琴照彈。"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
TREE = ast.parse(MAIN)


def _node(name):
    return next(n for n in TREE.body if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
                or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name))


def test_viewer_update_tags_are_saved():
    saved, logs = [], []
    ns = {"re": re, "spawn": lambda c: (c.close(), None), "log_print": logs.append,
          "save_viewer_profile": lambda name, **k: saved.append((name, k)) or _coro()}
    for n in ("_VIEWER_UPDATE_RE", "_save_viewer_updates"):
        exec(compile(ast.Module(body=[_node(n)], type_ignores=[]), "x", "exec"), ns)
    n = ns["_save_viewer_updates"]("謝謝明哥！[VIEWER_UPDATE:小明|CALL:明哥|REL:頭號粉絲|IMP:很熱情] 晚安～")
    assert n == 1 and saved == [("小明", {"call": "明哥", "relationship": "頭號粉絲", "impression": "很熱情"})]
    assert ns["_save_viewer_updates"]("沒有標籤") == 0


async def _noop():
    return None


def _coro():
    return _noop()


def test_live_brain_turn_saves_viewer_updates():
    src = ast.get_source_segment(MAIN, _node("continuous_live_worker"))
    assert "_save_viewer_updates(turn_buffer)" in src


def test_gemini_piano_intent_checks_the_piano_is_still_out():
    src = ast.get_source_segment(MAIN, _node("add_to_streamer_mind_board"))
    i = src.index("not pe.is_piano_active or getattr(pe, \"PIANO_SESSION_ID\", None) != _piano_session")
    assert i < src.index("await pe.play_virtual_piano(")
