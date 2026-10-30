# -*- coding: utf-8 -*-
"""軍師（services/advisor.py，2026-10-29 老爸：3.8 think 當 Live 主腦的常駐子代理，一直聽、給她建議）。
連線換成假的：一條連線問好幾輪、交辦結果下一輪一起帶上、[SILENCE] 回空、換線帶續接 handle、斷線換一條重問。"""
import asyncio
from types import SimpleNamespace

import services.advisor as adv


class _FakeSession:
    def __init__(self, replies, script):
        self.replies, self.script, self.sent = replies, script, []

    async def send_client_content(self, turns, turn_complete):
        self.sent.append(turns[0].parts[0].text)

    async def receive(self):
        kind, text = self.replies.pop(0)
        if kind == "boom":
            raise ConnectionError("1011 斷線")
        if kind == "goaway":
            yield SimpleNamespace(session_resumption_update=None, go_away=True, server_content=None)
        yield SimpleNamespace(session_resumption_update=SimpleNamespace(resumable=True, new_handle=f"h{len(self.sent)}"),
                              go_away=None, server_content=None)
        yield SimpleNamespace(session_resumption_update=None, go_away=None, server_content=SimpleNamespace(
            output_transcription=SimpleNamespace(text=text), turn_complete=False))
        yield SimpleNamespace(session_resumption_update=None, go_away=None, server_content=SimpleNamespace(
            output_transcription=None, turn_complete=True))


def _advisor(replies):
    opened = []

    class _CM:
        def __init__(self, cfg):
            self.cfg = cfg
            self.s = _FakeSession(replies, None)

        async def __aenter__(self):
            opened.append(self)
            return self.s

        async def __aexit__(self, *a):
            return False
    a = adv.ResidentAdvisor(lambda: "軍師規則", keys=["k1"], connect=lambda key, model, cfg: _CM(cfg))
    return a, opened


def test_one_connection_many_turns_and_results_ride_along():
    a, opened = _advisor([("ok", "[SILENCE]"), ("ok", "建議：明天是 32 度，不是 20 度")])

    async def go():
        r1 = await a.ask("老爸說：晚安\n7L 回：晚安～")
        a.note("（7L 交辦的結果回來了：明天台北多雲轉晴，最高 32 度）")
        r2 = await a.ask("老爸說：明天幾度\n7L 回：20 度喔")
        return r1, r2
    r1, r2 = asyncio.run(go())
    assert r1 == "" and r2.startswith("建議：明天是 32 度")             # 打招呼那輪沒建議
    assert len(opened) == 1                                             # 同一條連線：記得前面
    sent = opened[0].s.sent
    assert "最高 32 度" in sent[1] and sent[1].index("最高 32 度") < sent[1].index("20 度喔")
    assert "low" in str(opened[0].cfg.thinking_config.thinking_level).lower()   # 實測 low 每輪 1 秒內、medium 6～9 秒


def test_goaway_reconnects_with_the_resume_handle():
    a, opened = _advisor([("goaway", "[SILENCE]"), ("ok", "[SILENCE]")])

    async def go():
        await a.ask("第一輪")
        await a.ask("第二輪")
    asyncio.run(go())
    assert len(opened) == 2 and opened[1].cfg.session_resumption.handle == "h1"   # 換線不失憶


def test_a_dropped_connection_is_retried_once_then_gives_up_quietly():
    a, opened = _advisor([("boom", ""), ("ok", "建議：補一句")])
    assert asyncio.run(a.ask("這輪")) == "建議：補一句" and len(opened) == 2
    a, opened = _advisor([("boom", ""), ("boom", "")])
    assert asyncio.run(a.ask("這輪")) == "" and len(opened) == 2          # 兩次都斷：這輪放棄，不拋錯


def test_transcript_noise_is_not_a_suggestion():
    """2026-10-30 實測：一般 3.8 沒話說時轉寫出「<no speech>{pause}」，差點被當成建議遞給她。"""
    assert adv.clean_reply("<no speech>{pause}") == ""
    assert adv.clean_reply("  [SILENCE] ") == ""
    assert adv.clean_reply("建議：週三降溫到 22 度<noise>") == "建議：週三降溫到 22 度"
