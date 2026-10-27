# -*- coding: utf-8 -*-
"""TTS 語言分辨驗收：detect（大方向）＋ sovits_text_lang（ SoVITS 語系）＋中文聲線音譯。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.tts_router import detect_language, sovits_text_lang, transliterate_kana_to_zh

CASES = [
    "哇。成都炒飯點這首「ロンリーユニバース」超有品味的耶。老爸，這首很有挑戰性喔！",
    "ﾛﾝﾘｰﾕﾆﾊﾞｰｽ",
    "こんにちは",
    "Never Gonna Give You Up",
    "唱晴天",
]
for text in CASES:
    d = detect_language(text)
    s = sovits_text_lang(text)
    shown = transliterate_kana_to_zh(text) if (d == "zh") else text
    print(f"detect={d:3} sovits={s:5} edge唸作={shown[:45]}")
    print(f"   <= {text[:55]}")
