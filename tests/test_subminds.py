# -*- coding: utf-8 -*-
"""副意識群（services/subminds.py，2026-10-30 老爸：參考人腦，主意識只有 Live 主腦，旁邊很多副意識一起想）。
連線換成假的：每個副意識各用自己的 key 和模型、同時想、想太久的這輪不等、建議照重要順序併成一張紙條。"""
import asyncio
import time
from types import SimpleNamespace

import pytest

import services.advisor as adv
import services.subminds as sm
from core import promptkit


class _Session:
    def __init__(self, reply, delay):
        self.reply, self.delay, self.sent = reply, delay, []

    async def send_client_content(self, turns, turn_complete):
        self.sent.append(turns[0].parts[0].text)

    async def receive(self):
        await asyncio.sleep(self.delay)
        yield SimpleNamespace(session_resumption_update=None, go_away=None, server_content=SimpleNamespace(
            output_transcription=SimpleNamespace(text=self.reply), turn_complete=False))
        yield SimpleNamespace(session_resumption_update=None, go_away=None, server_content=SimpleNamespace(
            output_transcription=None, turn_complete=True))


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(adv, "log_print", lambda *a: None)
    monkeypatch.setattr(sm, "log_print", lambda *a: None)


def _minds(plan, wait_sec=1.0):
    """plan[名字] = (回覆, 要想幾秒)；回 (SubMinds, 開過的連線 [(名字, key, model, cfg, session)])。"""
    opened = []

    def connect(key, model, cfg):
        name = cfg.system_instruction.parts[0].text.split("「")[1].split("」")[0]
        reply, delay = plan[name]
        s = _Session(reply, delay)

        class _CM:
            async def __aenter__(self):
                opened.append((name, key, model, cfg, s))
                return s

            async def __aexit__(self, *a):
                return False
        return _CM()
    keys = [f"k{i}" for i in range(10)]
    return sm.SubMinds(lambda role: promptkit.submind_system("老爸", role), keys=keys, connect=connect,
                       wait_sec=wait_sec), opened


def test_every_submind_thinks_at_once_on_its_own_key_and_model():
    plan = {name: ("[SILENCE]", 0.2) for name, _, _ in sm.ROLES}
    plan["查核"] = ("建議：查到的是晴天 31 度，不是下雨", 0.2)
    plan["情緒"] = ("建議：老爸說他很累，先關心他一句", 0.2)
    minds, opened = _minds(plan)
    t = time.monotonic()
    got = asyncio.run(minds.ask("老爸說：好累，高雄明天天氣？\n7L 回：會下雨喔"))
    assert time.monotonic() - t < 0.6                       # 同時想，不是一個接一個（5 × 0.2 秒）
    assert [g[0] for g in got] == ["查核", "情緒"]          # 只留有話說的，講錯的排前面
    assert len({o[1] for o in opened}) == len(sm.ROLES)     # 每個副意識各用不同的 key
    models = {o[0]: (o[2], o[3].thinking_config) for o in opened}
    assert models["查核"][0] == sm.DEEP_THINK_LIVE_MODEL and str(models["查核"][1].thinking_level.value).lower() == "low"
    assert models["情緒"][0] == sm.LIVE_MODEL and models["情緒"][1] is None   # 一般 3.8 帶思考設定會被拒


def test_a_submind_that_thinks_too_long_is_not_waited_for():
    plan = {name: ("[SILENCE]", 0.1) for name, _, _ in sm.ROLES}
    plan["查核"] = ("建議：數字講錯了", 0.1)
    plan["話題"] = ("建議：反問老爸晚餐吃什麼", 5.0)
    minds, _ = _minds(plan, wait_sec=0.5)
    t = time.monotonic()
    got = asyncio.run(minds.ask("老爸說：今天加班\n7L 回：辛苦了"))
    assert time.monotonic() - t < 1.5 and [g[0] for g in got] == ["查核"]


def test_results_reach_every_submind_next_turn():
    plan = {name: ("[SILENCE]", 0.0) for name, _, _ in sm.ROLES}
    minds, opened = _minds(plan)
    minds.note("（7L 交辦的結果回來了：高雄明天晴，最高 31 度）")
    asyncio.run(minds.ask("老爸說：高雄呢\n7L 回：晴天喔"))
    assert all("高雄明天晴" in o[4].sent[0] for o in opened)


def test_suggestions_merge_into_one_slip_without_repeats():
    merged = sm.merge_suggestions([("查核", "建議：明天是晴天 31 度，不是下雨", 3.0),
                                   ("記憶", "建議：明天是晴天 31 度，不是下雨喔", 4.0),
                                   ("情緒", "建議：老爸很累，先關心他", 9.0)])
    assert merged == "【查核】明天是晴天 31 度，不是下雨\n【情緒】老爸很累，先關心他"


def test_each_submind_prompt_names_its_own_job():
    for role in promptkit.SUBMIND_FOCUS:
        text = promptkit.submind_system("老爸", role)
        assert f"「{role}」" in text and promptkit.SUBMIND_FOCUS[role] in text and "[SILENCE]" in text
