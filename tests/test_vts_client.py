"""VTS 連線層（2026-10-17）：request 不再偷偷重連、requestID 唯一、斷線快速失敗；
表情重複觸發維持開啟、開失敗不記帳。全部用假 WebSocket，不碰真 VTS。"""
import asyncio
import json

import pytest

import services.vts_client as v


class FakeWS:
    """最小假連線：send 記下 payload，可選擇自動回應；async for 迭代到 closed 事件為止。"""

    def __init__(self, client, reply=True, reply_type="ExpressionActivationResponse"):
        self.client = client
        self.reply = reply
        self.reply_type = reply_type
        self.sent = []
        self.close_code = None
        self._closed = asyncio.Event()

    async def send(self, msg):
        data = json.loads(msg)
        self.sent.append(data)
        if self.reply:
            rid = data["requestID"]
            asyncio.get_running_loop().call_soon(
                lambda: self.client.pending_requests.get(rid) and not self.client.pending_requests[rid].done()
                and self.client.pending_requests[rid].set_result(
                    {"requestID": rid, "messageType": self.reply_type, "data": {}}))

    def drop(self):
        self.close_code = 1006
        self._closed.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._closed.wait()
        raise StopAsyncIteration


def test_request_fails_fast_when_disconnected():
    c = v.RobustVTSClient(port=8001)

    async def main():
        with pytest.raises(ConnectionError):
            await asyncio.wait_for(c.request({"messageType": "APIStateRequest"}), timeout=0.5)

    asyncio.run(main())


def test_request_ids_unique_and_caller_dict_untouched():
    c = v.RobustVTSClient(port=8001)

    async def main():
        c.ws = FakeWS(c)
        msg = {"requestID": "ActivateExpression", "messageType": "ExpressionActivationRequest"}
        r1, r2 = await asyncio.gather(c.request(msg), c.request(msg))
        return msg, r1, r2

    msg, r1, r2 = asyncio.run(main())
    assert msg["requestID"] == "ActivateExpression"  # 呼叫端的 dict（常是模組常數）不能被改
    ids = [s["requestID"] for s in c.ws.sent]
    assert len(set(ids)) == 2 and all(i.startswith("ActivateExpression_") for i in ids)
    assert r1["requestID"] != r2["requestID"]
    assert c.pending_requests == {}


def test_timeout_and_outer_cancel_clean_pending():
    c = v.RobustVTSClient(port=8001)

    async def main():
        c.ws = FakeWS(c, reply=False)
        r = await c.request({"messageType": "X"}, timeout=0.05)
        assert r.get("errorID") == 408
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(c.request({"messageType": "X"}), timeout=0.05)

    asyncio.run(main())
    assert c.pending_requests == {}


def test_reader_fails_pending_when_connection_drops():
    c = v.RobustVTSClient(port=8001)

    async def main():
        ws = FakeWS(c, reply=False)
        c.ws = ws
        reader = asyncio.create_task(c._socket_reader(ws))
        req = asyncio.create_task(c.request({"messageType": "X"}, timeout=5.0))
        await asyncio.sleep(0.05)
        ws.drop()
        with pytest.raises(ConnectionError):
            await asyncio.wait_for(req, timeout=1.0)  # 不必乾等 5 秒
        await reader

    asyncio.run(main())


def test_reader_of_replaced_connection_leaves_new_requests_alone():
    c = v.RobustVTSClient(port=8001)

    async def main():
        old = FakeWS(c, reply=False)
        new = FakeWS(c, reply=False)
        c.ws = new  # 已換成新連線
        req = asyncio.create_task(c.request({"messageType": "X"}, timeout=0.3))
        await asyncio.sleep(0.02)
        old.drop()
        await c._socket_reader(old)
        r = await req
        assert r.get("errorID") == 408  # 照常逾時，沒被舊 reader 誤殺

    asyncio.run(main())


class FakeExprVTS:
    def __init__(self, fail_files=()):
        self.fail_files = set(fail_files)
        self.calls = []

    async def request(self, payload):
        d = payload.get("data", {}) or {}
        self.calls.append((d.get("expressionFile"), d.get("active")))
        if d.get("expressionFile") in self.fail_files:
            return {"messageType": "APIError", "data": {"errorID": 452, "message": "expression not found"}}
        return {"messageType": "ExpressionActivationResponse", "data": {}}


def _clean():
    v.CURRENT_ACTIVE_EXPS = set()
    v.LAST_CONSCIOUS_ACTION_TIME = 0.0


def test_repeat_same_expression_stays_on():
    """連續兩句都開心：第二句不能把愛心關掉（舊 toggle 事故）。"""
    _clean()
    fake = FakeExprVTS()
    asyncio.run(v.set_vts_expression(fake, "開心"))
    asyncio.run(v.set_vts_expression(fake, "開心"))
    assert fake.calls == [("爱心.exp3.json", True), ("爱心.exp3.json", True)]
    assert v.CURRENT_ACTIVE_EXPS == {"爱心.exp3.json"}


def test_failed_activation_not_recorded():
    """VTS 回錯誤（request 不丟例外）時不能記成已開。"""
    _clean()
    fake = FakeExprVTS(fail_files=("爱心.exp3.json",))
    asyncio.run(v.set_vts_expression(fake, "開心"))
    assert v.CURRENT_ACTIVE_EXPS == set()


def test_vts_ok_helper():
    assert v._vts_ok({"messageType": "ExpressionActivationResponse", "data": {}})
    assert v._vts_ok({"data": {}})
    assert not v._vts_ok({"errorID": 408, "message": "timed out"})
    assert not v._vts_ok({"messageType": "APIError", "data": {"errorID": 8}})
    assert not v._vts_ok(None)
