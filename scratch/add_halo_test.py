import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "tests/test_sing_queue.py"
src = open(p, encoding="utf-8").read()
assert "_clear_prep_halo" not in src.split("def test_mixed_rendezvous_lifecycle")[0][-500:] or True
block = '''

def test_clear_prep_halo_only_halo_alone():
    """開唱清場：只有暈單獨在臉上才摘，有別的戲/沒暈不碰（2026-10-11 暈帶上台事件）。"""
    import asyncio
    import services.vts_client as vc

    class FakeVTS:
        def __init__(self, active):
            self._active = set(active)
            self.deactivated = []

        async def request(self, payload):
            mt = payload.get("messageType")
            if mt == "ExpressionStateRequest":
                return {"data": {"expressions": [
                    {"file": f, "active": True} for f in self._active]}}
            if mt == "ExpressionActivationRequest":
                f = (payload.get("data", {}) or {}).get("expressionFile", "")
                if not (payload.get("data", {}) or {}).get("active", True):
                    self._active.discard(f)
                    self.deactivated.append(f)
            return {"data": {}}

    halo = (vc.VTS_EXPRESSION_MAP or {}).get("暈")
    assert halo, "選單沒有暈"
    old_set, old_vts = getattr(vc, "CURRENT_ACTIVE_EXPS", set()), vc.GLOBAL_VTS
    try:
        # 只有暈（busy worker 經 trigger 登記在小本本）→摘掉
        vc.CURRENT_ACTIVE_EXPS = {halo}
        vc.GLOBAL_VTS = FakeVTS({halo})
        assert asyncio.run(acp._clear_prep_halo()) is True
        assert vc.GLOBAL_VTS.deactivated == [halo]
        # 臉空→不動
        vc.GLOBAL_VTS = FakeVTS(set())
        assert asyncio.run(acp._clear_prep_halo()) is False
        # 暈＋別的→不動（不搶戲）
        vc.GLOBAL_VTS = FakeVTS({halo, "星星眼.exp3.json"})
        vc.CURRENT_ACTIVE_EXPS = {"星星眼.exp3.json"}
        assert asyncio.run(acp._clear_prep_halo()) is False
        assert vc.GLOBAL_VTS.deactivated == []
    finally:
        vc.CURRENT_ACTIVE_EXPS = old_set
        vc.GLOBAL_VTS = old_vts
'''
assert "_clear_prep_halo_only_halo_alone" not in src
open(p, "w", encoding="utf-8", newline="").write(src + block)
print("appended")
