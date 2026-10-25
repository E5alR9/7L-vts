# -*- coding: utf-8 -*-
"""core.lang：中日文判斷只剩一份（2026-10-25 收斂：以前 tts_router、local_xiaoyi_service 各一份一模一樣的）。"""
import os

from conftest import ROOT  # noqa: F401
from core.lang import has_kana, is_japanese_sentence

BS = chr(92)   # 反斜線：避開「\u」在各種工具裡被提前轉成字元
KANA_RANGE_ESCAPED = BS + "u3040-" + BS + "u309F"


def test_is_japanese_sentence_rules():
    assert is_japanese_sentence("ありがとう")                       # 純假名
    assert is_japanese_sentence("今日は天気がいいですね")           # 無中文虛詞、假名多
    assert not is_japanese_sentence("想被罵バカ的話，去找老爸盧啦")  # 有中文虛詞、假名少
    assert not is_japanese_sentence("我最喜歡的動畫是鬼滅之刃")       # 沒假名（全漢字日文無從判斷）
    assert not is_japanese_sentence("")
    assert has_kana("ﾛﾝﾘｰ") and not has_kana("老爸")                 # 半形片假名也算


def test_language_rules_are_not_duplicated():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("services/tts_router.py", "local_xiaoyi_service.py", "core/prompts.py"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        assert "的了嗎吧呢這那是在說" not in src, f       # 中文虛詞清單只在 core.lang
    for f in ("services/tts_router.py", "local_xiaoyi_service.py"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        assert KANA_RANGE_ESCAPED not in src, f          # 假名正則只在 core.lang
        assert chr(0x3040) + "-" not in src, f
