# -*- coding: utf-8 -*-
"""關鍵路徑不准默默吞錯（2026-10-25）：這些地方壞了功能就悄悄失效（鋼琴看門狗、斷線點歌救援、
給 Live 主腦的紙條、記憶載入／寫回、VTS 收訊、YT 陪看送畫面…），except 本體只有 pass 的一律改 log_swallowed()
（例外照吞、流程不變，同位置 60 秒最多一行）。清理暫存檔、關聲道、後台廣播這類允許失敗的不在此列。"""
import ast
import os

import pytest

from conftest import ROOT

GUARDED = {
    "vts_7L_test.py": ["_rescue_missed_song_requests", "get_user_profile", "update_subtitle"],
    "services/auto_cover_pipeline.py": ["scan_originals_once"],
    "services/piano_engine.py": ["piano_liveness_watchdog_worker", "_mark_piano_offline"],
    "services/roformer_sep.py": ["_monitor"],
    "services/vts_client.py": ["_socket_reader"],
    "services/tts_router.py": ["tts_cache_put"],
    "core/memory.py": ["init_unified_memory"],
}


def _silent_broad(h):
    broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"))
    return broad and all(isinstance(b, ast.Pass) for b in h.body)


@pytest.mark.parametrize("rel,funcs", sorted(GUARDED.items()))
def test_critical_paths_do_not_swallow_silently(rel, funcs):
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    found = {}
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in funcs:
            found[n.name] = [h.lineno for h in ast.walk(n) if isinstance(h, ast.ExceptHandler) and _silent_broad(h)]
    assert set(found) == set(funcs), set(funcs) - set(found)
    assert not any(found.values()), {k: v for k, v in found.items() if v}


def test_live_paper_drops_are_logged():
    """給 Live 主腦的紙條塞不進去（佇列滿）不能無聲消失。"""
    src = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Try):
            continue
        body = ast.get_source_segment(src, n.body[0]) or ""
        if "LIVE_API_SYSTEM_PROMPT_QUEUE.put_nowait" in body:
            assert not any(_silent_broad(h) for h in n.handlers), n.lineno
