# -*- coding: utf-8 -*-
"""AI 狀態唯一轉換點 set_ai_state＋唱歌旗單一真相（2026-10-23）。
主檔太重不 import，用 AST 抽出來跑；翻唱管線走 _core_set_ai_state 交給主核心轉。"""
import ast
import os
import types

from conftest import ROOT  # noqa: F401
import services.auto_cover_pipeline as acp


def _vts_src():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8") as f:
        return f.read()


def _load():
    logs, events = [], []
    wd = types.SimpleNamespace(
        broadcast_event=lambda t, d, keep_history=True: events.append((t, d, keep_history)))
    ns = {"current_ai_state": "IDLE", "log_print": logs.append, "web_dash": wd, "auto_cover": acp}
    for n in ast.parse(_vts_src()).body:
        if isinstance(n, ast.FunctionDef) and n.name in ("set_ai_state", "is_singing_active"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
    return ns, logs, events


def test_set_ai_state_transition_logs_and_broadcasts():
    ns, logs, events = _load()
    assert ns["set_ai_state"]("THINKING", "處理對話") is True
    assert ns["current_ai_state"] == "THINKING"
    assert len(logs) == 1 and "IDLE → THINKING" in logs[0] and "處理對話" in logs[0]
    t, d, keep = events[0]
    assert t == "system_state_update" and keep is False  # 高頻事件不進回放歷史
    assert d["ai_state"] == "thinking" and d["prev"] == "idle"


def test_set_ai_state_same_state_is_noop():
    ns, logs, events = _load()
    assert ns["set_ai_state"]("IDLE") is False
    assert logs == [] and events == []


def test_set_ai_state_only_from_guard():
    ns, _, _ = _load()
    ns["current_ai_state"] = "SINGING"
    assert ns["set_ai_state"]("IDLE", only_from="TALKING") is False
    assert ns["current_ai_state"] == "SINGING"  # 不是 TALKING 就不碰
    assert ns["set_ai_state"]("IDLE", only_from=("TALKING", "SINGING")) is True
    assert ns["current_ai_state"] == "IDLE"


def test_main_has_no_direct_state_writes():
    """除了 set_ai_state 自己和檔頭初值，主檔不准再直接改寫 current_ai_state／留唱歌旗拷貝。"""
    tree = ast.parse(_vts_src())
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name == "set_ai_state":
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id in ("current_ai_state", "IS_SINGING_ACTIVE")
                    for t in n.targets):
                bad.append((fn.name, n.lineno))
    assert bad == []
    top = [t.id for n in tree.body if isinstance(n, ast.Assign)
           for t in n.targets if isinstance(t, ast.Name)]
    assert "IS_SINGING_ACTIVE" not in top


def test_is_singing_active_reads_pipeline_flag(monkeypatch):
    ns, _, _ = _load()
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", True)
    assert ns["is_singing_active"]() is True
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", False)
    assert ns["is_singing_active"]() is False


def test_pipeline_routes_state_through_core(monkeypatch):
    calls = []
    monkeypatch.setattr(acp, "_HOST", {"set_ai_state": lambda new, reason="", only_from=None: calls.append((new, only_from))})
    acp._core_set_ai_state("IDLE", "測試", only_from="SINGING")
    assert calls == [("IDLE", "SINGING")]
    monkeypatch.setattr(acp, "_HOST", {})
    acp._core_set_ai_state("IDLE")  # main() 還沒交進來就安靜跳過


def test_broadcast_without_history_keeps_replay(monkeypatch):
    import services.web_dashboard as web_dash
    monkeypatch.setattr(web_dash, "RECENT_EVENTS", [])
    monkeypatch.setattr(web_dash, "CONNECTED_CLIENTS", set())
    web_dash.broadcast_event("system_state_update", {"ai_state": "talking"}, keep_history=False)
    assert web_dash.RECENT_EVENTS == []
    web_dash.broadcast_event("chat_sent", {"text": "hi"})
    assert [e["type"] for e in web_dash.RECENT_EVENTS] == ["chat_sent"]
