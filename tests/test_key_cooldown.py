"""金鑰冷卻統一（2026-10-22）：以前只有 fetch_ai_response 會在 429 時封印通道，
其他 11 個 Gemini 呼叫點看不到，被限流的 key 會被一直重打。
現在共用 core.llm_engine 的 (key, model) 冷卻表，候選池據此把冷卻中的 key 排到最後。"""
import os
import time

import pytest

import core.llm_engine as le


@pytest.fixture(autouse=True)
def _clean_table(monkeypatch):
    le._KEY_COOLDOWN.clear()
    monkeypatch.setattr(le, "GEMINI_KEYS", [])
    yield
    le._KEY_COOLDOWN.clear()


def test_cool_key_scopes():
    le.cool_key("K1", 60, "flash")
    assert le.key_cooling("K1", "flash")
    assert not le.key_cooling("K1", "pro")      # 只冷卻這個模型
    assert not le.key_cooling("K1")             # 整把沒冷卻
    assert le.key_cooling_any("K1")
    le.cool_key("K2", 60)                       # 整把冷卻
    assert le.key_cooling("K2", "anything")


def test_expired_entries_cleared():
    le._KEY_COOLDOWN[("K1", "m")] = time.time() - 1
    assert not le.key_cooling("K1", "m")
    assert ("K1", "m") not in le._KEY_COOLDOWN


def test_longer_cooldown_wins():
    le.cool_key("K1", 600, "m")
    le.cool_key("K1", 5, "m")
    assert le._KEY_COOLDOWN[("K1", "m")] > time.time() + 500


def test_candidates_put_cooling_keys_last_but_keep_them():
    le.cool_key("K1", 60, "flash")
    got = le.get_dynamic_live_key_candidates(["K1", "K2", "K3"])
    assert got == ["K2", "K3", "K1"]   # 健康的保持原順序在前


def test_candidates_all_cooling_still_returned():
    for k in ("K1", "K2"):
        le.cool_key(k, 60)
    assert le.get_dynamic_live_key_candidates(["K1", "K2"]) == ["K1", "K2"]  # 不餓死


def test_report_429_cools_key_model(monkeypatch):
    logs = []
    monkeypatch.setattr(le, "log_print", logs.append)
    assert le.report_gemini_key_error("KEY_ABCDEF", Exception("429 RESOURCE_EXHAUSTED retry in 20s"), "flash") is True
    assert le.key_cooling("KEY_ABCDEF", "flash")
    assert not le.key_cooling("KEY_ABCDEF", "pro")
    assert logs and "ABCDEF" in logs[0]


def test_report_ignores_non_limit_errors():
    assert le.report_gemini_key_error("K1", Exception("invalid argument: bad image"), "flash") is False
    assert le.report_gemini_key_error("", Exception("429"), "flash") is False
    assert le._KEY_COOLDOWN == {}


def test_daily_quota_cools_until_pt_midnight():
    le.report_gemini_key_error("K1", Exception("Quota exceeded: requests per day"), "flash")
    assert le._KEY_COOLDOWN[("K1", "flash")] - time.time() >= 59  # 至少到 PT 午夜（最少 60 秒）


def test_cooldown_helpers_only_in_llm_engine():
    """2026-10-25 搬家：冷卻剖析／回報只留 core.llm_engine 一份，主程式 import 來用。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    for name in ("get_seconds_until_pt_midnight", "parse_cooldown_seconds", "report_gemini_key_error"):
        assert f"def {name}(" not in main
    assert "_KEY_LIMIT_MARKERS = " not in main
