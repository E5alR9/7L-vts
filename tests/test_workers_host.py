# -*- coding: utf-8 -*-
"""從主檔搬到 workers/ 的程式（2026-10-26，docs/REDESIGN.md 的 I）經 host.<名稱> 讀寫主程式狀態。
契約：用到的名稱都登記在 HOST_ATTRS、主程式真的都有定義、主程式 import 後有 bind。主檔太重不 import，用 AST 核對。"""
import ast
import glob
import importlib
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_SRC = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
WORKERS = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "workers", "*.py"))
                 if not p.endswith("__init__.py"))


def _main_top_level_names():
    names = set()
    for n in ast.walk(ast.parse(MAIN_SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.col_offset == 0:
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)) and n.col_offset == 0:
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.Assign) and n.col_offset == 0:
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
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
