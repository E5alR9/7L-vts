# -*- coding: utf-8 -*-
"""自創曲管線（Lyria 桌面版 MP3 → originals/ → 分離/RVC/開唱）：命名空間隔離、
缺檔短路、隊列攜帶 origin。 sämtlich 不碰 GPU/網路（分離與 RVC 用假函數）。"""
import asyncio
import os
import wave

from conftest import ROOT  # noqa: F401
import services.auto_cover_pipeline as acp
import services.web_dashboard as web_dash


def _tiny_wav(path, seconds=1.0):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x01\x02\x03" * int(44100 * seconds))
    return path


def _make_fake_mp3(path):
    """副檔名 mp3、內容 wav（ffmpeg 按內容嗅探，照轉不誤）。"""
    tmp = path + ".tmp.wav"
    _tiny_wav(tmp)
    import subprocess
    r = subprocess.run([acp.FFMPEG_EXE, "-y", "-i", tmp, "-ar", "44100", "-ac", "2", path],
                       capture_output=True, timeout=60)
    os.remove(tmp)
    assert r.returncode == 0 and os.path.exists(path)
    return path


def test_convert_local_to_raw(tmp_path):
    src = _make_fake_mp3(str(tmp_path / "song.mp3"))
    out = str(tmp_path / "song_raw.wav")
    assert acp._convert_local_to_raw(src, out) is True
    assert os.path.getsize(out) > 10000
    assert acp._convert_local_to_raw(src, out) is True  # 快取沿用
    assert acp._convert_local_to_raw(str(tmp_path / "nope.mp3"), out + "2") is False


def test_prepare_original_full_path(monkeypatch, tmp_path):
    """自創曲整管：orig_ 命名空間＋分離/RVC 照跑＋回傳路徑。"""
    src = _make_fake_mp3(str(tmp_path / "MySong.mp3"))
    calls = {}

    def fake_sep(input_wav, song_name, tag=""):
        calls["sep_in"] = input_wav
        calls["sep_tag"] = tag
        # 照真實契約寫進快取路徑（含 orig_ 命名空間）
        safe = tag + acp.get_safe_filename(song_name)
        v = os.path.join(acp.CACHE_DIR, f"{safe}_vocals.wav")
        i = os.path.join(acp.CACHE_DIR, f"{safe}_instrumental.wav")
        _tiny_wav(v)
        _tiny_wav(i)
        return v, i

    def fake_rvc(vocal_in, vocal_out, *a, **k):
        calls["rvc_in"] = vocal_in
        _tiny_wav(vocal_out, seconds=2.0)
        return True

    monkeypatch.setattr(acp, "separate_stems_gpu", fake_sep)
    monkeypatch.setattr(acp, "pitch_shift_vocal_to_female", fake_rvc)
    monkeypatch.setattr("services.roformer_sep.separate_roformer",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該走真分離")))

    song = "單元測試自創曲完整鏈"
    vocal, inst = asyncio.run(acp.prepare_cover_song(song, source_mp3=src, origin="original"))
    safe = "orig_" + acp.get_safe_filename(song)
    try:
        assert vocal == os.path.join(acp.CACHE_DIR, f"{safe}_7l_vocal.wav")
        assert inst == os.path.join(acp.CACHE_DIR, f"{safe}_instrumental.wav")
        assert calls["sep_tag"] == "orig_"  # 分離也被關進命名空間（否則污染翻唱快取）
        assert calls["sep_in"] == os.path.join(acp.CACHE_DIR, f"{safe}_raw.wav")
        assert os.path.exists(calls["sep_in"])  # mp3 已轉好躺在 orig_ 命名空間
        # YouTube 命名空間沒被污染
        plain = acp.get_safe_filename(song)
        assert not os.path.exists(os.path.join(acp.CACHE_DIR, f"{plain}_raw.wav"))
    finally:
        import glob
        for p in glob.glob(os.path.join(acp.CACHE_DIR, f"{safe}_*")):
            if os.path.isfile(p):
                os.remove(p)


def test_prepare_original_missing_file():
    vocal, inst = asyncio.run(acp.prepare_cover_song("單元測試自創曲缺檔",
                                                     source_mp3="", origin="original"))
    assert (vocal, inst) == (None, None)
    vocal2, _ = asyncio.run(acp.prepare_cover_song("單元測試自創曲缺檔2",
                                                   source_mp3="C:/nope.mp3", origin="original"))
    assert vocal2 is None


def test_queue_carries_origin_and_worker_slip(monkeypatch):
    """排隊攜帶 origin；缺檔的失敗紙條是 MP3 文案不是通用文案。"""
    slips = []
    monkeypatch.setattr(acp, "_send_brain_slip", lambda text: slips.append(text) or True)
    events = []
    monkeypatch.setattr(web_dash, "broadcast_event",
                        lambda et, data: events.append((et, dict(data))))

    async def fake_prepare(title, source_mp3="", origin=""):
        assert origin == "original" and source_mp3 == ""
        return None, None

    monkeypatch.setattr(acp, "prepare_cover_song", fake_prepare)
    acp.SONG_REQUEST_QUEUE.clear()
    msg = acp.request_cover_song("單元測試自創曲排隊", "老爸", source_mp3="", origin="original")
    assert acp.SONG_REQUEST_QUEUE[0]["origin"] == "original"
    asyncio.run(acp._prepare_worker({"title": "單元測試自創曲排隊", "requester": "老爸",
                                     "source_mp3": "", "origin": "original"},
                                    acp._PIPELINE_GEN))
    assert any("originals" in s for s in slips), slips
    assert any(e[0] == "rvc_progress" and e[1].get("active") is False for e in events)
    acp.SONG_REQUEST_QUEUE.clear()


# ── originals 感測：一輪掃描（只準備不排隊）───────────────────────────────
def test_scan_originals_prepares_new_and_skips_ready(monkeypatch, tmp_path):
    import core.hard_command as hc
    monkeypatch.setattr(hc, "ORIGINALS_DIR", str(tmp_path))
    open(tmp_path / "New_Song.mp3", "wb").write(b"\x00" * 100)
    open(tmp_path / "note.txt", "w").write("x")
    calls = []

    async def fake_prepare(title, source_mp3="", origin=""):
        calls.append((title, source_mp3, origin))
        return (None, None)

    monkeypatch.setattr(acp, "prepare_cover_song", fake_prepare)
    done = asyncio.run(acp.scan_originals_once())
    assert done == []  # fake 回 None，不算備好
    assert calls == [("New Song", str(tmp_path / "New_Song.mp3"), "original")]
    assert acp._ORIG_PREPARING == set()  # 鎖有放掉


def test_scan_originals_skips_prepared(monkeypatch, tmp_path):
    import core.hard_command as hc
    monkeypatch.setattr(hc, "ORIGINALS_DIR", str(tmp_path))
    open(tmp_path / "Done_Song.mp3", "wb").write(b"\x00" * 100)
    safe = "orig_" + acp.get_safe_filename("Done Song")
    ready = os.path.join(acp.CACHE_DIR, f"{safe}_7l_vocal.wav")
    with open(ready, "wb") as f:
        f.write(b"\x00" * 200000)
    calls = []

    async def fake_prepare(title, source_mp3="", origin=""):
        calls.append(title)
        return ("v", "i")

    monkeypatch.setattr(acp, "prepare_cover_song", fake_prepare)
    try:
        done = asyncio.run(acp.scan_originals_once())
        assert done == [] and calls == []  # 成品在，連碰都不碰
    finally:
        os.remove(ready)
