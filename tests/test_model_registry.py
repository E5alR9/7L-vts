# -*- coding: utf-8 -*-
"""模型名稱唯一出處（2026-10-25）：Gemini 模型名只准寫在 core/llm_engine.py。
散在各檔寫死的時候，作曲一直打已下架的 gemini-2.5-flash，每次 404 都沒人發現。"""
import ast
import glob
import os
import re

from conftest import ROOT

_MODEL = re.compile(r"^(?:gemini|imagen)-[\w.\-]+$")


def _literals(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and _MODEL.match(n.value)]


def test_model_names_live_only_in_llm_engine():
    files = [os.path.join(ROOT, "vts_7L_test.py")]
    for d in ("core", "services", "mic_live_plugin", "realtime_tasks"):
        files += glob.glob(os.path.join(ROOT, d, "*.py"))
    bad = {os.path.relpath(f, ROOT): hits for f in files
           if not f.endswith(os.path.join("core", "llm_engine.py")) and (hits := _literals(f))}
    assert not bad, f"模型名請改用 core.llm_engine 的常數：{bad}"


def test_registry_is_consistent():
    import core.llm_engine as le
    assert le.LIVE_ONE_SHOT_MODEL == le.LIVE_MODEL and le.LIVE_MODEL in le.LIVE_MAIN_MODELS
    for m in [le.FAST_TEXT_MODEL, le.FAST_MULTIMODAL_MODEL, le.AUDIO_MODEL]:
        assert m in le.GEMINI_MODELS
    assert set(le.HIGH_IQ_GEMINI_MODELS) <= set(le.GEMINI_MODELS)
    assert "gemini-2.5-flash" not in str(vars(le))
