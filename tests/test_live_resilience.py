# -*- coding: utf-8 -*-
"""Live 韌性：同鑰重連決策＋哨兵化石過濾（純函數）。
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
        if isinstance(n, ast.FunctionDef) and n.name in (
                "_rotate_live_key", "_next_live_key", "_split_fossil_batch"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    # _next_live_key 內部調 _rotate_live_key：補進同一命名空間重綁
    if "_next_live_key" in funcs and "_rotate_live_key" in funcs:
        funcs["_next_live_key"].__globals__["_rotate_live_key"] = funcs["_rotate_live_key"]
    return funcs


def _msg(content, age_s, attempts=0, now=1000.0):
    return {"user": "Johnny", "content": content, "time": now - age_s,
            "status": "processing", "attempts": attempts}


# ── 鑰匙輪轉 ─────────────────────────────────────────────
def test_rotate_wraps():
    f = _load()["_rotate_live_key"]
    assert f(5, 0, 32, 2) == (6, 0)    # 普通前進
    assert f(31, 0, 32, 2) == (0, 1)   # key 用盡→換模型
    assert f(31, 1, 32, 2) == (0, 0)   # 全用盡→重頭


def test_quota_rotates_immediately():
    f = _load()["_next_live_key"]
    k, m, fails, rotated, wait = f(True, 2, 5, 0, 32, 2)
    assert (k, m, fails, rotated, wait) == (6, 0, 0, True, 2)


def test_clean_close_retries_same_key():
    f = _load()["_next_live_key"]
    assert f(False, 0, 5, 0, 32, 2) == (5, 0, 1, False, 2)   # 第1次：同鑰＋2s
    assert f(False, 1, 5, 0, 32, 2) == (5, 0, 2, False, 4)   # 第2次：同鑰＋4s
    assert f(False, 2, 5, 0, 32, 2) == (5, 0, 3, False, 6)   # 第3次：同鑰＋6s
    k, m, fails, rotated, wait = f(False, 3, 5, 0, 32, 2)   # 第4次：輪轉＋歸零
    assert (k, m, fails, rotated, wait) == (6, 0, 0, True, 2)


def test_clean_close_wrap_and_backoff_cap():
    f = _load()["_next_live_key"]
    assert f(False, 3, 31, 0, 32, 2)[:2] == (0, 1)           # 邊界照樣換模型
    assert f(False, 2, 5, 0, 32, 2)[4] == 6                  # 退避 2/4/6/8 上限
    k, m, fails, rotated, wait = f(False, 99, 5, 0, 32, 2)  # 計數器爆了也只輪轉
    assert (k, m, fails, rotated) == (6, 0, 0, True)


# ── 化石過濾 ─────────────────────────────────────────────
def test_fossil_split():
    f = _load()["_split_fossil_batch"]
    fresh_msg = _msg("嗨", age_s=10)
    old_msg = _msg("兩分鐘前的問題", age_s=200)
    tried_msg = _msg("審爛了", age_s=30, attempts=5)
    fresh, dropped = f([fresh_msg, old_msg, tried_msg], 1000.0)
    assert fresh == [fresh_msg]
    assert dropped == [old_msg, tried_msg]
    assert old_msg["status"] == "read" and tried_msg["status"] == "read"
    assert fresh_msg["status"] == "processing"  # 新的不動


def test_fossil_edge_cases():
    f = _load()["_split_fossil_batch"]
    assert f([], 1000.0) == ([], [])
    assert f(None, 1000.0) == ([], [])
    # 邊界：正好 180s 留，181s 丟；4 次留，5 次丟
    keep = _msg("邊", age_s=180, attempts=4)
    assert f([keep], 1000.0)[0] == [keep]
    drop1 = _msg("老", age_s=181, attempts=0)
    drop2 = _msg("煩", age_s=10, attempts=5)
    assert f([drop1, drop2], 1000.0) == ([], [drop1, drop2])
    # 沒 time 欄位不炸（當新訊息）
    no_ts = {"user": "x", "content": "y", "status": "processing"}
    assert f([no_ts], 1000.0)[0] == [no_ts]
