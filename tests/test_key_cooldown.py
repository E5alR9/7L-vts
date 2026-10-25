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


def test_channel_locks_live_in_llm_engine(tmp_path, monkeypatch):
    """通道／模型熔斷鎖 2026-10-25 從主程式搬進來：存檔讀檔原地換內容（主程式 import 的是同一個 dict）。"""
    monkeypatch.setattr(le, "API_LOCKS_FILE", str(tmp_path / "locks.json"))
    monkeypatch.setattr(le, "log_print", lambda *a, **k: None)
    monkeypatch.setattr(le, "sys_notify", lambda *a, **k: None)
    same = le.API_LOCKS
    saved = dict(same)
    try:
        same.clear()
        le.lock_entire_model("gemini-3.6-flash", duration=60, reason="測試")
        assert le.is_model_locked("gemini-3.6-flash") and not le.is_model_locked("gemini-3.8-flash")
        le.lock_target("G3_3.8-flash", "429 rate limit", key="K9", model="gemini-3.8-flash")
        assert le.is_locked("G3_3.8-flash") and le.key_cooling("K9", "gemini-3.8-flash")
        same["G1_old"] = time.time() - 5                                   # 過期的讀回來要清掉
        le.save_api_locks()
        same.clear()
        le.load_api_locks()
        assert le.API_LOCKS is same and "MODEL_3.6-flash" in same and "G1_old" not in same
    finally:
        same.clear()
        same.update(saved)


def test_record_model_failure_locks_after_every_key_failed(monkeypatch):
    monkeypatch.setattr(le, "GEMINI_KEYS", ["K1", "K2"])
    monkeypatch.setattr(le, "lock_entire_model", lambda m, duration, reason: locked.append((m, duration)))
    locked = []
    le.MODEL_FAIL_COUNT.pop("gemini-x", None)
    le.record_model_failure("gemini-x", "503 unavailable")
    assert locked == []                                                   # 一把失敗還不熔斷
    le.record_model_failure("gemini-x", "503 unavailable")
    assert locked == [("gemini-x", 180.0)] and le.MODEL_FAIL_COUNT["gemini-x"] == 0


def test_key_pools_and_locks_not_left_in_main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    for name in ("load_api_locks", "save_api_locks", "is_locked", "lock_target", "is_model_locked",
                 "lock_entire_model", "record_model_failure"):
        assert f"def {name}(" not in main
    for name in ("API_LOCKS = ", "KEYS_MIC_LIVE = ", "KEYS_PROACTIVE = ", "KEYS_DAD_MAIN = ", "DualHotStandbyLiveManager("):
        assert name not in main
    assert not hasattr(le, "DualHotStandbyLiveManager") and not hasattr(le, "KEYS_MIND_LIVE")
