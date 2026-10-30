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
# 討論輪：初步想完有人有話，就讓大家看彼此的想法再定案（大家都安靜就不開）。
# 2026-10-30 實測同樣三輪各兩次：開跟不開都抓到 5 個裡的 4 個，開了每輪多 8～12 秒（總共 16～21 秒）。
# 沒有更準又慢，預設關；SUBMINDS_DISCUSS=1 打開
import os as _os
DISCUSS_SEC = 12.0 if (_os.getenv("SUBMINDS_DISCUSS", "0") or "0").strip().lower() in ("1", "true", "yes", "on") else 0.0

# 工作群（2026-10-30 老爸：像有一個工作群，大家互相看得到）：主腦講了什麼、叫了什麼工具、哨兵怎麼判斷、
# 交辦結果、每個副意識上一輪的建議都貼進來；每個副意識下一輪開頭只拿「它上次之後的新訊息」（自己貼的不算）。
# 不在它想到一半時推過去：Live 連線收到新內容會打斷正在想的那段
GROUP_KEEP = 40        # 群裡最多留幾則
GROUP_PER_TURN = 12    # 一輪最多帶幾則新訊息給一個副意識
GROUP_LINE_MAX = 200   # 一則最多幾個字


class SubMinds:
    def __init__(self, system_fn: Callable[[str], str], keys: Optional[List[str]] = None,
                 roles=None, connect=None, wait_sec: float = WAIT_SEC, discuss_sec: float = DISCUSS_SEC):
        """system_fn(名字) → 那個副意識的系統提示詞；connect 測試換假連線用；discuss_sec=0 不開討論輪。"""
        keys = [k for k in (keys if keys is not None else GEMINI_KEYS) if k]
        roles = roles or ROLES
        self.wait_sec = wait_sec
        self.discuss_sec = discuss_sec
        self._group: List[Tuple[int, str, str]] = []   # (序號, 誰, 內容)
        self._seq = 0
        self._seen = {}   # 副意識名字 → 上次看到第幾則
        self.minds: List[ResidentAdvisor] = []
        for i, (name, model, level) in enumerate(roles):
            # 每個副意識分到自己那一份 key（第 i、i+n、i+2n… 把），彼此不搶同一把
            own = keys[i::len(roles)] or keys
            self.minds.append(ResidentAdvisor(lambda name=name: system_fn(name), keys=own, model=model,
                                              connect=connect, thinking_level=level, label=f"副意識・{name}"))

    def post(self, source: str, text: str) -> None:
        """貼一則到工作群（誰：主腦、哨兵、交辦結果、副意識・查核…）。"""
        text = " ".join((text or "").split())[:GROUP_LINE_MAX]
        if not text:
            return
        self._seq += 1
        self._group = (self._group + [(self._seq, source, text)])[-GROUP_KEEP:]

    def note(self, text: str) -> None:
        """不用回的背景（交辦結果）：貼進工作群，每個副意識下一輪都看得到。"""
        self.post("交辦結果", text)

    def _digest(self, name: str, round_text: str) -> str:
        """這個副意識上次之後的新訊息：自己貼的不算，主腦這輪的回答已經在題目裡的也不重複。"""
        seen = self._seen.get(name, 0)
        self._seen[name] = self._seq
        lines = [f"- {src}：{txt}" for seq, src, txt in self._group
                 if seq > seen and src != f"副意識・{name}" and not (src == "主腦" and txt.removeprefix("說：")[:30] in round_text)]
        return "\n".join(lines[-GROUP_PER_TURN:])

    async def _think(self, bodies: dict, wait_sec: float, t0: float, stage: str) -> dict:
        """bodies：{副意識: 這次要送的話}，全部同時想；回 {名字: (想完了沒, 建議, 秒數)}。"""
        tasks = {asyncio.ensure_future(m.ask(body)): m for m, body in bodies.items()}
        finished = {}   # 每個副意識自己想完的時間（不是整輪收完的時間）
        for t in tasks:
            t.add_done_callback(lambda t: finished.setdefault(t, time.perf_counter() - t0))
        _, pending = await asyncio.wait(tasks, timeout=wait_sec)
        for t in pending:
            t.cancel()   # 沒想完的這輪不等了；advisor 被取消會收掉連線，下一輪帶續接 handle 接回
        result, verdicts = {}, []
        for t, m in tasks.items():
            name = m.label.split("・")[-1]
            if t in pending:
                result[name] = (False, "", 0.0)
                verdicts.append(f"{name}:沒想完")
                continue
            try:
                said = (t.result() or "").strip()
            except Exception:
                said = ""
            secs = finished.get(t, time.perf_counter() - t0)
            result[name] = (True, said, secs)
            verdicts.append(f"{name}:{'有話' if said else '安靜'} {secs:.1f}s")
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        log_print(f"🧠 [副意識・{stage}] {time.perf_counter() - t0:.1f} 秒：{'、'.join(verdicts)}")
        return result

    async def ask(self, text: str) -> List[Tuple[str, str, float]]:
        """全部同時想這一輪；有人有想法就再開一輪討論定案。回 [(名字, 建議, 秒數)]（照 PRIORITY 排、只留有話說的）。"""
        t0 = time.perf_counter()
        bodies = {}
        for m in self.minds:
            digest = self._digest(m.label.split("・")[-1], text)
            bodies[m] = f"【工作群：妳上次想完之後的新訊息】\n{digest}\n\n【這一輪】\n{text}" if digest else text
        first = await self._think(bodies, self.wait_sec, t0, "初步")
        drafts = [(n, said) for n in PRIORITY for done, said, _ in [first.get(n, (False, "", 0))] if said]
        final = {n: (said, secs) for n, (done, said, secs) in first.items() if said}
        if drafts and self.discuss_sec > 0:
            # 討論輪（2026-10-30 老爸：工作群只看得到上一輪，同一輪誰講重複、誰漏了看不到；讓大家看完彼此的初步想法再定案）
            board = "\n".join(f"- {n}：{s}" for n, s in drafts)
            ask_final = (f"【討論：這一輪大家的初步想法】\n{board}\n\n"
                         "看完再定案，只管妳負責的那件事：要給 7L 的最後建議寫成「建議：…」（可以沿用、修正，"
                         "或補上大家都漏掉、屬於妳管的事）。別人已經講了一樣的事，就照順序（查核、分寸、記憶、情緒、話題）"
                         "留排前面的那個講，後面的輸出 [SILENCE]；妳沒有要講的也輸出 [SILENCE]。")
            second = await self._think({m: ask_final for m in self.minds}, self.discuss_sec, t0, "討論定案")
            for n, (done, said, secs) in second.items():
                if not done:
                    continue   # 討論輪沒想完：照它初步的意見（有的話）
                if said:
                    final[n] = (said, secs)
                else:
                    final.pop(n, None)   # 看完大家的，決定不講（別人講了、或發現不用講）
        out = [(n, said, secs) for n, (said, secs) in final.items()]
        for name, said, _ in out:   # 定案的建議貼進工作群：下一輪別人看得到，可以接著補或指出它講錯
            self.post(f"副意識・{name}", said)
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
