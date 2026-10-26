# -*- coding: utf-8 -*-
"""畫面變化只讓她知道、不請她開口（老爸 2026-10-26 決定）：餘光視覺看到新動態走 add_brain_context，不遞紙條。"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_peripheral_vision_puts_changes_into_background_context():
    src = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "peripheral_vision_worker")
    called = {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "add_brain_context" in called and "send_brain_slip" not in called
