# -*- coding: utf-8 -*-
"""services/tts_router.py 純函式測試（不打語音合成）"""
from conftest import ROOT  # noqa: F401
from services import tts_router as t


# ── 語言偵測（只回 zh / ja）─────────────────────────────────────────────────
def test_detect_language_chinese():
    assert t.detect_language("你好嗎，今天天氣真好。") == "zh"
    assert t.detect_language("老爸你在幹嘛") == "zh"
    # 無任何特徵時預設中文（直播語境以中文為主）
    assert t.detect_language("") == "zh"


def test_detect_language_japanese():
    assert t.detect_language("こんにちは") == "ja"
    assert t.detect_language("カタカナです") == "ja"
    # 純漢字、無中文語氣詞 → 依假名比例規則仍可能 zh，只要求回合法值
    assert t.detect_language("東京タワー") in ("zh", "ja")


def test_detect_language_mixed_prefers_chinese_with_markers():
    # 同時有漢字與假名，但帶中文語氣詞 → 判定 zh
    assert t.detect_language("你好 こんにちは 嗎") == "zh"


# ── 副檔名對應（播放端靠它命名暫存檔）──────────────────────────────────────
def test_file_extension_mapping():
    assert t.file_extension("edge") == ".mp3"
    assert t.file_extension("elevenlabs") == ".mp3"
    for eng in ("kokoro", "cosyvoice", "xiaoyi", "unknown_engine"):
        assert t.file_extension(eng) == ".wav"


# ── 文字清洗（餵給 TTS 前的標籤/括號/多音字處理入口）────────────────────────
def test_clean_text_strips_action_tags_and_brackets():
    out = t._clean_text("[PITCH:+2Hz]你好(笑)[EXPRESSION: 開心]，(這樣)", "zh")
    assert "[PITCH" not in out and "[EXPRESSION" not in out
    assert "(笑)" not in out and "(這樣)" not in out
    # 標籤/括號移除後剩「你好，」，尾逗號會被 strip 掉
    assert out == "你好"


def test_clean_text_renames_7l_for_tts():
    out = t._clean_text("我是7L，這是7l的實驗室", "zh")
    assert "7L" not in out and "7l" not in out
    assert out.count("小七") == 2


def test_clean_text_collapses_repeated_punctuation():
    # 只合併重複的逗號/感嘆/問號/句號（TTS 念重複標點會不自然）
    # 注意：合併結果統一為全形標點，且句尾標點保留（語氣依據）
    assert t._clean_text("真的嗎？？？", "zh") == "真的嗎？"
    assert t._clean_text("真的嗎!!!", "zh") == "真的嗎！"
    assert t._clean_text("嗯，，，然後呢", "zh") == "嗯，然後呢"
    assert t._clean_text("好。。好吧", "zh") == "好。好吧"
    # 開頭逗號仍被 strip
    assert t._clean_text("，你好", "zh") == "你好"


def test_clean_text_japanese_skips_loanword_rewrite():
    # 日文路徑不套中文外來語改寫表（回傳仍應含原文假名）
    out = t._clean_text("こんにちは[EXPRESSION: 開心]", "ja")
    assert "こんにちは" in out and "[EXPRESSION" not in out


# ── 引擎註冊表與降級鏈 ─────────────────────────────────────────────────────
def test_engine_registry_contains_all_known_engines():
    for eng in ("kokoro", "edge", "xiaoyi", "cosyvoice", "elevenlabs"):
        assert eng in t._ENGINES, f"缺少引擎註冊: {eng}"
        assert callable(t._ENGINES[eng])


def test_engine_chain_has_no_duplicates():
    assert len(t.ENGINE_CHAIN) == len(set(t.ENGINE_CHAIN))
    assert all(e in t._ENGINES for e in t.ENGINE_CHAIN), "鏈內有未註冊引擎"


def test_get_active_engine_initially_none_or_registered():
    ae = t.get_active_engine()
    assert ae is None or ae in t._ENGINES


def test_kokoro_voice_defaults_present():
    assert t.ZH_VOICE, "中文聲線不可為空"
    assert t.EN_VOICE, "英文聲線不可為空"
