# -*- coding: utf-8 -*-
"""語意指令分流：老爸打的字像不像要她「做事」（設提醒、記東西、查資料），像的話在紙條上提醒她交辦
（2026-11-01 老爸：其他好用有效率的 AI 架構都試看看；參考 semantic router）。

以前只有固定說法（正則）和主腦自己判斷：「等等提醒我喝水」這種換個說法的，她常只嘴上答應、沒交辦。
這裡不直接執行，只在紙條上加一句「這句像是要設提醒，要做就交辦」——做不做、怎麼做還是她決定。
點歌、彈琴、停唱有專門的判斷（Groq 點歌判斷、CPU 硬指令），「幫我記住…」程式直接存，都不在這裡。

試過純本機向量比對（bge-small-zh，3.5 毫秒）：沒看過的句子只對 16/24，分不出「叫妳做」跟「我在講一件事」
（「今天匯率好像漲了」被當成要查）。改成字詞先篩、可能是才問 Groq：兩組句子 27/28、23/24，每次約 0.2 秒，
沒有這些字的句子（大部分閒聊）完全不問。
"""
import re
from typing import Optional

HINT = re.compile(r"取消|查|搜|找一下|看一下|看看|上網|記住|記一下|記下|記得|記起來|提醒|叫我|叫一下我|分鐘|小時|鬧鐘|倒數|計時|"
                  r"晚點|待會|等等|等一下")
SYSTEM = ("判斷老爸對虛擬女兒 7L 說的這句話，是不是要她現在去做下面其中一件事：\n"
          "timer＝設計時器或過一段時間提醒／叫他；cancel＝取消已經設好的計時器或提醒；remember＝把一件關於他的事記下來；"
          "search＝上網查資料或看即時資訊。\n"
          "只是在講自己的事、講過去發生的、問她知不知道、閒聊，都是 none。只回一個字：timer、cancel、remember、search 或 none。")
LABELS = {"timer": "設計時器或到時候提醒", "cancel": "取消已經設好的計時器", "remember": "把一件事記進知識庫", "search": "上網查資料"}
TIMEOUT_SEC = 1.5   # 紙條要等這個判斷：最多等這麼久，Groq 慢就不加提示


async def classify(text: str) -> Optional[str]:
    """像要做事就回類別（timer／cancel／remember／search），不像或判斷不了回 None。"""
    t = (text or "").strip()
    if len(t) < 3 or len(t) > 120 or not HINT.search(t):
        return None
    try:
        from core.groq_router import groq_chat
        r = await groq_chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": t}],
                            temperature=0.0, max_tokens=8, timeout=TIMEOUT_SEC, total_timeout=TIMEOUT_SEC)
    except Exception:
        return None
    m = re.search(r"cancel|timer|remember|search", ((getattr(r, "text", "") or "") if r else "").lower())
    return m.group(0) if m else None


def hint_text(intent: str, owner: str = "老爸") -> str:
    extra = "；沒講多久就先問幾分鐘" if intent == "timer" else ""
    return f"（程式判斷：{owner}這句像是要妳{LABELS[intent]}，要做就交辦 invoke_subagent，不要只嘴上答應{extra}。）"


# 判定是要查資料時順便叫這個（主程式開機時接上 services.web_search.prefetch）：紙條還在送主腦，搜尋先開跑。
# core 不往上 import services，所以用登記的（跟 memory.register_rag 一樣）
ON_SEARCH = None


async def slip_hint(text: str, owner: str = "老爸", handled_by_cpu: bool = False) -> str:
    """給老爸打字紙條加的提示；不用加回空字串。handled_by_cpu：程式已經直接處理（記住、點歌），不用再提醒。"""
    if handled_by_cpu:
        return ""
    intent = await classify(text)
    if intent == "search" and ON_SEARCH is not None:
        try:
            ON_SEARCH(text)
        except Exception:
            pass
    return hint_text(intent, owner) if intent else ""
