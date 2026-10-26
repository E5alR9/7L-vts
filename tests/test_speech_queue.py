# -*- coding: utf-8 -*-
"""說話佇列（2026-10-26）：老爸的話先講、同車道先來先講；能挑掉某些話，不用整條倒出來。"""
import asyncio

from core.speech_queue import SpeechQueue


def test_dad_first_then_system_then_audience_in_arrival_order():
    q = SpeechQueue()
    for item in ({"text": "觀眾1", "target": "audience"}, {"text": "系統", "priority": 90}, {"text": "老爸1", "target": "dad"},
                 "字串也行", {"text": "老爸2", "target": "dad"}, {"text": "觀眾2", "target": "audience"}):
        q.put_nowait(item)
    order = []
    while not q.empty():
        x = q.get_nowait()
        order.append(x if isinstance(x, str) else x["text"])
        q.task_done()
    assert order == ["老爸1", "老爸2", "系統", "字串也行", "觀眾1", "觀眾2"]


def test_drop_where_keeps_the_rest_in_order_and_settles_the_books():
    async def go():
        q = SpeechQueue()
        for i, t in enumerate(("dad", "audience", "dad", "audience")):
            await q.put({"text": str(i), "target": t, "from_live": t == "dad"})
        assert q.drop_where(lambda it: it.get("from_live")) == 2
        assert [x["text"] for x in q._queue] == ["1", "3"] and q.qsize() == 2
        assert (await q.get())["text"] == "1"
        q.task_done()
        assert q.clear() == 1 and q.empty()
        await asyncio.wait_for(q._q.join(), 1.0)          # 挑掉的也銷帳了，沒有永遠未完成的
    asyncio.run(go())


def test_get_waits_for_the_next_item():
    async def go():
        q = SpeechQueue()
        getter = asyncio.ensure_future(q.get())
        await asyncio.sleep(0.01)
        assert not getter.done()
        q.put_nowait({"text": "來了", "target": "dad"})
        assert (await asyncio.wait_for(getter, 1.0))["text"] == "來了"
    asyncio.run(go())
