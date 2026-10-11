# -*- coding: utf-8 -*-
"""光桿點名短路（2026-10-11：單喊名字＋安靜＋冷卻→應一聲，不燒大腦審）。
主檔太重不直接 import，用 AST 抽出來跑。"""
import ast
import os
import re
import unicodedata


def _load():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {"re": re, "unicodedata": unicodedata,
          "_BARE_PING_NAMES": None, "_PING_COOLDOWN_SEC": None, "_PING_QUIET_SEC": None}
    funcs = {}
    consts = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in (
                        "_BARE_PING_NAMES", "_PING_COOLDOWN_SEC", "_PING_QUIET_SEC"):
                    consts[t.id] = ast.literal_eval(n.value)
        if isinstance(n, ast.FunctionDef) and n.name in (
                "_is_bare_ping", "_ping_short_circuit"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    ns.update(consts)
    # 重綁：函數 exec 時缺的常數現在補上
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in (
                "_is_bare_ping", "_ping_short_circuit"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs, consts


def test_bare_ping_detect():
    f = _load()[0]["_is_bare_ping"]
    for ping in ["7L", "7l", " 7L ", "7L！", "7L～", "小7", "7寶", "小七",
                 "7L，", "７Ｌ", "7L。", "😊7L😊"]:
        assert f(ping) is True, ping
    for not_ping in ["7L你好嗎", "7L在嗎", "唱歌7L", "7L唱首歌", "你好7L你好",
                     "", "哈哈哈", "716", "7", "L", "小七呢今天好嗎"]:
        assert f(not_ping) is False, not_ping


def test_short_circuit_gates():
    funcs, consts = _load()
    f = funcs["_ping_short_circuit"]
    now = 1000.0
    ok = f("Johnny", "7L", now, last_speech_ts=now - 60.0, last_ping_ts=0.0)
    assert ok != "" and "10字" in ok
    # 剛說過話（忙）→ 不搶
    assert f("Johnny", "7L", now, last_speech_ts=now - 5.0, last_ping_ts=0.0) == ""
    # 冷卻內重喊 → 不理（防刷屏）
    assert f("Johnny", "7L", now, last_speech_ts=now - 60.0,
             last_ping_ts=now - 30.0) == ""
    # 冷卻過 → 再應
    assert f("Johnny", "7L", now, last_speech_ts=now - 60.0,
             last_ping_ts=now - 200.0) != ""
    # 有實質內容 → 交正常流程
    assert f("Johnny", "7L你好嗎", now, last_speech_ts=now - 60.0,
             last_ping_ts=0.0) == ""
    assert consts["_PING_COOLDOWN_SEC"] == 120.0
    assert consts["_PING_QUIET_SEC"] == 20.0
