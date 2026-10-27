"""熱模組冒煙測試（2026-10-10 全庫審計第 9 項：六個零覆蓋模組）。

這六個模組是直播命脈，當時沒有任何測試碰過（現在各自都有專門測試了），
這裡留著最低限度的保險：

1. import 得動（抓語法錯誤、缺依賴、模組層炸彈）
2. 幾個「純函數」的輸入輸出（抓被順手改壞的邏輯）

紀律：絕不打網路、絕不寫資料檔——所以這份測試在 V7 直播中執行也安全。
"""
import importlib
import os

import pytest

HOT_MODULES = [
    "core.memory",            # 記憶讀寫（黑板/統一記憶/觀眾檔案）
    "core.prompts",           # prompt 組裝與文字清洗
    "core.llm_engine",        # 模型名稱、金鑰池、冷卻表
    "services.piano_engine",  # 鋼琴
    "services.vts_client",    # VTS API（表情/走位）
    "services.tiktok_listener",  # TikTok 彈幕
]


@pytest.mark.parametrize("name", HOT_MODULES)
def test_hot_module_imports(name):
    m = importlib.import_module(name)
    assert m is not None, f"{name} import 失敗"


def test_memory_mode_path_is_pure_and_mode_suffixed():
    from core.memory import mode_path
    p = mode_path("unified_memory.json")
    base = os.path.basename(p)
    assert base.startswith("unified_memory_"), base
    assert base.endswith(".json")
    assert os.path.isabs(p)
    # 無副檔名的呼叫也不會掉字
    assert "_" in os.path.basename(mode_path("abc"))


def test_prompts_text_clean_engine_is_pure():
    from core.prompts import TextCleanEngine
    assert TextCleanEngine.strip_emojis("") == ""
    assert TextCleanEngine.strip_emojis("好耶😀🎉") == "好耶"
    # 整段系統提示清空、句中系統提示只拔標籤區塊
    assert TextCleanEngine.remove_system_hints("[系統提示：整段都是]") == ""
    assert TextCleanEngine.remove_system_hints("[系統提示：靜音]你好") == "你好"
    assert TextCleanEngine.remove_system_hints("") == ""


def test_llm_engine_key_candidates_dedupe_and_keep_order():
    from core.llm_engine import get_dynamic_live_key_candidates as f
    out = f(["k1", "k1", "", None, "k2"])
    assert out[:2] == ["k1", "k2"], out
    assert len(out) == len(set(out)), "候選池不可有重複金鑰"
    # 偏好池永遠排在全域池前面
    assert out.index("k1") < out.index("k2")


def test_key_tracker_counts_and_releases():
    """同 key 互斥追蹤：計數、釋放、異常也釋放、排序空閒優先。"""
    import asyncio
    from core import llm_engine as le

    async def main():
        assert le.key_load("K") == 0
        async with le.track_key("K"):
            assert le.key_load("K") == 1
            async with le.track_key("K"):
                assert le.key_load("K") == 2
            assert le.key_load("K") == 1
        assert le.key_load("K") == 0
        try:
            async with le.track_key("K"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert le.key_load("K") == 0, "異常也必須釋放，否則 key 被BehindTheScenes永久封印"

    asyncio.run(main())
    # 排序：空閒優先；全忙不阻擋（照排）
    ordered = le.sort_keys_by_load(["x", "y", "z"])
    assert set(ordered) == {"x", "y", "z"}


def test_piano_midi_to_freq_is_a440():
    from services.piano_engine import midi_to_freq
    assert midi_to_freq(69) == pytest.approx(440.0)
    assert midi_to_freq(60) == pytest.approx(261.6255653005986)


def test_vts_parse_relative_spatial_offsets_is_pure():
    from services.vts_client import parse_relative_spatial_offsets as f
    # 純命名站位與空字串：不給偏移（呼叫方走預設站位）
    assert f("") == (None, None, None)
    assert f("正中間") == (None, None, None)
    assert f("原位") == (None, None, None)
    # 顯式 dx 與口語走位
    assert f("dx:2") == (pytest.approx(2.0), 0.0, 0.0)
    dx, dy, _ = f("往右走")
    assert dx == pytest.approx(0.22) and dy == 0.0
    # 無任何可解析指令
    assert f("法藍朵") == (None, None, None)


def test_tiktok_target_ids_are_at_prefixed_list():
    from services.tiktok_listener import get_target_tiktok_ids
    ids = get_target_tiktok_ids()
    assert isinstance(ids, list) and ids
    assert all(i.startswith("@") for i in ids), ids
    assert len(ids) == len(set(ids)), "監聽清單不可有重複帳號"
