# -*- coding: utf-8 -*-
"""副意識群（2026-10-30 老爸：參考人腦——主意識一個、副意識很多。做決定、開口的還是只有 Live 主腦，
軍師那個位置換成一群 3.8 和 3.8 think 一起在背後想）。

每個副意識是一條常駐 Live 連線（services/advisor.ResidentAdvisor），各管一件事（core/promptkit.SUBMIND_FOCUS），
各用不同的 key。主腦每回完一句人話，全部同時想；在 WAIT_SEC 內想完的建議併成一張紙條給主腦，
講不講、怎麼講由她決定。沒想完的這輪就不等了（取消那一輪，下一輪接回原本的對話）。

實測（2026-10-30，同一題、每條不同 key）：3.8 think 低思考同時 5～15 條都正常，中間值 3～8 秒；
一般 3.8 不能調思考，中間值 11～13 秒。同一把 key 開到 10 條會被拒（1011 超過額度），所以每個副意識分開用 key。
"""
import asyncio
import time
from typing import Callable, List, Optional, Tuple

from core.llm_engine import DEEP_THINK_LIVE_MODEL, GEMINI_KEYS, LIVE_MODEL
from core.utils import log_print
from services.advisor import ResidentAdvisor

# (名字, 模型, 思考強度)：事實和記憶要想清楚，用 3.8 think；情緒、話題、分寸靠直覺，用一般 3.8
ROLES: List[Tuple[str, str, Optional[str]]] = [
    ("查核", DEEP_THINK_LIVE_MODEL, "low"),
    ("記憶", DEEP_THINK_LIVE_MODEL, "low"),
    ("情緒", LIVE_MODEL, None),
    ("話題", LIVE_MODEL, None),
    ("分寸", LIVE_MODEL, None),
]
WAIT_SEC = 15.0   # 這輪最多等這麼久；一般 3.8 中間值 11～13 秒，再短就常常只剩 think 的
# 紙條上的順序：講錯事實、認錯人（越界）最要緊，再來記憶、情緒，話題最後。
#（2026-10-30 實測：分寸排最後，觀眾冒充老爸、叫她停琴那條被三條上限切掉）
PRIORITY = ["查核", "分寸", "記憶", "情緒", "話題"]


class SubMinds:
    def __init__(self, system_fn: Callable[[str], str], keys: Optional[List[str]] = None,
                 roles=None, connect=None, wait_sec: float = WAIT_SEC):
        """system_fn(名字) → 那個副意識的系統提示詞；connect 測試換假連線用。"""
        keys = [k for k in (keys if keys is not None else GEMINI_KEYS) if k]
        roles = roles or ROLES
        self.wait_sec = wait_sec
        self.minds: List[ResidentAdvisor] = []
        for i, (name, model, level) in enumerate(roles):
            # 每個副意識分到自己那一份 key（第 i、i+n、i+2n… 把），彼此不搶同一把
            own = keys[i::len(roles)] or keys
            self.minds.append(ResidentAdvisor(lambda name=name: system_fn(name), keys=own, model=model,
                                              connect=connect, thinking_level=level, label=f"副意識・{name}"))

    def note(self, text: str) -> None:
        """不用回的背景（交辦結果）：每個副意識下一輪都一起看。"""
        for m in self.minds:
            m.note(text)

    async def ask(self, text: str) -> List[Tuple[str, str, float]]:
        """全部同時想這一輪；回 [(名字, 建議, 秒數)]（照 PRIORITY 排、只留有話說的）。"""
        t0 = time.perf_counter()
        tasks = {asyncio.ensure_future(m.ask(text)): m for m in self.minds}
        finished = {}   # 每個副意識自己想完的時間（不是整輪收完的時間）
        for t in tasks:
            t.add_done_callback(lambda t: finished.setdefault(t, time.perf_counter() - t0))
        done, pending = await asyncio.wait(tasks, timeout=self.wait_sec)
        for t in pending:
            t.cancel()   # 沒想完的這輪不等了；advisor 被取消會收掉連線，下一輪帶續接 handle 接回
        out, verdicts = [], []
        for t, m in tasks.items():
            name = m.label.split("・")[-1]
            if t in pending:
                verdicts.append(f"{name}:沒想完")
                continue
            try:
                said = (t.result() or "").strip()
            except Exception:
                said = ""
            secs = finished.get(t, time.perf_counter() - t0)
            verdicts.append(f"{name}:{'有話' if said else '安靜'} {secs:.1f}s")
            if said:
                out.append((name, said, secs))
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        log_print(f"🧠 [副意識] 這輪 {time.perf_counter() - t0:.1f} 秒：{'、'.join(verdicts)}")
        return sorted(out, key=lambda r: PRIORITY.index(r[0]) if r[0] in PRIORITY else 99)


def merge_suggestions(suggestions: List[Tuple[str, str, float]], limit: int = 3) -> str:
    """幾個副意識的建議併成一段給主腦看；同一件事講兩次的只留前面那個。"""
    lines, seen = [], []
    for name, said, _ in suggestions:
        body = said.removeprefix("建議：").removeprefix("建議:").strip()
        if any(body[:12] and body[:12] in s for s in seen):
            continue
        seen.append(body)
        lines.append(f"【{name}】{body}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)
