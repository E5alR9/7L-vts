# -*- coding: utf-8 -*-
"""2026-10-26 功能實測找到的問題：Live 主腦記不住觀眾、收琴後 Gemini 判斷的點琴照彈。"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: E402


def _node(name):
    return next(n for n in TREE.body if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
                or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name))


def test_viewer_update_tags_are_saved():
    saved, logs = [], []
    import asyncio

    async def save(name, **k):
        saved.append((name, k))
        return name == "小明"
    ns = {"re": re, "spawn": lambda c: asyncio.run(c), "log_print": logs.append, "save_viewer_profile": save,
          "viewer_seen_this_session": lambda n: True, "is_known_viewer": lambda n: True}
    for n in ("_VIEWER_UPDATE_RE", "_save_viewer_updates", "_save_one_viewer_update"):
        exec(compile(ast.Module(body=[_node(n)], type_ignores=[]), "x", "exec"), ns)
    n = ns["_save_viewer_updates"]("謝謝明哥！[VIEWER_UPDATE:小明|CALL:明哥|REL:頭號粉絲|IMP:很熱情] 晚安～")
    assert n == 1 and saved == [("小明", {"call": "明哥", "relationship": "頭號粉絲", "impression": "很熱情"})]
    assert ns["_save_viewer_updates"]("沒有標籤") == 0
    assert len(logs) == 1 and "小明" in logs[0]
    ns["_save_viewer_updates"]("[VIEWER_UPDATE:小美|CALL:美美]")    # 都沒變（save 回 False）：不記「記住觀眾」
    assert len(logs) == 1


def test_unchanged_viewer_profile_is_not_rewritten(monkeypatch):
    """她每句回話都帶一樣的 [VIEWER_UPDATE:…]，以前每次都寫本地檔＋雲端（2026-10-31 Fable 看實機日誌）。"""
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import core.memory as mem
    stored = []
    prof = {"call": "明哥", "relationship": "頭號粉絲", "impression": "很熱情",
            "last_seen": datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")}

    async def get(name):
        return dict(prof)
    monkeypatch.setattr(mem, "get_viewer_profile", get)
    monkeypatch.setattr(mem, "_store_viewer_profile_local", lambda n, p: stored.append(dict(p)))
    monkeypatch.setattr(mem.db_module, "db", None)
    assert asyncio.run(mem.save_viewer_profile("小明", call="明哥", relationship="頭號粉絲", impression="很熱情")) is False
    assert stored == []
    assert asyncio.run(mem.save_viewer_profile("小明", impression="很熱情，常送玫瑰")) is True   # 有變：寫
    assert stored[-1]["impression"] == "很熱情，常送玫瑰"
    prof["last_seen"] = "2026-10-01 12:00"                                                      # 很久沒見：更新見到時間
    assert asyncio.run(mem.save_viewer_profile("小明", call="明哥")) is True


async def _noop():
    return None


def _coro():
    return _noop()


def test_live_brain_turn_saves_viewer_updates():
    src = ast.get_source_segment(MAIN, _node("continuous_live_worker"))
    assert "_speak_brain_turn(" in src
    assert "_save_viewer_updates(text)" in ast.get_source_segment(MAIN, _node("_speak_brain_turn"))


def test_gemini_piano_intent_checks_the_piano_is_still_out():
    src = ast.get_source_segment(MAIN, _node("add_to_streamer_mind_board"))
    i = src.index("not pe.is_piano_active or getattr(pe, \"PIANO_SESSION_ID\", None) != _piano_session")
    assert i < src.index("await pe.play_virtual_piano(")
