# -*- coding: utf-8 -*-
"""忙碌指示（跑活兒掛暈，閒了摘掉）：決策純函數全真值表＋忙碌判定。
主檔太重不直接 import，用 AST 抽出來跑。"""
import ast
import asyncio
import os
import sys
import types

import pytest


def _load():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    import services.auto_cover_pipeline as ac
    pe = types.ModuleType("pe")
    pe.PENDING_PIANO_PRELOADS = set()
    ns = {"asyncio": asyncio, "ac": None, "pe": pe,
          "_RUNNING_SUBAGENT_TASKS": set()}
    # _background_busy 內部 import ac 走真模組；pe/任務集合用樁
    del ns["ac"]
    funcs = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in (
                "_background_busy", "_busy_face_action"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs, ns, pe, ac


def test_face_action_truth_table():
    funcs, _, _, _ = _load()
    f = funcs["_busy_face_action"]
    H, O = "halo.exp3.json", "other.exp3.json"
    assert f(True, False, set(), H) == ("set", True)      # 忙＋臉空→掛
    assert f(True, True, {H}, H) == ("none", True)        # 忙＋暈已在→維持
    assert f(True, False, {O}, H) == ("none", False)      # 忙＋臉有戲→不搶
    assert f(True, False, {H, O}, H) == ("none", False)   # 忙＋暈＋別的→不動
    assert f(False, True, {H}, H) == ("reset", False)     # 閒＋自己掛的→摘
    assert f(False, True, {O}, H) == ("none", False)      # 閒＋臉被換→不管
    assert f(False, False, set(), H) == ("none", False)
    assert f(False, False, set(), "") == ("none", False)  # 沒暈檔→永不動手


def test_background_busy_sources():
    funcs, ns, pe, ac = _load()
    b = funcs["_background_busy"]
    assert b() is False
    ns["_RUNNING_SUBAGENT_TASKS"] = {"t"}
    try:
        assert b() is True
    finally:
        ns["_RUNNING_SUBAGENT_TASKS"] = set()
    # RVC 準備中
    class T:
        def done(self):
            return False
    old = ac._PREPARE_TASK
    ac._PREPARE_TASK = T()
    try:
        assert b() is True
    finally:
        ac._PREPARE_TASK = old
    # 鋼琴預載中
    pe.PENDING_PIANO_PRELOADS.add("x")
    try:
        assert b() is True
    finally:
        pe.PENDING_PIANO_PRELOADS.clear()
    assert b() is False
