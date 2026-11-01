# -*- coding: utf-8 -*-
"""承諾追蹤：她答應要做、卻沒真的去做（2026-11-01 老爸：其他好用有效率的 AI 架構都試看看）。

實測看到的：「時間到了我一定會盯著你喝水」（沒設計時器）、「我再幫你設一次」（沒再交辦）。
做法（便宜的先、貴的後）：
1. 她說完一句，先用字比對看像不像在答應做事（PROMISE_HINT），不像就結束——大部分的話到這裡就停，不花 API；
2. 等一下（交辦、叫工具要一點時間），這段時間有做任何動作就算有做；
3. 都沒有才問 Groq（約 0.3 秒）這句是不是答應了「要系統工具才做得到的事」，缺什麼資訊（幾分鐘）；
4. 是的話遞紙條提醒她：要做就交辦、缺資訊就問、做不到就老實說。同一句只提醒一次。
"""
import json
import re
from typing import Optional

# 像在答應「之後要做」的說法；陪伴、安慰的話（我陪你、加油）不在這裡
PROMISE_HINT = re.compile(r"我會|我再|我來|我去|我幫你|幫你(設|記|查|放|唱|彈|開|關|找)|等一下|待會|等等|時間到|到時候|"
                          r"提醒你|盯著你|叫你|記得幫|馬上幫你|現在就|這就幫|一定會|我唱|唱首|唱給你|我彈|彈首|彈給你")
# 問句是在問細節（「要幾分鐘後提醒你呢？」），那正是該做的，不算答應了沒做（2026-11-01 實機誤判）
QUESTION = re.compile(r"[?？]|(嗎|呢|吧)[\s～~!！。]*$")
WAIT_SEC = 8.0   # 說完等這麼久再檢查（交辦子智能體、CPU 派發都在這段時間內）

SYSTEM = ("妳在檢查虛擬女兒 7L 剛說的一句話：她有沒有答應要做「需要系統工具才做得到」的事——"
          "例如設計時器或到時候提醒、記住某件事、唱歌、彈琴、上網查資料、換表情、走位、看畫面。"
          "只是口頭陪伴、關心、聊天、答應會注意（「我陪你」「我會乖乖的」）不算；已經在講做完的結果、在問對方細節的問句也不算。"
          "只回一行 JSON：{\"promise\": true 或 false, \"action\": \"要做的事（簡短）\", "
          "\"missing\": \"要做這件事還缺的資訊，例如幾分鐘後；不缺就空字串\"}")


def worth_checking(text: str) -> bool:
    t = re.sub(r"\[[^\]]*\]", "", text or "").strip()
    return bool(PROMISE_HINT.search(t)) and not QUESTION.search(t)


def parse(text: str) -> Optional[dict]:
    """Groq 的回答 → {"action", "missing"}；不是承諾或看不懂回 None。"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if d.get("promise") is not True:
        return None
    action = str(d.get("action") or "").strip()[:40]
    if not action:
        return None
    return {"action": action, "missing": str(d.get("missing") or "").strip()[:40]}


def nudge_text(said: str, found: dict, owner: str = "老爸") -> str:
    ask = f"要做的話還缺「{found['missing']}」，先問{owner}；" if found.get("missing") else ""
    return (f"[系統提示：妳剛才說「{said[:60]}」，答應了要{found['action']}，但系統沒看到妳真的去做（沒有交辦、也沒叫工具）。"
            f"{ask}要做就現在 invoke_subagent 交辦；做不到就老實跟{owner}說。不用為這張紙條道歉。]")


async def find_promise(said: str) -> Optional[dict]:
    """問 Groq 這句是不是答應了要做的事；Groq 掛了回 None（寧可不提醒）。"""
    try:
        from core.groq_router import groq_chat
        r = await groq_chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": said}],
                            temperature=0.0, max_tokens=120, timeout=5.0)
    except Exception:
        return None
    return parse(getattr(r, "text", "") if r else "")
