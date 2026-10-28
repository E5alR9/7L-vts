# -*- coding: utf-8 -*-
"""兩台分工（services/gpu_split.py）：切點規劃、接縫合併，和筆電有開時兩首同時準備仍照點歌順序唱。"""
from conftest import ROOT  # noqa: F401
import asyncio
import time

import numpy as np
import pytest
import soundfile as sf

import services.auto_cover_pipeline as acp
import services.gpu_split as gs
import services.remote_gpu as rg


@pytest.fixture(autouse=True)
def _machines():
    saved = (gs.DESK.rate, gs.LAP.rate)
    gs.DESK.rate, gs.LAP.rate = 1.8, 0.75
    gs.DESK.reserved.clear()
    gs.LAP.reserved.clear()
    yield
    gs.DESK.rate, gs.LAP.rate = saved
    gs.DESK.reserved.clear()
    gs.LAP.reserved.clear()


def test_plan_desk_only_without_laptop():
    plan, _ = gs._plan(240 * gs.SR, gs.SR, lap_ok=False)
    assert [(m, s, e) for m, s, e, _c in plan] == [(gs.DESK, 0, 240 * gs.SR)]


def test_plan_split_keeps_seam_clear_of_both_edges():
    n = 240 * gs.SR
    plan, eta = gs._plan(n, gs.SR, lap_ok=True)
    assert [m for m, *_ in plan] == [gs.DESK, gs.LAP]
    (_, d0, d_end, cut), (_, l_start, l_end, _c) = plan
    assert d0 == 0 and l_end == n
    assert l_start % gs.STEP == 0                       # 後段對齊整首的窗
    assert d_end - cut >= gs.CHUNK + gs.VALID           # 接縫離前段尾超過一窗
    assert cut - l_start >= gs.CHUNK + gs.VALID         # 接縫離後段頭超過一窗
    assert cut > n / 2                                  # 桌機快，分得多
    assert eta - time.time() < 240 / 1.8                # 比桌機整首自己分快


def test_plan_goes_to_whichever_machine_is_free():
    n = 200 * gs.SR
    gs.DESK.reserved["other song"] = time.time() + 1000
    plan, _ = gs._plan(n, gs.SR, lap_ok=True)
    assert [m for m, *_ in plan] == [gs.LAP]
    gs.DESK.reserved.clear()
    gs.LAP.reserved["other song"] = time.time() + 1000
    plan, _ = gs._plan(n, gs.SR, lap_ok=True)
    assert [m for m, *_ in plan] == [gs.DESK]


def test_short_song_not_split():
    plan, _ = gs._plan(40 * gs.SR, gs.SR, lap_ok=True)
    assert len(plan) == 1


def test_desktop_failure_hands_whole_song_to_laptop(monkeypatch):
    """桌機顯卡掉了（CUDA unknown error）不要只在桌機重試，整首丟筆電。"""
    calls = []

    def fake_run(m, src, voc, ins, song, progress_cb=None):
        calls.append(m.name)
        return m is gs.LAP

    monkeypatch.setattr(gs, "_run", fake_run)
    monkeypatch.setattr(rg, "available", lambda: True)
    assert gs._whole("in.wav", "v.wav", "i.wav", "歌", None) is True
    assert calls == ["桌機", "筆電"]
    calls.clear()
    monkeypatch.setattr(rg, "available", lambda: False)
    assert gs._whole("in.wav", "v.wav", "i.wav", "歌", None) is False
    assert calls == ["桌機"]


def test_merge_matches_level_and_crossfades(tmp_path):
    sr, n = gs.SR, 60 * gs.SR
    rng = np.random.default_rng(0)
    x = (0.3 * rng.standard_normal((n, 2))).clip(-0.85, 0.85)
    cut = 30 * sr
    d_end, l_start = cut + gs.VALID + gs.CHUNK, (cut - gs.VALID - gs.CHUNK) // gs.STEP * gs.STEP
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    sf.write(a, x[:d_end], sr, subtype="FLOAT")
    sf.write(b, 0.9 * x[l_start:], sr, subtype="FLOAT")   # 後段被 audio-separator 自己壓過
    out = tmp_path / "out.wav"
    g = gs._merge([(0, d_end, str(a)), (l_start, n, str(b))], cut, n, str(out), "test")
    y, _ = sf.read(out, always_2d=True)
    assert abs(g - 1 / 0.9) < 1e-3
    assert len(y) == n
    assert np.max(np.abs(y - x)) < 2 / 32768             # 只剩 16 位元捨入


def test_two_songs_prepared_together_still_sung_in_order(monkeypatch):
    """筆電有開：後點的先準備好，也要等先點的唱完才輪到它。"""
    for q in (acp.SONG_REQUEST_QUEUE, acp.READY_SONGS, acp._ACTIVE_TITLES, acp._PREPARING_SEQS):
        q.clear()
    acp._ORCH_TASK = acp._PREPARE_TASK = acp._PREPARE_TASK2 = acp._PLAY_TASK = None
    acp.IS_SINGING_ACTIVE = False
    started, sung = [], []

    async def fake_prepare(title, source_mp3="", origin=""):
        started.append((title, time.monotonic()))
        await asyncio.sleep(0.6 if title == "先點的" else 0.1)
        return f"{title}.wav", f"{title}_inst.wav"

    async def fake_play(title, vocal, inst, gen):
        sung.append(title)
        acp._ACTIVE_TITLES.discard(acp._dedupe_key(title))
        return ""

    monkeypatch.setattr(acp, "prepare_cover_song", fake_prepare)
    monkeypatch.setattr(acp, "play_prepared_song", fake_play)
    monkeypatch.setattr(rg, "available", lambda: True)
    monkeypatch.setattr(acp, "_stage_busy", lambda: False)

    async def go():
        acp.request_cover_song("先點的", "老爸")
        acp.request_cover_song("後點的", "老爸")
        await asyncio.wait_for(acp._sing_orchestrator(), 10)

    asyncio.run(go())
    assert [t for t, _ in started] == ["先點的", "後點的"]
    assert started[1][1] - started[0][1] < 0.6          # 第二首沒等第一首做完就開始準備
    assert sung == ["先點的", "後點的"]


def test_laptop_off_prepares_one_at_a_time(monkeypatch):
    for q in (acp.SONG_REQUEST_QUEUE, acp.READY_SONGS, acp._ACTIVE_TITLES, acp._PREPARING_SEQS):
        q.clear()
    acp._ORCH_TASK = acp._PREPARE_TASK = acp._PREPARE_TASK2 = acp._PLAY_TASK = None
    running, peak = [0], [0]

    async def fake_prepare(title, source_mp3="", origin=""):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        await asyncio.sleep(0.2)
        running[0] -= 1
        return f"{title}.wav", f"{title}_inst.wav"

    async def fake_play(title, vocal, inst, gen):
        acp._ACTIVE_TITLES.discard(acp._dedupe_key(title))
        return ""

    monkeypatch.setattr(acp, "prepare_cover_song", fake_prepare)
    monkeypatch.setattr(acp, "play_prepared_song", fake_play)
    monkeypatch.setattr(rg, "available", lambda: False)
    monkeypatch.setattr(acp, "_stage_busy", lambda: False)

    async def go():
        acp.request_cover_song("歌一", "老爸")
        acp.request_cover_song("歌二", "老爸")
        await asyncio.wait_for(acp._sing_orchestrator(), 10)

    asyncio.run(go())
    assert peak[0] == 1
