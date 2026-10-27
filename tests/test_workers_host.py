# -*- coding: utf-8 -*-
"""從主檔搬到 workers/ 的程式（2026-10-26，docs/REDESIGN.md 的 I）經 host.<名稱> 讀寫主程式狀態。
契約：用到的名稱都登記在 HOST_ATTRS、主程式真的都有定義、主程式 import 後有 bind。主檔太重不 import，用 AST 核對。"""
import ast
import glob
import importlib
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC  # noqa: E402
WORKERS = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "workers", "*.py"))
                 if not p.endswith("__init__.py"))


def _main_top_level_names():
    """主程式模組層級的名稱（頂層 if／try／with 區塊裡定義的也算，函式裡的不算）。"""
    names = set()

    def visit(stmts):
        for n in stmts:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in n.names)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    names.update(x.id for x in ast.walk(t) if isinstance(x, ast.Name))
            for field in ("body", "orelse", "finalbody", "handlers"):
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    sub = getattr(n, field, None)
                    if isinstance(sub, list):
                        visit(sub)
    visit(ast.parse(MAIN_SRC).body)
    return names


def test_there_are_workers():
    assert {"face_tracking", "system_audio", "cma_panel"} <= set(WORKERS)


@pytest.mark.parametrize("name", WORKERS)
def test_host_attrs_are_registered_and_defined(name):
    src = open(os.path.join(ROOT, "workers", f"{name}.py"), encoding="utf-8").read()
    used = {n.attr for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "host"}
    mod = importlib.import_module(f"workers.{name}")
    assert used == set(mod.HOST_ATTRS), (used ^ set(mod.HOST_ATTRS))
    assert set(mod.HOST_ATTRS) - _main_top_level_names() == set()
    assert f"{name}.bind(sys.modules[__name__])" in MAIN_SRC


@pytest.mark.parametrize("name", WORKERS)
def test_module_does_not_import_main(name):
    src = open(os.path.join(ROOT, "workers", f"{name}.py"), encoding="utf-8").read()
    assert "vts_7L_test" not in src and "sys.modules[\"__main__\"]" not in src
