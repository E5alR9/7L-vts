# -*- coding: utf-8 -*-
"""備援分出來的分軌、壞掉的分軌不當快取命中（2026-11-01：快取裡 8 首一直是 ffmpeg 相位抵消分的，伴奏留著原唱；
另一首人聲檔整個是零，那首永遠唱不出來）。"""
import asyncio
import os

import numpy as np
import soundfile as sf

import services.auto_cover_pipeline as acp


def _wav(path, sec=3.0):
    sf.write(path, np.zeros((int(44100 * sec), 2), dtype="float32") + 0.01, 44100)


def _age(path, sec=7 * 3600):
    t = os.path.getmtime(path) - sec
    os.utime(path, (t, t))


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(acp, "CACHE_DIR", str(tmp_path))
    raw = str(tmp_path / "歌_raw.wav")
    _wav(raw)
    return raw


def test_good_cache_hits_without_separating(tmp_path, monkeypatch):
    raw = _setup(tmp_path, monkeypatch)
    _wav(str(tmp_path / "歌_vocals.wav"))
    _wav(str(tmp_path / "歌_instrumental.wav"))
    import services.gpu_split as gs
    monkeypatch.setattr(gs, "separate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該重分")))
    v, i = acp.separate_stems_gpu(raw, "歌")
    assert v.endswith("歌_vocals.wav") and i.endswith("歌_instrumental.wav")


def test_fallback_is_flagged_and_redone_next_time(tmp_path, monkeypatch):
    raw = _setup(tmp_path, monkeypatch)
    import services.gpu_split as gs
    monkeypatch.setattr(gs, "separate", lambda *a, **k: False)
    monkeypatch.setattr(acp.subprocess, "run", lambda cmd, **k: _wav(cmd[-1]) or type("R", (), {"returncode": 1})())
    acp.separate_stems_gpu(raw, "歌")
    assert os.path.exists(acp._redo_flag("歌"))
    assert not acp._stems_need_redo("歌")                     # 剛備援分完：先湊合用，不馬上重試
    _age(acp._redo_flag("歌"))
    assert acp._stems_need_redo("歌")

    calls = []

    def good(inp, v, i, **k):
        calls.append(inp)
        _wav(v)
        _wav(i)
        return True
    monkeypatch.setattr(gs, "separate", good)
    acp.separate_stems_gpu(raw, "歌")
    assert calls and not os.path.exists(acp._redo_flag("歌")) and not acp._stems_need_redo("歌")


def test_all_zero_vocals_file_is_not_a_cache_hit(tmp_path, monkeypatch):
    raw = _setup(tmp_path, monkeypatch)
    with open(tmp_path / "歌_vocals.wav", "wb") as f:
        f.write(b"\0" * 200000)
    _wav(str(tmp_path / "歌_instrumental.wav"))
    assert acp._stems_need_redo("歌")
    import services.gpu_split as gs
    calls = []
    monkeypatch.setattr(gs, "separate", lambda inp, v, i, **k: calls.append(1) or (_wav(v), _wav(i)) and True)
    acp.separate_stems_gpu(raw, "歌")
    assert calls and not acp._stems_need_redo("歌")


def test_prepare_skips_old_voice_when_stems_must_be_redone(tmp_path, monkeypatch):
    """備援分的那首就算有 7L 聲線檔，也要重分重轉，不直接唱舊的。"""
    _setup(tmp_path, monkeypatch)
    for suf in ("_vocals.wav", "_instrumental.wav", "_7l_vocal.wav"):
        _wav(str(tmp_path / f"歌{suf}"))
    open(acp._redo_flag("歌"), "w").close()
    _age(acp._redo_flag("歌"))
    seen = []

    def sep(raw, name, tag=""):
        seen.append("分離")
        os.remove(acp._redo_flag("歌"))
        return str(tmp_path / "歌_vocals.wav"), str(tmp_path / "歌_instrumental.wav")

    def rvc(vin, vout, semi=0.0, auto_pitch=True):
        seen.append("RVC")
        _wav(vout)
        return True
    monkeypatch.setattr(acp, "separate_stems_gpu", sep)
    monkeypatch.setattr(acp, "pitch_shift_vocal_to_female", rvc)

    async def no_wait(*a, **k):
        return 0.0
    monkeypatch.setattr(acp, "_let_her_finish_talking", no_wait)
    v, i = asyncio.run(acp.prepare_cover_song("歌"))
    assert seen == ["分離", "RVC"] and v.endswith("歌_7l_vocal.wav")


def test_broken_accompaniment_or_missing_original(tmp_path, monkeypatch):
    raw = _setup(tmp_path, monkeypatch)
    _wav(str(tmp_path / "歌_vocals.wav"))
    with open(tmp_path / "歌_instrumental.wav", "wb") as f:
        f.write(b"\0" * 200000)
    assert acp._stems_need_redo("歌")                          # 伴奏壞了也要重分
    _wav(str(tmp_path / "歌_instrumental.wav"))
    open(acp._redo_flag("歌"), "w").close()
    _age(acp._redo_flag("歌"))
    os.remove(raw)
    assert not acp._stems_need_redo("歌")                      # 原曲沒了：重抓可能是別的錄音，先用舊的


def test_two_requests_for_the_same_song_separate_once(tmp_path, monkeypatch):
    import threading
    import time
    raw = _setup(tmp_path, monkeypatch)
    import services.gpu_split as gs
    calls = []

    def slow(inp, v, i, **k):
        calls.append(1)
        time.sleep(0.3)
        _wav(v)
        _wav(i)
        return True
    monkeypatch.setattr(gs, "separate", slow)
    ts = [threading.Thread(target=acp.separate_stems_gpu, args=(raw, "歌")) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert calls == [1]
