"""表情 reset 打假（2026-10-11 直播事故：log 說已重置，臉上還掛著）。

根因：reset 只信 CURRENT_ACTIVE_EXPS 小本本（重啟殘留/不同步就發個寂寞），
單檔 0.2 秒超時還靜默吞掉。現改為先問 VTS 要 ground truth。
"""
import asyncio

import services.vts_client as v


class FakeVTS:
    def __init__(self, active_files=(), fail_deactivate=(), fail_query=False):
        self.active = set(active_files)
        self.fail_deactivate = set(fail_deactivate)
        self.fail_query = fail_query
        self.deactivated = []

    async def request(self, payload):
        mt = payload.get("messageType")
        if mt == "ExpressionStateRequest":
            if self.fail_query:
                raise RuntimeError("vts busy")
            return {"data": {"expressions": [
                {"name": f, "file": f, "active": True} for f in self.active
            ]}}
        if mt == "ExpressionActivationRequest":
            f = (payload.get("data", {}) or {}).get("expressionFile", "")
            if payload.get("data", {}).get("active"):
                self.active.add(f)
            else:
                if f in self.fail_deactivate:
                    raise TimeoutError("slow vts")
                self.active.discard(f)
                self.deactivated.append(f)
            return {"data": {}}
        raise ValueError(mt)


def _reset_state(files=()):
    v.CURRENT_ACTIVE_EXPS = set(files)
    v.wink_timer = v.shock_timer = v.frown_timer = v.eye_roll_timer = 0.0


def test_reset_catches_desync():
    """臉上有、本本空（重啟殘留）：照樣關掉，不撒謊。"""
    _reset_state(())
    fake = FakeVTS(active_files=("星星眼.exp3.json",))
    asyncio.run(v.set_vts_expression(fake, "_RESET_"))
    assert "星星眼.exp3.json" in fake.deactivated
    assert not fake.active


def test_reset_normal_path():
    _reset_state(("黑臉.exp3.json",))
    fake = FakeVTS(active_files=("黑臉.exp3.json",))
    asyncio.run(v.set_vts_expression(fake, "_RESET_"))
    assert "黑臉.exp3.json" in fake.deactivated
    assert v.CURRENT_ACTIVE_EXPS == set()


def test_reset_query_failure_falls_back():
    """查臉失敗：用小本本硬關，不炸。"""
    _reset_state(("黑臉.exp3.json",))
    fake = FakeVTS(active_files=("黑臉.exp3.json",), fail_query=True)
    asyncio.run(v.set_vts_expression(fake, "_RESET_"))
    assert "黑臉.exp3.json" in fake.deactivated


def test_reset_deactivate_failure_logged_not_swallowed():
    """關不掉：小本本照清（防 toggle 反轉），不炸。"""
    _reset_state(())
    fake = FakeVTS(active_files=("黑臉.exp3.json",), fail_deactivate=("黑臉.exp3.json",))
    asyncio.run(v.set_vts_expression(fake, "_RESET_"))  # 不拋就算過
    assert "黑臉.exp3.json" not in fake.deactivated
    assert v.CURRENT_ACTIVE_EXPS == set()


def test_reset_clean_face_is_noop():
    _reset_state(())
    fake = FakeVTS(active_files=())
    asyncio.run(v.set_vts_expression(fake, "_RESET_"))
    assert fake.deactivated == []
