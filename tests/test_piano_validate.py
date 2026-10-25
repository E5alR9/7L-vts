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


def test_composed_piece_is_long_enough_to_play(monkeypatch, tmp_path):
    """作曲寫死已下架的 gemini-2.5-flash，掉進 5 秒的保底旋律，被可播性下限擋掉後
    拿「7L原創_xxx」上網搜，抓了不相干的 YouTube 影片來彈（2026-10-25 實機）。"""
    import asyncio, inspect
    played = {}

    async def fake_play(song_name="", midi_file="", **k):
        played["midi"] = midi_file
        return "[EXPRESSION: 星星眼]"
    import core.groq_router as gr

    async def no_groq(*a, **k):
        return None
    monkeypatch.setattr(gr, "groq_chat", no_groq)
    monkeypatch.setattr(pe, "get_piano_gemini_keys", lambda: [])          # 走保底旋律
    monkeypatch.setattr(pe, "MIDI_SHEETS_DIR", str(tmp_path))
    monkeypatch.setattr(pe, "save_midi_catalog_entry", lambda *a: None)
    monkeypatch.setattr(pe, "play_virtual_piano", fake_play)
    monkeypatch.setattr(pe, "log_print", lambda *a, **k: None)
    asyncio.run(pe.compose_and_play_original_piano("開心的小日子", "輕快"))
    assert played["midi"] and pe.is_midi_playable(played["midi"])
    assert '"gemini-2.5-flash"' not in inspect.getsource(pe.compose_and_play_original_piano)


def test_given_midi_that_is_too_short_is_not_searched_online(monkeypatch, tmp_path):
    import asyncio
    short = _write_mid(str(tmp_path / "7L原創_太短.mid"), notes=4, seconds=2.0)
    for name in ("init_piano_synthesizer", "save_persisted_piano_state"):
        monkeypatch.setattr(pe, name, lambda *a, **k: None)
    monkeypatch.setattr(pe, "log_print", lambda *a, **k: None)
    monkeypatch.setattr(pe, "_fetch_validated_midi", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該上網搜")))
    r = asyncio.run(pe.play_virtual_piano("7L原創_太短", midi_file=short))
    assert "沒辦法彈" in r


def test_composer_uses_ai_notes_when_groq_answers(monkeypatch, tmp_path):
    import asyncio, json as _j
    import core.groq_router as gr
    played = {}
    score = {"title": "午後", "bpm": 120,
             "notes": [{"pitch": 60 + (i % 12), "start_beat": i * 0.5, "duration_beats": 0.5, "velocity": 80}
                       for i in range(48)]}

    class _R:
        text = "好的：\n" + _j.dumps(score, ensure_ascii=False)

    async def fake_groq(*a, **k):
        return _R()

    async def fake_play(song_name="", midi_file="", **k):
        played.update(title=song_name, midi=midi_file)
        return ""
    monkeypatch.setattr(gr, "groq_chat", fake_groq)
    monkeypatch.setattr(pe, "get_piano_gemini_keys", lambda: [])
    monkeypatch.setattr(pe, "MIDI_SHEETS_DIR", str(tmp_path))
    monkeypatch.setattr(pe, "save_midi_catalog_entry", lambda *a: None)
    monkeypatch.setattr(pe, "play_virtual_piano", fake_play)
    logs = []
    monkeypatch.setattr(pe, "log_print", lambda m, *a, **k: logs.append(m))
    asyncio.run(pe.compose_and_play_original_piano("午後", "輕快"))
    assert played["title"] == "7L原創_午後" and pe.is_midi_playable(played["midi"])
    assert not any("保底" in m for m in logs)


def test_piano_intent_gives_up_within_budget(monkeypatch):
    """Groq 沒回、Gemini 一直逾時：舊碼模型 × 3 把金鑰 × 4 秒，最壞 84 秒才有反應（2026-10-25 健檢）。"""
    import asyncio, time as _t
    import core.groq_router as gr

    async def no_groq(*a, **k):
        return None

    class _Slow:
        def __init__(self, api_key=""):
            self.aio = self
            self.models = self

        async def generate_content(self, **k):
            await asyncio.sleep(5)
    logs = []
    monkeypatch.setattr(gr, "groq_chat", no_groq)
    monkeypatch.setattr(pe, "get_piano_gemini_keys", lambda: ["k1", "k2", "k3"])
    monkeypatch.setattr(pe.genai, "Client", _Slow)
    monkeypatch.setattr(pe, "PIANO_INTENT_GEMINI_BUDGET_SEC", 0.8)
    monkeypatch.setattr(pe, "log_print", lambda m, *a, **k: logs.append(m))
    t0 = _t.time()
    r = asyncio.run(pe.resolve_piano_intent_by_ai("小星星", ["小星星.mid"]))
    assert _t.time() - t0 < 2.0 and r.get("_from_ai") is False
    assert any("照曲名直接找" in m for m in logs)
