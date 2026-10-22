# -*- coding: utf-8 -*-
"""core.utils.log_swallowed：取代 except Exception: pass 的節流 log（2026-10-23）。
同一位置每 60 秒最多一行、壓下的次數併到下一行；本身不拋錯、不改控制流程。"""
import ast
import asyncio
import os
import types

from conftest import ROOT  # noqa: F401
import core.utils as cu


def _boom_at_one_site(n):
    """同一個 except 位置連吞 n 次，回傳吞完後繼續跑到的次數（驗證控制流程照舊）"""
    reached = 0
    for _ in range(n):
        try:
            raise ValueError("壞掉了")
        except Exception:
            cu.log_swallowed()
        reached += 1
    return reached


def test_same_site_logs_once_per_interval(monkeypatch):
    logs = []
    monkeypatch.setattr(cu, "log_print", logs.append)
    monkeypatch.setattr(cu, "_SWALLOWED", {})
    clock = [1000.0]
    monkeypatch.setattr(cu.time, "monotonic", lambda: clock[0])
    assert _boom_at_one_site(5) == 5
    assert len(logs) == 1
    assert "_boom_at_one_site" in logs[0] and "ValueError" in logs[0] and "壞掉了" in logs[0]
    assert "test_log_swallowed.py:" in logs[0]
    clock[0] += 61.0
    _boom_at_one_site(1)
    assert len(logs) == 2 and "另壓下 4 次" in logs[1]


def test_different_sites_are_independent(monkeypatch):
    logs = []
    monkeypatch.setattr(cu, "log_print", logs.append)
    monkeypatch.setattr(cu, "_SWALLOWED", {})
    try:
        raise KeyError("a")
    except Exception:
        cu.log_swallowed()
    try:
        raise KeyError("b")
    except Exception:
        cu.log_swallowed("自訂名")
    assert len(logs) == 2 and "自訂名" in logs[1]


def test_never_raises(monkeypatch):
    def _broken(_msg):
        raise RuntimeError("log 掛了")
    monkeypatch.setattr(cu, "log_print", _broken)
    monkeypatch.setattr(cu, "_SWALLOWED", {})
    assert _boom_at_one_site(3) == 3
    cu.log_swallowed()  # 不在 except 裡呼叫也不炸


def test_worker_survives_failures_and_logs_throttled(monkeypatch):
    """真 worker 走一遍：VTS 每次都失敗，水印守護照樣一輪輪重試，log 只記一行。"""
    logs = []
    monkeypatch.setattr(cu, "log_print", logs.append)
    monkeypatch.setattr(cu, "_SWALLOWED", {})
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    vc = types.ModuleType("vc")
    vc.vts_lock = asyncio.Lock()
    ns = {"asyncio": asyncio, "vc": vc, "log_swallowed": cu.log_swallowed, "WATERMARK_REASSERT_SEC": 60.0}
    for n in ast.parse(src).body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "anti_watermark_worker":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)

    class _DeadVTS:
        calls = 0

        async def request(self, payload):
            _DeadVTS.calls += 1
            raise ConnectionError("VTS 沒開")

    async def main():
        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
        t = asyncio.create_task(ns["anti_watermark_worker"](_DeadVTS(), interval=0.0))
        for _ in range(50):
            await _real_sleep(0)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    _real_sleep = asyncio.sleep

    async def _fast_sleep(_sec):
        await _real_sleep(0)

    asyncio.run(main())
    assert _DeadVTS.calls >= 5
    assert len(logs) == 1 and "anti_watermark_worker" in logs[0] and "ConnectionError" in logs[0]
