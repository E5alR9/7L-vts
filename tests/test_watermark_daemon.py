"""水印常駐守護（2026-10-11：之前只跑一次就結束，誰關掉就永遠掉）。

主檔太重不直接 import，用 AST 把 worker 抽出來跑，vc 打樁。
"""
import ast
import asyncio
import os
import types

import pytest


def _load_worker():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    vc = types.ModuleType("vc")
    vc.vts_lock = asyncio.Lock()
    ns = {"asyncio": asyncio, "vc": vc}
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") == "WATERMARK_REASSERT_SEC" for t in n.targets):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "anti_watermark_worker":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
    return ns["anti_watermark_worker"], ns["WATERMARK_REASSERT_SEC"]


class FakeVTS:
    def __init__(self):
        self.activations = 0

    async def request(self, payload):
        assert payload["data"]["expressionFile"] == "水印.exp3.json"
        assert payload["data"]["active"] is True
        self.activations += 1
        return {"data": {}}


def test_watermark_reasserts_periodically():
    worker, _ = _load_worker()

    async def main():
        fake = FakeVTS()
        t = asyncio.create_task(worker(fake, interval=0.05))
        await asyncio.sleep(2.25)  # 初次 2 秒＋兩輪
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        return fake.activations

    assert asyncio.run(main()) >= 3


def test_watermark_interval_default_sane():
    _, interval = _load_worker()
    assert 30 <= interval <= 300, "守護間隔太密洗 VTS，太疏等於沒有"
