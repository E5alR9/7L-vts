# -*- coding: utf-8 -*-
"""MIDI 編輯器純函式測試（讀譜→改譜→回讀驗證）"""
import mido
from conftest import ROOT  # noqa: F401
from services import midi_editor as me


def _make(path, notes=(60, 64, 67)):
    mid = mido.MidiFile(ticks_per_beat=480)
    t = mido.MidiTrack()
    t.append(mido.MetaMessage("track_name", name="test", time=0))
    t.append(mido.Message("program_change", program=0, channel=0, time=0))
    tick = 0
    for n in notes:
        t.append(mido.Message("note_on", note=n, velocity=80, channel=0, time=tick))
        t.append(mido.Message("note_off", note=n, velocity=0, channel=0, time=240))
        tick = 240
    mid.tracks.append(t)
    mid.save(path)
    return path


def test_inspect(tmp_path):
    p = _make(str(tmp_path / "a.mid"))
    r = me.inspect_midi(p)
    assert r["ok"] and r["notes"] == 3 and r["tracks"] == 1
    assert me.inspect_midi(str(tmp_path / "no.mid"))["ok"] is False


def test_transpose_and_velocity(tmp_path, monkeypatch):
    monkeypatch.setattr(me, "SHEETS_DIR", str(tmp_path))
    p = _make(str(tmp_path / "b.mid"))
    r = me.transpose(p, 2, out_name="b_t")
    assert r["ok"] and r["changed"] == 6
    r2 = me.inspect_midi(r["file"])
    assert r2["detail"][0]["pitch_lo"] == 62
    r3 = me.set_velocity(r["file"], 0.5, out_name="b_v")
    assert r3["ok"]
    mid = mido.MidiFile(r3["file"])
    vels = [m.velocity for t in mid.tracks for m in t if m.type == "note_on" and m.velocity > 0]
    assert all(v == 40 for v in vels)


def test_quantize_add_del(tmp_path, monkeypatch):
    monkeypatch.setattr(me, "SHEETS_DIR", str(tmp_path))
    p = _make(str(tmp_path / "c.mid"))
    r = me.quantize(p, "16", out_name="c_q")
    assert r["ok"]
    r2 = me.add_notes(r["file"], [{"pitch": 72, "start_beat": 4.0, "duration_beats": 1.0,
                                   "velocity": 90, "channel": 1}], out_name="c_a")
    assert r2["ok"]
    r3 = me.inspect_midi(r2["file"])
    assert r3["notes"] == 4 and r3["tracks"] == 2
    r4 = me.delete_pitch_range(r2["file"], 70, 80, out_name="c_d")
    assert r4["ok"] and r4["changed"] == 2
    assert me.set_program(p, 9, 40)["ok"] is False
    r5 = me.set_program(p, 0, 40, out_name="c_p")
    assert r5["ok"]
