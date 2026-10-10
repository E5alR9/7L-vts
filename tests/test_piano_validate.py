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
