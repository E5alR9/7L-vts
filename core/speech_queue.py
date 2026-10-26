# -*- coding: utf-8 -*-
"""她要講的話排隊（2026-10-26）。

用法跟 asyncio.Queue 一樣（put／put_nowait／get／get_nowait／empty／qsize／task_done），另外：
- 有車道：給老爸的話（target="dad"）先講，其他照順序，給觀眾的最後；同一車道先來先講。
- drop_where(條件)：挑掉排隊中符合條件的話。以前要挑就把整條倒出來再把要留的塞回去；
  Live 主腦被打斷時更是整條清掉，連罐頭應答、鋼琴台詞、系統提醒都一起丟。
"""
import asyncio
import heapq
import itertools


def lane(item) -> int:
    """0＝給老爸、1＝其他（系統、沒標對象）、2＝給觀眾。"""
    target = item.get("target") if isinstance(item, dict) else None
    if target == "dad":
        return 0
    if target == "audience":
        return 2
    return 1


class SpeechQueue:
    def __init__(self):
        self._q = asyncio.PriorityQueue()
        self._seq = itertools.count()

    def put_nowait(self, item) -> None:
        self._q.put_nowait((lane(item), next(self._seq), item))

    async def put(self, item) -> None:
        self.put_nowait(item)

    async def get(self):
        return (await self._q.get())[2]

    def get_nowait(self):
        return self._q.get_nowait()[2]

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()

    def task_done(self) -> None:
        self._q.task_done()

    def drop_where(self, pred) -> int:
        """挑掉排隊中 pred(項目) 為真的話，回挑掉幾則。"""
        heap = self._q._queue
        keep = [e for e in heap if not pred(e[2])]
        dropped = len(heap) - len(keep)
        heap[:] = keep
        heapq.heapify(heap)
        for _ in range(dropped):
            self._q.task_done()   # 放進來時記了一筆未完成，挑掉的不會被 get，要自己銷帳
        return dropped

    def clear(self) -> int:
        return self.drop_where(lambda item: True)

    @property
    def _queue(self) -> list:
        """排隊中的話，照會講的順序（給測試、除錯看）。"""
        return [e[2] for e in sorted(self._q._queue, key=lambda e: e[:2])]
