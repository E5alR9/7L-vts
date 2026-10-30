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


def test_dead_channel_locks_removed_and_model_cooling_reads_shared_table():
    """熔斷鎖 2026-10-27 刪掉（寫入端 10-26 就沒了，鋼琴和金鑰面板讀到的永遠是沒鎖）；改看共用冷卻表。"""
    for name in ("API_LOCKS", "lock_target", "is_locked", "is_model_locked", "record_model_failure"):
        assert not hasattr(le, name)
    le.cool_key("K1", 60, "gemini-x")
    assert not le.model_cooling("gemini-x", ["K1", "K2"])      # 還有一把能用
    le.cool_key("K2", 60)                                       # 整把冷卻也算
    assert le.model_cooling("gemini-x", ["K1", "K2"]) and not le.model_cooling("gemini-y", ["K1"])
    assert not le.model_cooling("gemini-x", [])
    assert 55 < le.cooldown_left("K2", "gemini-y") <= 60 and le.cooldown_left("K3") == 0


def test_key_pools_and_locks_not_left_in_main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    for name in ("load_api_locks", "save_api_locks", "is_locked", "lock_target", "is_model_locked",
                 "lock_entire_model", "record_model_failure"):
        assert f"def {name}(" not in main
    for name in ("API_LOCKS = ", "KEYS_MIC_LIVE = ", "KEYS_PROACTIVE = ", "KEYS_DAD_MAIN = ", "DualHotStandbyLiveManager("):
        assert name not in main
    assert not hasattr(le, "DualHotStandbyLiveManager") and not hasattr(le, "KEYS_MIND_LIVE")


def test_daily_quota_wins_over_the_short_retry_hint(monkeypatch):
    """Google 的每日額度 429 照樣附「retry in 26.9s」：以前先抓秒數只冷卻半分鐘，用完的 key 整天一直撞（2026-10-30）。"""
    monkeypatch.setattr(le, "get_seconds_until_pt_midnight", lambda: 5 * 3600.0)
    err = ("429 RESOURCE_EXHAUSTED. You exceeded your current quota. Quota exceeded for metric: "
           "generate_content_free_tier_requests, limit: 250 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' "
           "Please retry in 26.9s.")
    assert le.parse_cooldown_seconds(err.lower()) == 5 * 3600.0
    assert le.parse_cooldown_seconds("429 per minute limit. please retry in 26.9s.") < 60


def test_vague_live_quota_close_is_not_a_whole_day(monkeypatch):
    """Live 斷線原因最多 123 字常只剩「超過額度」：以前當每天用完、冷卻到半夜，一次每分鐘限流就廢掉一整天。"""
    monkeypatch.setattr(le, "get_seconds_until_pt_midnight", lambda: 5 * 3600.0)
    assert le.parse_cooldown_seconds("1011 none. you exceeded your current quota, please check your plan") == 600.0


def test_retired_model_and_dead_key_are_cooled(monkeypatch):
    """以前 404、key 失效不在名單裡：每次呼叫都白白再撞一次。"""
    monkeypatch.setattr(le, "log_print", lambda *a: None)
    assert le.report_gemini_key_error("K1", Exception("404 NOT_FOUND. models/gemini-x is not found for API version v1beta"), "gemini-x")
    assert le.key_cooling("K1", "gemini-x") and not le.key_cooling("K1", "flash")
    assert le.report_gemini_key_error("K2", Exception("400 INVALID_ARGUMENT. API key not valid. reason: API_KEY_INVALID"), "flash")
    assert le.key_cooling("K2", "pro")   # 整把冷卻
    # 參數錯誤（例如思考等級不支援）不是 key 或模型的問題，不冷卻
    assert not le.report_gemini_key_error("K3", Exception("400 INVALID_ARGUMENT. Thinking level MINIMAL is not supported for this model."), "flash")


def test_live_connections_spread_over_keys(monkeypatch):
    """2026-10-30 老爸：用 key 的地方盡量分開，不夠才同一把多開。連著的 Live 會記成佔用，挑 key 先挑沒人佔的。"""
    import asyncio

    class _Live:
        def __init__(self, api_key):
            self.aio = type("A", (), {"live": type("L", (), {"connect": staticmethod(lambda model, config: _CM())})})()

    class _CM:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(le.genai, "Client", _Live)
    picked = []

    async def go():
        held = []
        for _ in range(3):
            k = le.pick_live_key(["K1", "K2", "K3"], "m")
            picked.append(k)
            cm = le.held_live_connect(k, "m", None)
            await cm.__aenter__()
            held.append(cm)
        assert sorted(picked) == ["K1", "K2", "K3"]                 # 三條各用一把，不重複
        assert le.pick_live_key(["K1", "K2", "K3"], "m") in picked  # 都佔了才同一把多開
        assert le.get_dynamic_live_key_candidates(["K1"])[0] != "K1" or not le.GEMINI_KEYS
        for cm in held:
            await cm.__aexit__(None, None, None)
        assert le.live_load("K1") == le.live_load("K2") == le.live_load("K3") == 0   # 斷線就還回去
    monkeypatch.setattr(le, "GEMINI_KEYS", ["K1", "K4"])
    asyncio.run(go())
