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
    for f in ("services/tts_router.py", "services/local_xiaoyi_service.py", "core/prompts.py"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        assert "的了嗎吧呢這那是在說" not in src, f       # 中文虛詞清單只在 core.lang
    for f in ("services/tts_router.py", "services/local_xiaoyi_service.py", "core/prompts.py"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        assert KANA_RANGE_ESCAPED not in src, f          # 假名正則只在 core.lang
        assert chr(0x3040) + "-" not in src, f


def test_key_modules_load_dotenv_themselves():
    """llm_engine／groq_router 載入時就讀金鑰：以前只有主程式開頭讀 .env，
    別的入口先 import 就是空金鑰池（2026-10-25 測試時本能腦因此崩潰）。新程序、清掉環境變數再 import 驗證。"""
    import os
    import subprocess
    import sys
    from conftest import ROOT
    from core.env_config import ENV_PATH as env_path   # 專案裡的 .env，沒有就家目錄的（2026-10-27 起）
    if not os.path.exists(env_path) or "GEMINI_API_KEY" not in open(env_path, encoding="utf-8", errors="replace").read():
        import pytest
        pytest.skip("這台沒有含 Gemini 金鑰的 .env")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GEMINI_API_KEY", "GROQ_"))}
    out = subprocess.run([sys.executable, "-c", "import core.groq_router as g, core.llm_engine as le;"
                          "print(len(le.GEMINI_KEYS) > 0, len(g.GROQ_KEYS) > 0)"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "True True", out.stderr[-500:]
