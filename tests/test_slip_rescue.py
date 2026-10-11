# -*- coding: utf-8 -*-
"""紙條救援判定（2026-10-11：聊天紙條靜默丟失，工具＋說話＋回包三無才撿）。
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
        if isinstance(n, ast.FunctionDef) and n.name == "_slip_needs_rescue":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs


def test_needs_rescue_truth_table():
    f = _load()["_slip_needs_rescue"]
    s = 1000.0
    assert f(s + 10.0, s, 0.0, 0.0, 0.0) is False   # 還沒到 20 秒，不急
    assert f(s + 20.0, s, 0.0, 0.0, 0.0) is True    # 三無，撿
    assert f(s + 60.0, s, 0.0, 0.0, 0.0) is True
    assert f(s + 25.0, s, s + 5.0, 0.0, 0.0) is False   # 調過工具，不撿
    assert f(s + 25.0, s, 0.0, s + 5.0, 0.0) is False   # 說過話，不撿
    assert f(s + 25.0, s, 0.0, 0.0, s + 5.0) is False   # 服務端有回包（慢但活著），不撿
    assert f(s + 25.0, s, s - 5.0, s - 5.0, s - 5.0) is True  # 全是送紙條之前的事，撿
    assert f(s + 25.0, s, s, s, s, timeout=20.0) is False     # 卡邊界算有動靜
    assert f(s + 30.0, s, 0.0, 0.0, 0.0, timeout=60.0) is False  # 自訂超時
