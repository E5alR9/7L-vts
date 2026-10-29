"""VTS 走位：時間超過 2 秒 VTS 整個拒絕（APIError 302），以前沒看回應，自主漫遊一步都沒走過還回成功。"""
import asyncio

import services.vts_client as vc


class FakeVTS:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    async def request(self, req, timeout=2.0):
        self.sent.append(req)
        if req["messageType"] == "CurrentModelRequest":
            return {"messageType": "CurrentModelResponse",
                    "data": {"modelPosition": {"positionX": 0.1, "positionY": -1.27, "size": -54.8}}}
        return self.reply


def _moves(fake):
    return [r["data"] for r in fake.sent if r["messageType"] == "MoveModelRequest"]


def test_move_time_is_kept_within_what_vts_accepts(monkeypatch):
    fake = FakeVTS({"messageType": "MoveModelResponse", "data": {}})
    monkeypatch.setattr(vc, "GLOBAL_VTS", fake)
    for asked in (3.0, 2.0, 0.5, -1.0):
        assert asyncio.run(vc.move_vts_spatial(target_pos="random", duration=asked)) is True
    assert [m["timeInSeconds"] for m in _moves(fake)] == [2.0, 2.0, 0.5, 0.0]


def test_vts_refusing_the_move_is_a_failure(monkeypatch):
    fake = FakeVTS({"messageType": "APIError", "data": {"errorID": 302, "message": "values are too high or low"}})
    monkeypatch.setattr(vc, "GLOBAL_VTS", fake)
    monkeypatch.setattr(vc, "log_print", lambda *a, **k: None)
    monkeypatch.setattr(vc, "CURRENT_VTS_MODEL_X", None)
    assert asyncio.run(vc.move_vts_spatial(target_pos="左邊", duration=1.0)) is False
    assert vc.CURRENT_VTS_MODEL_X == 0.1   # 記的位置還是 VTS 說的那個，不是沒走成的目的地
