# -*- coding: utf-8 -*-
"""中日文判斷（TTS 路由、本機曉伊、文字清洗共用）。

以前「這句是不是日文」的規則在 tts_router 和 local_xiaoyi_service 各有一份一模一樣的，
假名的正則散在四個檔案、有的漏了半形片假名（YT 歌名常見）。收成這一份，改規則只改這裡。
"""
import re

# 平假名、片假名、半形片假名
KANA_RE = re.compile(r"[぀-ゟ゠-ヿ｡-ﾟ]")
HAN_RE = re.compile(r"[一-鿿]")
# 中文才會出現的語氣詞／虛詞：句子裡有這些，就算夾了假名也大概是中文句
ZH_MARKER_RE = re.compile(r"[的了嗎吧呢這那是在說妳你我他們著啦喔呀嘛欸咦啥誰怎麼盧搞弄為什麼]")


def has_kana(text: str) -> bool:
    return bool(KANA_RE.search(text or ""))


def is_japanese_sentence(text: str) -> bool:
    """整句以日文為主嗎（中文語境優先）：
    - 有假名、沒漢字 → 日文
    - 沒有中文虛詞、假名佔（假名＋漢字）35% 以上 → 日文
    - 有中文虛詞，但假名佔 65% 以上 → 日文（例：「想被罵バカ的話」仍是中文）
    全漢字的日文（沒假名）無從判斷，當中文。"""
    t = text or ""
    num_kana = len(KANA_RE.findall(t))
    if num_kana == 0:
        return False
    num_hanzi = len(HAN_RE.findall(t))
    if num_hanzi == 0:
        return True
    ratio = num_kana / (num_kana + num_hanzi)
    return ratio >= (0.65 if ZH_MARKER_RE.search(t) else 0.35)
