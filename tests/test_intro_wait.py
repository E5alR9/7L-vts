# -*- coding: utf-8 -*-
"""開場白等待必須有上限：聊不停就硬開唱，不能無聲沉默。
auto_cover_pipeline 太重？不——它可直接 import（test_sing_queue 已證），但本測
用樁隔離 pygame/core_vts，只驗等待邏輯。"""
import asyncio
import time
import types

import pytest

from conftest import ROOT  # noqa: F401
import services.auto_cover_pipeline as acp


class _FakeMusic:
    def __init__(self, busy=False):
        self._busy = busy

    def get_busy(self):
        return self._busy


def _make_core(state="IDLE", queued=False, last_tts_end=0.0, music_busy=False):
    q = asyncio.Queue()
    if queued:
        q.put_nowait({"text": "x"})
    return types.SimpleNamespace(
        current_ai_state=state,
        speech_queue=q,
        LAST_TTS_END_TIME=last_tts_end,
    ), music_busy


@pytest.fixture(autouse=True)
def _stage_state(monkeypatch):
    import core.stage_state as stage
    monkeypatch.setattr(stage, "AI_STATE", "IDLE")   # 每個測試自己設，跑完還原
    return stage


def _host(core):
    """main() 用 bind_host 交進來的那幾樣（2026-10-25 起不再撈主程式模組）；AI 狀態在 core.stage_state（2026-10-26）。"""
    import core.stage_state as stage
    stage.AI_STATE = core.current_ai_state
    return {"speech_queue": core.speech_queue, "get_last_tts_end": lambda: core.LAST_TTS_END_TIME}


def test_intro_wait_returns_when_idle(monkeypatch):
    core, _ = _make_core(state="IDLE")
    monkeypatch.setattr(acp, "_HOST", _host(core))
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=5.0))
    assert time.time() - t0 < 3.0  # 緩衝 0.5s 後直接過


def test_intro_wait_breaks_through_chatter(monkeypatch):
    """一直 TALKING 也必須在 timeout 內硬開唱（2026-10-11：無限等修復）。"""
    core, _ = _make_core(state="TALKING", queued=True,
                         last_tts_end=time.time())  # 三個條件全滿
    monkeypatch.setattr(acp, "_HOST", _host(core))
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=1.5))
    el = time.time() - t0
    assert 1.5 <= el < 4.0  # 到點硬過，不多等


def test_intro_wait_no_core_returns(monkeypatch):
    monkeypatch.setattr(acp, "_HOST", {})
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=1.0))


def test_intro_wait_default_timeout():
    """開場等待預設 15 秒（應答約 6 秒，聊不停就硬開唱，不過度禮讓）。"""
    assert acp.wait_for_intro_speech_complete.__defaults__ == (15.0, 0.0, 0.0)   # 第二個：剛點的歌等主腦應答的期限（預設不等）；第三個：點歌時間


def test_just_requested_song_waits_for_the_brains_reply(monkeypatch):
    """剛點的歌（2026-10-26 拿掉罐頭應答）：主腦的回覆 2～3 秒才到，等它排進來、講完再唱。"""
    core, _ = _make_core(state="IDLE")
    monkeypatch.setattr(acp, "_HOST", _host(core))
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)

    async def go():
        async def brain_replies():
            await asyncio.sleep(1.2)
            core.speech_queue.put_nowait({"text": "Faded 馬上來"})
            await asyncio.sleep(0.5)
            core.speech_queue.get_nowait()          # 講完
            core.LAST_TTS_END_TIME = 0.0
        asyncio.ensure_future(brain_replies())
        t0 = time.time()
        await acp.wait_for_intro_speech_complete(timeout=10.0, reply_deadline=time.time() + 5.0)
        return time.time() - t0
    el = asyncio.run(go())
    assert 1.6 <= el < 4.5           # 等到回覆排進來、講完；沒等滿 5 秒


def test_silent_reply_starts_the_song_right_away(monkeypatch):
    """2026-10-29：她這輪回 [SILENCE]（不講開場）＝回完了、沒有要講的，備好的歌馬上唱，不乾等到期限。"""
    core, _ = _make_core(state="IDLE")
    host = _host(core)
    done = {"ts": 0.0}
    host["get_last_reply_done"] = lambda: done["ts"]
    monkeypatch.setattr(acp, "_HOST", host)
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)

    async def go():
        asked = time.time()

        async def brain_stays_silent():
            await asyncio.sleep(1.0)
            done["ts"] = time.time()
        asyncio.ensure_future(brain_stays_silent())
        t0 = time.time()
        await acp.wait_for_intro_speech_complete(timeout=10.0, reply_deadline=asked + 15.0, asked=asked)
        return time.time() - t0
    el = asyncio.run(go())
    assert 1.0 <= el < 3.0           # 她回完就唱，不等 15 秒


def test_reply_finished_before_the_tool_counts(monkeypatch):
    """她先講再叫工具：點歌前 1 秒內回完的也算（話已經排進佇列，下一步照樣等她講完）。"""
    core, _ = _make_core(state="IDLE")
    host = _host(core)
    asked = time.time()
    host["get_last_reply_done"] = lambda: asked - 0.5
    monkeypatch.setattr(acp, "_HOST", host)
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=10.0, reply_deadline=asked + 15.0, asked=asked))
    assert time.time() - t0 < 2.0
    host["get_last_reply_done"] = lambda: asked - 30.0   # 半分鐘前的舊回覆不算：照等到期限
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=10.0, reply_deadline=time.time() + 1.0, asked=asked))
    assert 0.9 <= time.time() - t0 < 3.0


def test_reply_wait_gives_up_at_the_deadline(monkeypatch):
    core, _ = _make_core(state="IDLE")
    monkeypatch.setattr(acp, "_HOST", _host(core))
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=10.0, reply_deadline=time.time() + 1.0))
    assert 0.9 <= time.time() - t0 < 3.0   # 主腦沒回：到期限就唱
