# -*- coding: utf-8 -*-
"""彈唱同步（2026-10-25）：彈唱同一首歌時，鋼琴改彈翻唱伴奏轉出來的譜，照共同起點跟人聲一起進。
網路上的 MIDI 速度、前奏長度都跟 YT 原曲不一樣，以前邊彈邊唱一定對不上。"""
import ast
import asyncio
import bisect
import os
import time
import types

import mido

from conftest import ROOT
import services.audio_to_score as ats
import services.auto_cover_pipeline as acp
import services.piano_engine as pe


# —— 伴奏轉譜 ——

def test_piano_midi_path_sits_next_to_instrumental():
    assert ats.piano_midi_path_for(os.path.join("c", "晴天_instrumental.wav")) == os.path.join("c", "晴天_piano.mid")
    assert ats.piano_midi_path_for("x.wav") == "x_piano.mid"


def test_arrange_for_piano_cleans_transcription():
    ev = [
        (0.00, 0.50, 60, 0.9),      # 正常
        (0.30, 0.90, 60, 0.5),      # 同音重疊：前一個在 0.30 收掉
        (1.00, 1.03, 64, 0.9),      # 太短：丟
        (1.00, 1.50, 15, 0.9),      # 鋼琴沒這個鍵：丟
    ]
    ev += [(2.0 + i * 0.002, 2.5, 48 + i, 0.1 * (i + 1)) for i in range(8)]   # 同一下 8 個音：留最大聲 6 個
    out = ats.arrange_for_piano(ev)
    assert (0.0, 0.3, 60, out[0][3]) == out[0]
    assert all(21 <= p <= 108 and d >= 0.08 for _, d, p, _ in out)
    chord = [p for s, _, p, _ in out if 1.99 <= s <= 2.02]
    assert sorted(chord) == [50, 51, 52, 53, 54, 55]
    assert all(40 <= v <= 105 for *_, v in out)
    assert ats.arrange_for_piano([]) == []


def test_write_piano_midi_two_hands_real_seconds(tmp_path):
    out = str(tmp_path / "s_piano.mid")
    ats.write_piano_midi([(1.0, 0.5, 72, 90), (1.0, 0.5, 48, 70), (2.25, 1.0, 48, 80)], out)
    mid = mido.MidiFile(out)
    assert [t.name for t in mid.tracks] == ["Right Hand", "Left Hand"]   # 鋼琴視窗靠軌名分左右手
    t, ons = 0.0, []
    for msg in mid:
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            ons.append((round(t, 3), msg.note))
    assert sorted(ons) == [(1.0, 48), (1.0, 72), (2.25, 48)]               # 譜上的秒數＝原曲的秒數
    assert not os.path.exists(out + ".tmp")


def test_instrumental_to_piano_midi_caches_and_degrades(tmp_path, monkeypatch):
    inst = str(tmp_path / "歌_instrumental.wav")
    open(inst, "wb").write(b"\0" * 100)
    monkeypatch.setattr(ats, "log_print", lambda *a, **k: None)

    def no_bp(path):
        raise ImportError("no basic-pitch")
    monkeypatch.setattr(ats, "_basic_pitch_note_events", no_bp)
    assert ats.instrumental_to_piano_midi(inst) == ""                      # 沒裝：回空，調用方退回曲名找譜

    monkeypatch.setattr(ats, "_basic_pitch_note_events",
                        lambda path: [(0.5, 1.0, 60, 0.8), (1.0, 2.0, 43, 0.6)])
    out = ats.instrumental_to_piano_midi(inst)
    assert out == str(tmp_path / "歌_piano.mid") and os.path.exists(out)

    def must_not_run(path):
        raise AssertionError("已轉過要直接用快取")
    monkeypatch.setattr(ats, "_basic_pitch_note_events", must_not_run)
    assert ats.instrumental_to_piano_midi(inst) == out
    assert ats.instrumental_to_piano_midi(str(tmp_path / "不存在_instrumental.wav")) == ""


# —— 鋼琴視窗：照時間點校時 ——

def _align_to_clock():
    src = open(os.path.join(ROOT, "test_virtual_piano.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "align_to_clock":
            ns = {"time": time, "bisect": bisect}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "x", "exec"), ns)
            return ns["align_to_clock"]
    raise AssertionError("鋼琴視窗沒有 align_to_clock")


class _Canvas:
    def __init__(self):
        self.deleted = []

    def delete(self, item):
        self.deleted.append(item)


def _window(song_time=-1.6, bars=()):
    times = [0.0, 0.5, 1.0, 2.0, 3.0, 4.0]
    track = {"events": [(t, 60, 0.3, 90) for t in times], "event_times": times, "event_idx": 0,
             "current_song_time": song_time, "paused_song_time": song_time}
    return types.SimpleNamespace(
        is_playing=True, active_tracks=[track], playback_events=track["events"], playback_event_times=times,
        playback_event_idx=0, current_song_time=song_time, paused_song_time=song_time, FALL_TIME=1.6,
        playback_speed=1.0, active_falling_bars=list(bars), canvas=_Canvas(), last_perf_time=None,
        playback_start_perf=0.0), track


def test_align_future_start_waits_with_negative_clock():
    align = _align_to_clock()
    w, track = _window()
    align(w, time.time() + 3.0)
    assert abs(w.current_song_time + 3.0) < 0.05 and abs(track["current_song_time"] + 3.0) < 0.05
    assert track["event_idx"] == 0                                         # 方塊之後照常提前落下


def test_align_late_start_skips_past_notes_without_burst():
    align = _align_to_clock()
    w, track = _window()
    align(w, time.time() - 2.5)                                            # 人聲已經唱了 2.5 秒
    assert abs(track["current_song_time"] - 2.5) < 0.05
    assert track["event_idx"] == 4 and w.playback_event_idx == 4          # 0~2 秒的音不補彈


def test_align_forward_resync_drops_unplayed_bars_only():
    align = _align_to_clock()
    bars = [{"id": "played", "hit_time": 0.9, "played": True},
            {"id": "missed", "hit_time": 1.2, "played": False},
            {"id": "ahead", "hit_time": 2.0, "played": False}]
    w, track = _window(song_time=1.0, bars=bars)
    align(w, time.time() - 1.5)                                            # 鋼琴慢了 0.5 秒
    assert w.canvas.deleted == ["missed"]
    assert [b["id"] for b in w.active_falling_bars] == ["played", "ahead"]
    assert abs(w.current_song_time - 1.5) < 0.05


def test_align_small_or_backward_only_moves_clock():
    align = _align_to_clock()
    bars = [{"id": "soon", "hit_time": 1.03, "played": False}]
    w, _ = _window(song_time=1.0, bars=bars)
    align(w, time.time() - 1.05)                                           # 只差 0.05 秒：照彈不丟
    assert w.canvas.deleted == [] and len(w.active_falling_bars) == 1
    w, track = _window(song_time=2.0, bars=bars)
    align(w, time.time() - 1.0)                                            # 鋼琴快了：撥回去
    assert abs(track["current_song_time"] - 1.0) < 0.05 and w.canvas.deleted == []


def test_align_ignored_when_not_playing():
    align = _align_to_clock()
    w, _ = _window(song_time=0.7)
    w.is_playing = False
    align(w, time.time() - 30)
    assert w.current_song_time == 0.7


def test_piano_window_handles_sync_ipc():
    src = open(os.path.join(ROOT, "test_virtual_piano.py"), encoding="utf-8").read()
    assert 'elif cmd == "sync":' in src and 'cmd_obj.get("start_at")' in src


# —— 鋼琴引擎：同步開彈＋校時 ——

def test_sync_piano_clock_only_for_the_synced_score(monkeypatch):
    sent = []
    monkeypatch.setattr(pe, "send_piano_ipc_command", lambda cmd: sent.append(cmd) or True)
    monkeypatch.setattr(pe, "is_piano_active", True)
    monkeypatch.setattr(pe, "current_piano_midi_file", os.path.join("c", "晴天_piano.mid"))
    assert pe.sync_piano_clock(123.0, os.path.join("c", "晴天_piano.mid"))
    assert sent == [{"cmd": "sync", "start_at": 123.0}]
    assert not pe.sync_piano_clock(124.0, os.path.join("c", "別首_piano.mid"))   # 台上換了別首：不動它
    assert len(sent) == 1


def test_start_piano_worker_passes_start_time(monkeypatch):
    got = {}

    async def fake_worker(**kw):
        got.update(kw)
    monkeypatch.setattr(pe, "play_piano_worker", fake_worker)
    monkeypatch.setattr(pe, "current_piano_task", None)

    async def run():
        pe._start_piano_worker("晴天", "x_piano.mid", start_at=55.0)
        await pe.current_piano_task
    asyncio.run(run())
    assert got["midi_file"] == "x_piano.mid" and got["start_at"] == 55.0
    assert got["session_id"] == pe.PIANO_SESSION_ID and pe.current_piano_midi_file == "x_piano.mid"


# —— 兩邊會合：鋼琴側（主檔 _mixed_piano_run）＋翻唱側（_mixed_rendezvous_sing）——

def _mixed_piano_run(fake_pe):
    src = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    for n in ast.parse(src).body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_mixed_piano_run":
            ns = {"asyncio": asyncio, "log_print": lambda *a, **k: None, "pe": fake_pe,
                  "MIXED_PIANO_WAIT_SEC": 30.0}
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            return ns["_mixed_piano_run"]
    raise AssertionError("主檔沒有 _mixed_piano_run")


def _fake_pe():
    calls = []
    fake = types.SimpleNamespace(calls=calls)

    async def noop():
        return ""

    async def ready(timeout=25.0):
        return True

    async def resolve(title):
        calls.append(("resolve", title))
        return "online.mid", title

    async def synced(title, midi, start_at):
        calls.append(("synced", title, midi, start_at))

    async def by_title(title, midi_file="", **kw):
        calls.append(("by_title", title, midi_file))
    fake.open_virtual_piano, fake.wait_piano_subprocess_ready = noop, ready
    fake.resolve_local_midi_file, fake.play_synced_midi, fake.play_virtual_piano = resolve, synced, by_title
    return fake


def _run_mixed(monkeypatch, piano_title, sing_title, midi_result):
    monkeypatch.setattr(acp, "is_song_active", lambda t: True)
    converted = []

    def fake_convert(inst_path):
        converted.append(inst_path)
        return midi_result
    monkeypatch.setattr(ats, "instrumental_to_piano_midi", fake_convert)
    fake = _fake_pe()
    run = _mixed_piano_run(fake)

    async def scenario():
        piano = asyncio.create_task(run(piano_title, sing_title, "dad", "老爸"))
        for _ in range(50):                                                # 等鋼琴側舉旗
            await asyncio.sleep(0)
        rv = acp._MIXED_RENDEZVOUS.pop(acp._dedupe_key(sing_title))
        start_at = await acp._mixed_rendezvous_sing(rv, sing_title, "x_instrumental.wav")
        await asyncio.wait_for(piano, 5)
        return rv, start_at
    rv, start_at = asyncio.run(scenario())
    return fake.calls, converted, rv, start_at


def test_mixed_same_song_plays_synced_score(monkeypatch):
    t0 = time.time()
    calls, converted, rv, start_at = _run_mixed(monkeypatch, "晴天", "晴天", "x_piano.mid")
    assert rv["want_sync"] and converted == ["x_instrumental.wav"]
    assert start_at and abs(start_at - (t0 + acp._MIXED_LEAD_SEC)) < 1.0
    assert calls == [("synced", "晴天", "x_piano.mid", start_at)]          # 不再用曲名找網路譜


def test_mixed_different_song_keeps_title_lookup(monkeypatch):
    calls, converted, rv, start_at = _run_mixed(monkeypatch, "月光", "晴天", "x_piano.mid")
    assert not rv["want_sync"] and converted == [] and start_at is None
    assert calls == [("resolve", "月光"), ("by_title", "月光", "online.mid")]


def test_mixed_conversion_failure_falls_back(monkeypatch):
    calls, converted, rv, start_at = _run_mixed(monkeypatch, "晴天", "晴天", "")
    assert converted and start_at is None and rv["piano_gave_up"]
    assert calls == [("resolve", "晴天"), ("by_title", "晴天", "online.mid")]


def test_play_prepared_song_hands_start_time_to_playback(monkeypatch):
    got = {}

    async def fake_play(vocal_path, title, inst_path=None, start_at=None, on_start=None):
        got.update(start_at=start_at, on_start=on_start)
    monkeypatch.setattr(acp, "play_cover_audio", fake_play)
    monkeypatch.setattr(acp, "_send_brain_slip", lambda text: True)
    monkeypatch.setattr(acp, "_HOST", {})
    monkeypatch.setattr(ats, "instrumental_to_piano_midi", lambda p: "y_piano.mid")
    synced = []
    monkeypatch.setattr(pe, "sync_piano_clock", lambda t, midi: synced.append((t, midi)))
    rv = acp.arm_mixed_rendezvous("單元測試彈唱歌", want_sync=True)
    rv["piano"].set()
    asyncio.run(acp.play_prepared_song("單元測試彈唱歌", "v.wav", "y_instrumental.wav", acp._PIPELINE_GEN))
    assert got["start_at"] and rv["start_at"] == got["start_at"] and rv["sing"].is_set()
    got["on_start"](777.0)                                                 # 人聲實際開播 → 鋼琴照它校時
    assert synced == [(777.0, "y_piano.mid")]


def test_sync_speed_does_not_overwrite_dads_speed_setting():
    """彈唱那首倍速固定 1.0，視窗心跳回報 1.0 以前會蓋掉老爸設的 1.2，之後每首都 1 倍（2026-10-31 Fable 看實機日誌）。"""
    src = open(os.path.join(ROOT, "services", "piano_engine.py"), encoding="utf-8").read()
    assert 'if "speed" in pkg and not _SPEED_FORCED_FOR_SYNC and time.time() >= _SPEED_RESTORE_UNTIL:' in src
    assert '_SPEED_FORCED_FOR_SYNC = "pending" if sync_at and play_speed != GLOBAL_PIANO_SPEED else False' in src
    # 視窗收到 play 先廣播 speed_changed（還沒在彈）：要看過「在彈」才算開始，停了才算彈完（Fable 審查）
    assert 'if is_playing and _SPEED_FORCED_FOR_SYNC == "pending":' in src
    hb = src[src.index("elif not is_playing:"):]
    hb = hb[:hb.index('if "volume" in pkg')]
    assert 'if _SPEED_FORCED_FOR_SYNC == "playing":' in hb
    assert '"set_speed", "speed": GLOBAL_PIANO_SPEED' in hb           # 彈完那首：視窗改回老爸的倍速
    old_spd, old_flag = pe.GLOBAL_PIANO_SPEED, pe._SPEED_FORCED_FOR_SYNC
    try:
        pe._SPEED_FORCED_FOR_SYNC = True
        asyncio.run(pe.set_piano_speed(1.3))                            # 彈唱中老爸自己改：照他的
        assert pe.GLOBAL_PIANO_SPEED == 1.3 and pe._SPEED_FORCED_FOR_SYNC is False
    finally:
        pe.GLOBAL_PIANO_SPEED, pe._SPEED_FORCED_FOR_SYNC = old_spd, old_flag
