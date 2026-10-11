# -*- coding: utf-8 -*-
"""自主閒聊門檻（2026-10-11：安靜夠久＋冷卻過＋開機後有人說過話才遞紙條）。
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
                        "_IDLE_QUIET_SEC", "_IDLE_QUIET_PIANO_SEC", "_IDLE_COOLDOWN_SEC"):
                    ns[t.id] = ast.literal_eval(n.value)
        if isinstance(n, ast.FunctionDef) and n.name == "_idle_chatter_due":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_idle_chatter_due":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs, ns


def test_due_logic():
    f = _load()[0]["_idle_chatter_due"]
    now = 10000.0
    # 開機沒人說過話：不對空房間自言自語
    assert f(now, 0.0, 0.0) is False
    assert f(now, None, None) is False
    # 安靜不夠：不吵
    assert f(now, now - 60.0, 0.0) is False
    # 安靜夠＋冷卻過：開口
    assert f(now, now - 200.0, 0.0) is True
    # 冷卻內：閉嘴（不當話癆）
    assert f(now, now - 200.0, now - 60.0) is False
    assert f(now, now - 200.0, now - 500.0) is True
    # 彈琴中門檻更高：9 分鐘不夠，11 分鐘夠
    assert f(now, now - 540.0, 0.0, piano_active=True) is False
    assert f(now, now - 660.0, 0.0, piano_active=True) is True


def test_consts_sane():
    _, ns = _load()
    assert ns["_IDLE_QUIET_SEC"] == 180.0
    assert ns["_IDLE_QUIET_PIANO_SEC"] == 600.0
    assert ns["_IDLE_COOLDOWN_SEC"] == 420.0
