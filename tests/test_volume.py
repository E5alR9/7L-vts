# -*- coding: utf-8 -*-
"""後台音量滑桿：說話、唱歌、鋼琴各一條，0～200（老爸 2026-11-01：後台加滑動桿 0 到 200 音量控制）。"""
import asyncio
import json
import os

import numpy as np
import pytest

import core.paths as paths
from core import volume as V


@pytest.fixture
def vol(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(V, "_cache", {})
    monkeypatch.setattr(V, "_SING_LIVE", {})
    return tmp_path


@pytest.fixture
def mixer():
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
    return pygame


def _tone(pygame, amp, sec=0.5):
    n = int(44100 * sec)
    wave = (np.sin(np.arange(n) * 2 * np.pi * 440 / 44100) * amp * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.column_stack([wave, wave]))


def test_defaults_to_100_and_survives_a_restart(vol):
    assert V.get("speech") == 100 and V.get("sing") == 100
    V.set_volume("speech", 150)
    V.set_volume("sing", 999)              # 超過範圍收在 200
    V._cache.clear()                        # 像重開一樣重讀檔案
    assert V.get("speech") == 150 and V.get("sing") == 200
    assert json.load(open(vol / "volume_settings.json", encoding="utf-8")) == {"speech": 150, "sing": 200}


def test_broken_settings_file_falls_back_to_100(vol):
    (vol / "volume_settings.json").write_text("{壞掉", encoding="utf-8")
    assert V.get("speech") == 100
    (vol / "volume_settings.json").write_text('{"speech": "abc", "sing": -5}', encoding="utf-8")
    V._cache.clear()
    assert V.get("speech") == 100 and V.get("sing") == 0


def test_split_keeps_the_channel_at_most_1_and_boosts_the_rest(vol):
    assert V.split(1.0, "speech") == (1.0, 1.0)              # 100：跟以前一樣
    V.set_volume("speech", 50)
    assert V.split(1.0, "speech") == (0.5, 1.0)
    V.set_volume("sing", 200)
    ch, gain = V.split(0.67, "sing")
    assert ch == 1.0 and gain == pytest.approx(1.34)          # 人聲本來 0.67，兩倍要聲音放大 1.34 倍


def test_boost_makes_it_louder_without_hard_clipping(vol, mixer):
    quiet = _tone(mixer, 0.3)
    loud = V.boost(quiet, 2.0)
    a, b = mixer.sndarray.array(quiet), mixer.sndarray.array(loud)
    assert np.abs(b).max() / np.abs(a).max() == pytest.approx(2.0, rel=0.02)   # 沒到頂：剛好兩倍
    src = _tone(mixer, 0.9)
    hot = mixer.sndarray.array(V.boost(src, 2.0))[:, 0].astype(int)
    assert np.abs(hot).max() < 32767                                           # 快爆音的地方柔和壓住，不撞頂
    x = mixer.sndarray.array(src)[:, 0].astype(int)
    order = np.argsort(x, kind="stable")
    assert (np.diff(hot[order]) >= 0).all()                                    # 越大聲的還是越大聲（不是削成一片平的）
    assert V.boost(quiet, 1.0) is quiet


def test_sliding_during_a_song_changes_that_song_only(vol, mixer):
    snd = _tone(mixer, 0.3, sec=3)
    ch = mixer.mixer.Channel(6)
    ch.play(snd)
    ch.set_volume(0.67)
    V.sing_started({6: (0.67, 1.0, snd)})
    V.set_volume("sing", 50)
    assert ch.get_volume() == pytest.approx(0.335, abs=0.01)
    ch.play(_tone(mixer, 0.3, sec=3))      # 唱完後聲道被說話借走
    ch.set_volume(1.0)
    V.set_volume("sing", 150)
    assert ch.get_volume() == pytest.approx(1.0, abs=0.01)                   # 不去動別人的聲音
    ch.stop()


def test_dashboard_api_sets_each_kind(vol, monkeypatch):
    import services.piano_engine as pe
    import services.web_dashboard as w
    seen = []

    async def fake_piano(v):
        seen.append(v)
        pe.GLOBAL_PIANO_VOLUME = v
    monkeypatch.setattr(pe, "set_piano_volume", fake_piano)
    monkeypatch.setattr(pe, "GLOBAL_PIANO_VOLUME", 100)
    events = []
    monkeypatch.setattr(w, "broadcast_event", lambda t, d: events.append((t, d)))

    class Req:
        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    def call(handler, body=None):
        r = asyncio.run(handler(Req(body)))
        return r.status, json.loads(r.text)

    assert call(w.api_set_volume, {"kind": "speech", "value": 140})[1]["volume"]["speech"] == 140
    assert call(w.api_set_volume, {"kind": "piano", "value": 250})[1]["volume"]["piano"] == 200
    assert seen == [200]
    assert call(w.api_set_volume, {"kind": "sing", "value": "80"})[1]["volume"]["sing"] == 80
    assert call(w.api_set_volume, {"kind": "bgm", "value": 50})[0] == 400
    assert call(w.api_set_volume, {"kind": "speech"})[0] == 400
    assert call(w.api_get_volume)[1]["volume"] == {"speech": 140, "sing": 80, "piano": 200}
    assert events[-1] == ("volume_changed", {"speech": 140, "sing": 80, "piano": 200})


def test_page_has_three_sliders_wired_to_the_api():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    js = open(os.path.join(root, "web", "dashboard.js"), encoding="utf-8").read()
    for kind in ("speech", "sing", "piano"):
        assert f'min="0" max="200" step="1" value="100" data-kind="{kind}"' in html
    assert "fetch('/api/volume'" in js and "'volume_changed'" in js


def test_song_is_released_when_it_ends_but_not_the_next_one(vol, mixer):
    a, b = _tone(mixer, 0.3), _tone(mixer, 0.3)
    V.sing_started({6: (0.67, 1.0, a)})
    V.sing_ended(a)
    assert V._SING_LIVE == {}                       # 唱完：放大過的整首不留著
    V.sing_started({6: (0.67, 1.0, b)})
    V.sing_ended(a)                                 # 上一首的收尾比較晚跑到：不能把這首清掉
    assert V._SING_LIVE[6][2] is b


def test_unsigned_audio_is_left_alone(vol):
    class Fake:
        pass
    import pygame
    snd = Fake()
    orig = pygame.sndarray.array
    pygame.sndarray.array = lambda s: np.full((10, 2), 128, dtype=np.uint8)
    try:
        assert V.boost(snd, 2.0) is snd
    finally:
        pygame.sndarray.array = orig
