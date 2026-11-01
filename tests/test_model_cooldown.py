# -*- coding: utf-8 -*-
"""整個模型卡住就先跳過（2026-11-01：gemini-3.8-flash 的 REST 連「說嗨」都 40 秒沒回，深度思考每次先白等 13 秒）。"""
import time

import core.llm_engine as le
from conftest import MAIN_SRC as MAIN


def test_timed_out_model_is_skipped_then_comes_back(monkeypatch):
    monkeypatch.setattr(le, "_MODEL_DOWN", {})
    ladder = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
    assert le.usable_models(ladder) == ladder
    le.report_model_timeout("gemini-3.8-flash")
    assert le.usable_models(ladder) == ladder[1:]
    assert le.model_cooling("gemini-3.8-flash", ["k1"]) and not le.model_cooling("gemini-3.6-flash", ["k1"])   # 鋼琴挑模型也跳過
    le._MODEL_DOWN["gemini-3.8-flash"] = time.time() - 1                                                     # 時間到就回來
    assert le.usable_models(ladder) == ladder


def test_all_down_keeps_the_order():
    le._MODEL_DOWN.clear()
    for m in ("a", "b"):
        le.report_model_timeout(m)
    assert le.usable_models(["a", "b"]) == ["a", "b"]                                                         # 全卡住：照原順序，不餓死
    le._MODEL_DOWN.clear()


def test_subagent_passes_report_timeouts_and_skip_down_models():
    assert MAIN.count("report_model_timeout(gmodel)") == 2                                                  # 工具判定、深度思考
    assert "models = usable_models(models)" in MAIN
