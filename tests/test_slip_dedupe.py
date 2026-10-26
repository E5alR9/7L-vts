# -*- coding: utf-8 -*-
"""紙條去重（2026-10-11：一次點歌三張同字紙條，自斷三次，應答被砍死）。
2026-10-26 改查流水帳（core.eventlog）：交給主腦時記一筆 slip，10 秒內同文的就是重複；
送失敗的本來就沒記，不用再撤銷。主檔太重不直接 import，用 AST 抽出來跑。"""
import ast
import os

from core import eventlog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    tree = ast.parse(open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read())
    ns = {"eventlog": eventlog, "log_swallowed": lambda: None}
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SLIP_DEDUPE_SEC":
            ns["_SLIP_DEDUPE_SEC"] = ast.literal_eval(n.value)
        if isinstance(n, ast.FunctionDef) and n.name in ("_slip_is_dupe", "_record_slip"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
    assert ns["_SLIP_DEDUPE_SEC"] == 10.0
    return ns["_slip_is_dupe"], ns["_record_slip"]


def test_dupe_within_window():
    dupe, record = _load()
    assert dupe("同一張紙條", 1000.0) is False       # 還沒交過
    record("同一張紙條", "dad", "", "live", 1000.0)
    assert dupe("同一張紙條", 1005.0) is True        # 5 秒後重來，擋
    assert dupe("同一張紙條", 1011.0) is False       # 11 秒後，已過窗
    assert dupe("另一張紙條", 1005.0) is False       # 不同文案不擋
    record("點歌", "", "", "rest", 1020.0)           # REST 接手的也算交過
    assert dupe("點歌", 1021.0) is True


def test_failed_send_is_not_recorded_so_resend_goes_through():
    """送失敗退回重送（2026-10-17）：沒送成功就沒記，10 秒內重送照樣放行。"""
    dupe, record = _load()
    assert dupe("點歌紙條", 1000.0) is False
    # 送失敗：沒呼叫 record
    assert dupe("點歌紙條", 1002.0) is False
    record("點歌紙條", "dad", "", "live", 1002.0)
    assert dupe("點歌紙條", 1003.0) is True


def test_slip_record_carries_identity_for_rescue():
    _, record = _load()
    record("[黑板同步] 老爸傳來文字訊息：唱晴天", "dad", "", "live", 1000.0)
    record("系統提醒", "", "", "rest", 1001.0)
    live = eventlog.get().recent("slip", since=900.0, brain="live")
    assert [(e["text"], e["who"]) for e in live] == [("[黑板同步] 老爸傳來文字訊息：唱晴天", "dad")]


def test_live_worker_has_no_local_time_import():
    """2026-10-17 事故：send_system_prompts_to_live 裡的 `import time` 讓 time 變區域變數，
    去重那行每次 UnboundLocalError 被 except 吞掉，去重從沒生效。"""
    tree = ast.parse(open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "send_system_prompts_to_live")
    local_imports = [a.name for n in ast.walk(fn) if isinstance(n, ast.Import) for a in n.names]
    assert "time" not in local_imports
