# -*- coding: utf-8 -*-
"""紙條去重（2026-10-11：一次點歌三張同字紙條，自斷三次，應答被砍死）。
主檔太重不直接 import，用 AST 抽出來跑。"""
import ast
import os


def _load():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {}
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in (
                        "_SLIP_LAST_TS", "_SLIP_DEDUPE_SEC", "_SLIP_LEDGER_MAX"):
                    ns[t.id] = ast.literal_eval(n.value)
        if isinstance(n, ast.FunctionDef) and n.name == "_slip_is_dupe":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    # 常數後抽：函數定義時缺的名字，調用前補上，重綁一次
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_slip_is_dupe":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    assert ns["_SLIP_DEDUPE_SEC"] == 10.0 and ns["_SLIP_LEDGER_MAX"] == 200
    return funcs, ns


def test_dupe_within_window():
    funcs, ns = _load()
    f = funcs["_slip_is_dupe"]
    ns["_SLIP_LAST_TS"].clear()
    try:
        assert f("同一張紙條", 1000.0) is False  # 首送放行＋記帳
        assert f("同一張紙條", 1005.0) is True   # 5 秒後重來，擋
        assert f("同一張紙條", 1011.0) is False  # 11 秒後，已過窗
        assert f("另一張紙條", 1011.5) is False  # 不同文案不擋
        assert f("", 1012.0) is False           # 空字串也記帳（避免空轉刷屏）
        assert f("", 1013.0) is True
    finally:
        ns["_SLIP_LAST_TS"].clear()


def test_ledger_prunes():
    funcs, ns = _load()
    f = funcs["_slip_is_dupe"]
    ns["_SLIP_LAST_TS"].clear()
    try:
        ns["_SLIP_DEDUPE_SEC"] = 0.0  # 關掉時間窗，只看剪枝
        # _SLIP_LEDGER_MAX 在函數 globals，AST 命名空間共用 ns，先塞值
        ns["_SLIP_LEDGER_MAX"] = 5
        for i in range(10):
            assert f(f"紙條{i}", 1000.0 + i) is False
        assert len(ns["_SLIP_LAST_TS"]) <= 5
    finally:
        ns["_SLIP_LAST_TS"].clear()
