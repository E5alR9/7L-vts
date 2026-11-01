# -*- coding: utf-8 -*-
"""知識庫的事實會更新，不只會累加（2026-11-01 老爸：其他好用有效率的 AI 架構都試看看；參考 Mem0 的 ADD／UPDATE／NOOP）。

以前 learned_facts 只會一直 append：先記「老爸最喜歡喝無糖綠茶」，後來說「其實最喜歡紅茶」，兩條都在提示詞裡互相矛盾；
同一件事換個說法（「我最喜歡喝無糖綠茶」「老爸最喜歡喝無糖綠茶」）也存兩條。
現在新事實進來先用字的重疊找出可能相關的舊事實（不用載模型），有相關的才問 Groq（約 0.3 秒）要
新增（add）、更新某一條（update，換成合併後的句子）、還是重複不用存（skip）。Groq 掛了照舊新增。
"""
import json
import re
from typing import List, Optional, Tuple

CANDIDATE_MIN_OVERLAP = 0.15   # 兩句的雙字詞重疊比例（以較短那句為準）到這個值才算可能相關
MAX_CANDIDATES = 5
_STOP = {"老爸", "爸爸", "他的", "我的", "我們", "一個", "就是", "可以", "因為", "所以"}   # 「喜歡」這類是主題，不能濾

SYSTEM = ("妳在整理 7L 的知識庫（關於老爸和她自己的事實）。給妳一條新事實和幾條可能相關的舊事實，判斷怎麼存"
          "（新事實多半是老爸親口叫她記的，句子裡的「我」就是老爸）：\n"
          "- 新事實跟舊的講同一件事、意思一樣 → skip\n"
          "- 新事實更新、修正或跟某條舊的矛盾（例如喜好改了、數字改了）→ update，index 填那條的編號，"
          "merged 填合併後的一句（以新的為準，舊的還成立的部分可以保留）\n"
          "- 講的是不同的事 → add\n"
          "只回一行 JSON：{\"op\": \"add|update|skip\", \"index\": 編號或 null, \"merged\": \"句子或空字串\"}")


def _bigrams(text: str) -> set:
    t = re.sub(r"[\s，,。.！!？?、：:；;「」『』（）()~～…]+", "", text or "").lower()
    return {t[i:i + 2] for i in range(len(t) - 1)} - _STOP


def candidates(new: str, facts: List[str]) -> List[int]:
    """可能跟新事實相關的舊事實編號（重疊多的在前，最多 MAX_CANDIDATES 條）。"""
    nb = _bigrams(new)
    if not nb:
        return []
    scored = []
    for i, f in enumerate(facts):
        fb = _bigrams(f)
        if not fb:
            continue
        overlap = len(nb & fb) / min(len(nb), len(fb))
        if overlap >= CANDIDATE_MIN_OVERLAP:
            scored.append((overlap, i))
    return [i for _, i in sorted(scored, reverse=True)[:MAX_CANDIDATES]]


def parse_decision(text: str, cand: List[int], facts: List[str]) -> Tuple[str, Optional[int], str]:
    """Groq 的回答 → (op, 事實清單裡的位置, 合併句)；看不懂就當 add。"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return "add", None, ""
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return "add", None, ""
    op = str(d.get("op") or "").lower()
    if op == "skip":
        return "skip", None, ""
    if op == "update":
        try:
            k = int(d.get("index")) - 1
        except (TypeError, ValueError):
            return "add", None, ""
        merged = str(d.get("merged") or "").strip()
        if 0 <= k < len(cand) and merged and len(merged) <= 200:
            return "update", cand[k], merged
    return "add", None, ""


async def reconcile(new: str, facts: List[str]) -> Tuple[str, Optional[int], str]:
    """新事實要怎麼存：('add', None, '')／('update', 位置, 合併句)／('skip', None, '')。"""
    cand = candidates(new, facts)
    if not cand:
        return "add", None, ""
    lines = "\n".join(f"{k + 1}. {facts[i]}" for k, i in enumerate(cand))
    try:
        from core.groq_router import groq_chat
        r = await groq_chat([{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": f"新事實：{new}\n舊事實：\n{lines}"}],
                            temperature=0.0, max_tokens=200, timeout=6.0)
        text = getattr(r, "text", "") if r else ""
    except Exception:
        return "add", None, ""
    return parse_decision(text, cand, facts)
