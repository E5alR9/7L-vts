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


# —— 背景任務（2026-10-25）：沒存起來的 create_task 可能跑到一半被回收，例外也沒人接 ——

def test_spawn_keeps_tasks_alive_and_logs_failures(monkeypatch):
    import asyncio
    import gc
    import core.utils as u
    logged = []
    monkeypatch.setattr(u, "log_print", lambda m, *a, **k: logged.append(m))
    u._BG_FAIL_LOG.clear()

    async def boom():
        await asyncio.sleep(0)
        raise RuntimeError("壞掉了")

    async def slow(out):
        await asyncio.sleep(0.05)
        out.append("跑完")

    async def go():
        out = []
        u.spawn(slow(out))
        gc.collect()                       # 沒人存的任務也不能被回收
        u.spawn(boom(), label="pe.play_virtual_piano({'song_name': '小星星'})")
        await asyncio.sleep(0.1)
        return out
    assert asyncio.run(go()) == ["跑完"]
    assert len(logged) == 1 and "小星星" in logged[0] and "壞掉了" in logged[0] and "Traceback" in logged[0]
    assert not u._BG_TASKS                 # 跑完就放掉


def test_repeated_background_failures_are_throttled(monkeypatch):
    import asyncio
    import core.utils as u
    logged = []
    monkeypatch.setattr(u, "log_print", lambda m, *a, **k: logged.append(m))
    u._BG_FAIL_LOG.clear()

    async def boom():
        raise ValueError("x")

    async def go():
        for _ in range(5):
            u.spawn(boom())
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert len(logged) == 1                # 同一個協程一分鐘只記一次


@pytest.mark.parametrize("rel", ["vts_7L_test.py", "services/web_dashboard.py", "services/piano_engine.py",
                                 "services/auto_cover_pipeline.py", "services/dashboard_bridge.py",
                                 "services/yt_companion_service.py"])
def test_no_fire_and_forget_create_task(rel):
    tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
    bare = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute) and n.value.func.attr in ("create_task", "ensure_future")]
    assert not bare, f"{rel} 這幾行的背景任務沒存起來，改用 spawn()：{bare}"


@pytest.mark.parametrize("rel,ceiling", [("vts_7L_test.py", 37), ("services/piano_engine.py", 7)])
def test_silent_swallows_do_not_grow_back(rel, ceiling):
    """2026-10-25 健檢：清理類（刪暫存檔、關程序、停音效、後台廣播）以外的 except Exception: pass 都改成 log_swallowed，
    主程式剩下的多是清理類與開機環境調整。數量只准變少。"""
    tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
    n = sum(1 for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler) and isinstance(h.type, ast.Name)
            and h.type.id == "Exception" and h.name is None and len(h.body) == 1 and isinstance(h.body[0], ast.Pass))
    assert n <= ceiling, f"{rel} 的 except Exception: pass 有 {n} 處（上限 {ceiling}），新的請用 log_swallowed()"
