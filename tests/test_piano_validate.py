# -*- coding: utf-8 -*-
"""線上抓譜驗證（2026-10-11 logo 事件：onlinesequencer.net logo 被當成晴天播）。
標題不符擋掉、可播性下限擋掉，不碰網路。"""
import services.piano_engine as pe


def _write_mid(path, notes=30, seconds=30.0):
    import mido
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("program_change", program=0, time=0))
    per = max(1, int(480 * seconds / max(notes, 1)))
    for i in range(notes):
        tr.append(mido.Message("note_on", note=60 + (i % 12), velocity=90, time=0))
        tr.append(mido.Message("note_off", note=60 + (i % 12), velocity=0, time=per))
    mid.save(path)
    return path


def test_match_valid_rejects_logo():
    assert pe.is_midi_match_valid("晴天", "onlinesequencer.net logo.mid") is False
    assert pe.is_midi_match_valid("晴天", "晴天.mid") is True


def test_playable_floor():
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        good = _write_mid(os.path.join(d, "good.mid"), notes=30, seconds=30.0)
        assert pe.is_midi_playable(good) is True
        tiny = _write_mid(os.path.join(d, "tiny.mid"), notes=2, seconds=0.4)
        assert pe.is_midi_playable(tiny) is False
        empty = os.path.join(d, "empty.mid")
        open(empty, "wb").write(b"junk")
        assert pe.is_midi_playable(empty) is False
        assert pe.is_midi_playable(os.path.join(d, "nope.mid")) is False
        assert pe.is_midi_playable("") is False


def test_queue_path_uses_the_same_checks_as_playing_now():
    """演奏中點歌走排隊那條路，舊碼直接拿曲庫別名，晴天排進 91 bytes 的 logo（2026-10-25 實機）。"""
    import inspect
    src = inspect.getsource(pe.play_virtual_piano)
    queue = src[src.index("exact_local = AUTHENTIC_MIDI_MAP.get(norm_k)"):src.index("PIANO_REQUEST_QUEUE.append(")]
    assert "is_midi_match_valid(clean_target_song, os.path.basename(exact_local))" in queue
    assert "is_midi_playable(req_midi)" in queue


def test_online_result_is_checked_against_the_song_not_the_search_words(monkeypatch):
    """搜尋字帶歌手（周杰倫 晴天 鋼琴 MIDI），拿它比對的話同歌手的夜曲也會過關（2026-10-25 實機）。"""
    seen = {}

    def fake_fetch(q, out_dir, validate=None):
        seen["q"] = q
        seen["ok"] = validate("周杰倫 Jay Chou - 夜曲 Nocturne (Instrumental)")
        seen["right"] = validate("周杰倫 晴天 Sunny Day piano")
        return None
    monkeypatch.setattr(pe.pianist_midi_engine, "fetch_and_download_pianist_match", fake_fetch)
    pe._fetch_validated_midi("周杰倫 晴天 鋼琴 MIDI", "晴天")
    assert seen == {"q": "周杰倫 晴天 鋼琴 MIDI", "ok": False, "right": True}
    src = __import__("inspect").getsource(pe.play_virtual_piano)
    assert "_fetch_validated_midi, song_str, c_song)" in src     # 排隊那條路有帶歌名
