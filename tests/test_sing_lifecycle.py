# -*- coding: utf-8 -*-
"""翻唱 HUD 生命週期：開唱/完唱/失敗都要把 tts_progress 事件收尾，
不能讓上一首的 RVC 卡在螢幕上（2026-10-11：Mili TTS 時網站還寫 RVC）。"""
import asyncio

from conftest import ROOT  # noqa: F401
import services.auto_cover_pipeline as acp
import services.web_dashboard as web_dash


def _recorder():
    events = []

    def _bcast(etype, data):
        events.append((etype, dict(data)))

    return events, _bcast


def test_cache_hit_broadcasts_incoming(monkeypatch, tmp_path):
    """快取命中要報『即將開唱95%』，等開場白那 10 秒 HUD 不再是舊的 RVC。"""
    import os
    song = "單元測試HUD快取歌"
    safe = acp.get_safe_filename(song)
    voc = os.path.join(acp.CACHE_DIR, f"{safe}_7l_vocal.wav")
    ins = os.path.join(acp.CACHE_DIR, f"{safe}_instrumental.wav")
    for p in (voc, ins):
        with open(p, "wb") as f:
            f.write(b"\x00\x01" * 100000)
    events, bcast = _recorder()
    monkeypatch.setattr(web_dash, "broadcast_event", bcast)
    try:
        got = asyncio.run(acp.prepare_cover_song(song))
        assert got[0] == voc
        stages = [(e[1].get("stage"), e[1].get("percent"), e[1].get("active"))
                  for e in events if e[0] == "rvc_progress"]
        assert ("快取命中即將開唱", 95, True) in stages
    finally:
        for p in (voc, ins):
            if os.path.exists(p):
                os.remove(p)


def test_play_lifecycle_broadcasts(monkeypatch, tmp_path):
    """開唱報100%、結束報收尾（active False），HUD 不會卡住。"""
    events, bcast = _recorder()
    monkeypatch.setattr(web_dash, "broadcast_event", bcast)

    async def fake_play(vocal_path, title, inst_path=None):
        return None

    monkeypatch.setattr(acp, "play_cover_audio", fake_play)
    monkeypatch.setattr(acp, "_send_brain_slip", lambda text: True)
    monkeypatch.setattr(acp, "get_core_vts", lambda: None)  # intro 等待直通

    asyncio.run(acp.play_prepared_song("單元測試HUD開唱歌", "v.wav", "i.wav",
                                       acp._PIPELINE_GEN))
    stages = [(e[1].get("stage"), e[1].get("active")) for e in events
              if e[0] == "rvc_progress"]
    assert ("舞台開唱", True) in stages
    assert ("演唱完畢", False) in stages
    assert stages.index(("舞台開唱", True)) < stages.index(("演唱完畢", False))


def test_prepare_fail_hides_hud(monkeypatch):
    """準備失敗要滅燈，不能停在 50% RVC。"""
    events, bcast = _recorder()
    monkeypatch.setattr(web_dash, "broadcast_event", bcast)
    monkeypatch.setattr(acp, "_send_brain_slip", lambda text: True)

    async def fake_prepare(title):
        return None, None

    monkeypatch.setattr(acp, "prepare_cover_song", fake_prepare)
    asyncio.run(acp._prepare_worker({"title": "單元測試HUD失敗歌",
                                     "requester": ""}, acp._PIPELINE_GEN))
    stages = [(e[1].get("stage"), e[1].get("active")) for e in events
              if e[0] == "rvc_progress"]
    assert ("準備失敗", False) in stages
