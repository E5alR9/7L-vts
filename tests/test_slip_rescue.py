# -*- coding: utf-8 -*-
"""紙條救援判定（2026-10-11：聊天紙條靜默丟失，工具＋說話＋產出三無才撿）。
2026-10-26：第三項從「服務端有回包」改成「主腦有產出」：金鑰額度用完時連線還在、照樣有回包，舊判法永遠不撿；
連兩張紙條沒產出就換金鑰重連。主檔太重不直接 import，用 AST 抽出來跑。"""
import ast
import os


NAMES = {"_slip_needs_rescue", "_brain_output_seen", "_note_live_mute"}


def _load(ns=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {} if ns is None else ns
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in NAMES:
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
    assert f(s + 25.0, s, 0.0, 0.0, s + 5.0) is False   # 有轉寫的字出來（慢但在講），不撿
    assert f(s + 25.0, s, s - 5.0, s - 5.0, s - 5.0) is True  # 全是送紙條之前的事，撿
    assert f(s + 25.0, s, s, s, s, timeout=20.0) is False     # 卡邊界算有動靜
    assert f(s + 30.0, s, 0.0, 0.0, 0.0, timeout=60.0) is False  # 自訂超時


def test_two_unanswered_slips_close_the_session_once():
    """連兩張紙條沒產出：關連線一次（換金鑰）；中間有產出就重算。"""
    import time
    from collections import deque
    closed, logs = [], []

    class Session:
        async def close(self):
            closed.append(1)

    ns = {"time": time, "LIVE_MUTE_STRIKES": 2, "_LIVE_MUTE": {"strikes": 0, "rotate": ""},
          "LAST_BRAIN_OUTPUT_TS": 0.0, "GLOBAL_LIVE_SESSION": Session(),
          "log_print": logs.append, "spawn": lambda coro: (coro.close(), closed.append(1)),
          "_LIVE_SLIP_RETRY": deque()}
    f = _load(ns)
    assert f["_note_live_mute"]("紙條一") is False
    assert closed == [] and ns["_LIVE_MUTE"]["strikes"] == 1
    f["_brain_output_seen"]()                                  # 中間講過話：重算
    assert ns["_LIVE_MUTE"]["strikes"] == 0 and ns["LAST_BRAIN_OUTPUT_TS"] > 0
    assert f["_note_live_mute"]("紙條二") is False
    assert f["_note_live_mute"](("紙條三", "dad", "妳好", "")) is True
    assert closed == [1] and ns["_LIVE_MUTE"]["rotate"]
    assert list(ns["_LIVE_SLIP_RETRY"]) == [("紙條三", "dad", "妳好", "")]   # 沒人理的那張交給新連線，身分照舊
    assert f["_note_live_mute"]("紙條四") is False             # 已經在換了，不重複關
    assert closed == [1] and len(ns["_LIVE_SLIP_RETRY"]) == 1
    assert any("換一把金鑰" in l for l in logs)
