# -*- coding: utf-8 -*-
"""開場白等待必須有上限：聊不停就硬開唱，不能無聲沉默。
auto_cover_pipeline 太重？不——它可直接 import（test_sing_queue 已證），但本測
用樁隔離 pygame/core_vts，只驗等待邏輯。"""
import asyncio
import time
import types

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


def test_intro_wait_returns_when_idle(monkeypatch):
    core, _ = _make_core(state="IDLE")
    monkeypatch.setattr(acp, "get_core_vts", lambda: core)
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=5.0))
    assert time.time() - t0 < 3.0  # 緩衝 0.5s 後直接過


def test_intro_wait_breaks_through_chatter(monkeypatch):
    """一直 TALKING 也必須在 timeout 內硬開唱（2026-10-11：無限等修復）。"""
    core, _ = _make_core(state="TALKING", queued=True,
                         last_tts_end=time.time())  # 三個條件全滿
    monkeypatch.setattr(acp, "get_core_vts", lambda: core)
    monkeypatch.setattr(acp.pygame.mixer, "get_init", lambda: None)
    t0 = time.time()
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=1.5))
    el = time.time() - t0
    assert 1.5 <= el < 4.0  # 到點硬過，不多等


def test_intro_wait_no_core_returns(monkeypatch):
    monkeypatch.setattr(acp, "get_core_vts", lambda: None)
    asyncio.run(acp.wait_for_intro_speech_complete(timeout=1.0))


def test_intro_wait_default_timeout():
    """開場等待預設 15 秒（應答約 6 秒，聊不停就硬開唱，不過度禮讓）。"""
    assert acp.wait_for_intro_speech_complete.__defaults__ == (15.0,)
