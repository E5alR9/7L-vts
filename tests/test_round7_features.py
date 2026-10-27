# -*- coding: utf-8 -*-
"""功能清單第二輪（2026-10-27 老爸逐項回覆）：自主醒來、自主彈琴、獎懲、光喊 7L、答應她的點歌提議。"""
import ast
import asyncio
import time

from conftest import MAIN_SRC as MAIN, main_def, load_main
from core.hard_command import offer_accept_command
from dryrun import DryRun


# ── 自主醒來：老爸離開過、又回來操作才醒 ──
def _wake_ns():
    return load_main("_should_wake_from_screen", SCREEN_WAKE_AWAY_SEC=180.0, SCREEN_WAKE_INPUT_SEC=10.0,
                     _SLEEP_WAKE={"away_seen": False})


def test_busy_at_the_pc_when_told_to_sleep_does_not_wake_her():
    ns = _wake_ns()
    st = {"away_seen": False}
    # 老爸叫她去睡、自己繼續用電腦：滑鼠一直在動、畫面一直在變
    assert not any(ns["_should_wake_from_screen"](2.0, "high", st) for _ in range(20))


def test_dad_comes_back_after_leaving_wakes_her():
    ns = _wake_ns()
    st = {"away_seen": False}
    assert ns["_should_wake_from_screen"](600.0, "none", st) is False   # 離開了
    assert ns["_should_wake_from_screen"](3.0, "low", st) is False      # 碰一下滑鼠、畫面沒變
    assert ns["_should_wake_from_screen"](3.0, "med", st) is True       # 回來操作


def test_unknown_input_idle_never_wakes():
    ns = _wake_ns()
    assert ns["_should_wake_from_screen"](None, "high", {"away_seen": True}) is False


def test_sleeping_still_samples_screen_change():
    src = ast.get_source_segment(MAIN, main_def("screen_capture_worker"))
    assert "_sleep_screen_probe" in src
    probe = ast.get_source_segment(MAIN, main_def("_sleep_screen_probe"))
    assert "grab_screen" in probe and "latest_screen_cache" not in probe and "LATEST_HD_SCREEN_BYTES" not in probe


def test_falling_asleep_resets_away_flag():
    assert '_SLEEP_WAKE["away_seen"] = False' in ast.get_source_segment(MAIN, main_def("set_sleep_mode"))


# ── 自主彈琴：只看自己的開關、直接給 MIDI ──
def test_auto_piano_not_gated_by_wander_switch():
    src = ast.get_source_segment(MAIN, main_def("autonomous_wander_worker"))
    piano = src.index("IS_AUTO_PIANO_ENABLED and")
    outer = src.rfind("if ", 0, piano)
    outer = src.rfind("if ", 0, outer)
    assert "IS_AUTO_WANDER_ENABLED" not in src[outer:piano]
    assert "midi_file=" in src and "is_direct_song_name=True" in src
    assert "IS_AUTO_WANDER_ENABLED and now - LAST_WANDER_TIME" in src


# ── 獎懲：睡著先醒、記進對話記憶 ──
def test_reward_and_punish_wake_her_and_record_memory():
    for name in ("execute_punish_action", "execute_reward_action"):
        src = ast.get_source_segment(MAIN, main_def(name))
        assert "_wake_for_dad_touch(" in src and "_record_dad_touch(" in src and "record_bot_message(" not in src, name


def test_wake_for_dad_touch():
    calls = []

    async def set_sleep_mode(v):
        calls.append(v)
    ns = load_main("_wake_for_dad_touch", IS_SLEEPING=True, set_sleep_mode=set_sleep_mode)
    asyncio.run(ns["_wake_for_dad_touch"]("電擊"))
    ns["IS_SLEEPING"] = False
    asyncio.run(ns["_wake_for_dad_touch"]("獎勵"))
    assert calls == [False]


# ── 光喊 7L：一律不交哨兵審 ──
def test_bare_ping_during_cooldown_tells_brain_quietly():
    seen = []

    async def sentry(*a):
        seen.append(a)
        return {"should_speak": False, "target": "", "focus": "", "raw": "[PASS]"}

    async def go():
        async with DryRun(live=True) as d:
            d.ns["_PING_LAST_TS"]["小明"] = time.time()          # 剛應過他（看板用顯示名當 key）
            d.ns["judge_should_speak"] = sentry
            await d.viewer("小明", "7L", uid="xiaoming01")
            await d.settle(3.0)
            q = d.ns["LIVE_SILENT_CONTEXT_QUEUE"]
            return list(q._queue), d
    quiet, d = asyncio.run(go())
    assert seen == []
    assert any("小明" in x and "喊了妳" in x for x in quiet)


# ── 她提議、對方答應 ──
def test_offer_accept_parses_her_offer():
    assert offer_accept_command("要", "要不要我唱《晴天》給你聽？") == [("auto_sing_song", {"song_name": "晴天"})]
    assert offer_accept_command("好啊！", "要不要聽我彈月光呢？") == [("pe.play_virtual_piano", {"song_name": "月光"})]
    assert offer_accept_command("好的", "那我唱一首稻香給大家聽好不好") == [("auto_sing_song", {"song_name": "稻香"})]


def test_offer_accept_rejects_non_answers():
    assert offer_accept_command("不要", "要不要我唱晴天？") == []
    assert offer_accept_command("不用了", "要不要我唱晴天？") == []
    assert offer_accept_command("今天好累", "要不要我唱晴天？") == []        # 有「好」不算答應
    assert offer_accept_command("要", "我剛唱完晴天！") == []                 # 她沒在問
    assert offer_accept_command("要", "我可以彈月光，也可以唱晴天，你要哪個？") == []   # 讓人挑
    assert offer_accept_command("可以啊", "要不要我唱首歌給你聽？") == []       # 沒說哪首


def test_dad_typing_yes_schedules_her_offered_song(monkeypatch):
    import core.memory as mem
    monkeypatch.setattr(mem, "UNIFIED_DIALOGUE_MEMORY",
                        __import__("collections").deque([{"time": time.time() - 5, "role": "assistant",
                                                          "content": "要不要我唱《晴天》給你聽？"}]))

    async def go():
        async with DryRun(live=True) as d:
            await d.dad("要")
            await d.settle(1.0)
            return d
    d = asyncio.run(go())
    assert ("auto_sing_song", {"song_name": "晴天"}) in [(t, a) for t, a, *_ in d.tools] and d.problems == []


def test_viewer_yes_only_counts_for_the_viewer_she_asked():
    o = {"who": "dad", "ts": 0.0, "said": "", "human": True, "name": ""}
    ns = load_main("_offer_accept_cmds", "_her_words_before", _BRAIN_INPUT_ORIGIN=o, re=__import__("re"),
                   time=time, offer_accept_command=offer_accept_command, log_swallowed=lambda: None)
    assert ns["_offer_accept_cmds"]("要", "audience", "路人") == []
    o.update(who="audience", name="小明")
    assert ns["_offer_accept_cmds"]("要", "audience", "路人 (@luren)") == []


def test_dedupe_treats_bracketed_song_as_same():
    src = ast.get_source_segment(MAIN, main_def("_hard_cmd_seen_recently"))
    assert "《》" in src and "casefold" in src


def test_offer_with_measure_word_and_tags():
    # 實機 2026-10-27：她說「要不要聽我唱首《晴天》呢？」，以前抽成「首《晴天」拿去 YouTube 下載
    her = "[EXPRESSION: 期待] 老爸老爸，等一下想聽我唱歌嗎？[EXPRESSION: 眨眼] 那... 要不要聽我唱首《晴天》呢？"
    assert offer_accept_command("要", her) == [("auto_sing_song", {"song_name": "晴天"})]
    from core.hard_command import extract_sing_song, extract_piano_song
    assert extract_sing_song("唱首《晴天》") == "《晴天》" and extract_piano_song("彈首《卡農》") == "《卡農》"
    assert extract_sing_song("唱首爾的歌") == "首爾的歌"   # 首後面不是書名號不剝


# ── 本機有沒有這首：歌名＋檔案清單交給 AI 挑（老爸 2026-10-27）──
def _fake_groq(answer, calls):
    async def groq_chat(messages, **k):
        calls.append(messages[0]["content"])
        import types
        return None if answer is None else types.SimpleNamespace(text=answer)
    return groq_chat


def test_cover_ai_match_picks_listed_cache_or_none(tmp_path, monkeypatch):
    import core.groq_router as gr
    import services.auto_cover_pipeline as ac
    for n in ("晴天_7l_vocal.wav", "Shape_of_You_vocals.wav", "orig_自創_7l_vocal.wav", "temp_dl_x_raw.wav"):
        (tmp_path / n).write_bytes(b"x")
    monkeypatch.setattr(ac, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ac, "_AI_CACHE_MATCH", {})
    assert ac.cached_song_names() == ["Shape_of_You", "晴天"]
    calls = []
    monkeypatch.setattr(gr, "groq_chat", _fake_groq("晴天", calls))
    assert asyncio.run(ac.ai_match_cached_song("周杰倫的晴天")) == "晴天"
    assert "周杰倫的晴天" in calls[0] and "Shape_of_You" in calls[0]
    asyncio.run(ac.ai_match_cached_song("周杰倫的晴天"))
    assert len(calls) == 1                                   # 同一個歌名這次開機不重問
    monkeypatch.setattr(gr, "groq_chat", _fake_groq("七里香", calls))
    assert asyncio.run(ac.ai_match_cached_song("七里香")) == ""   # 清單外的字當沒有
    monkeypatch.setattr(gr, "groq_chat", _fake_groq(None, calls))
    assert asyncio.run(ac.ai_match_cached_song("稻香")) == "" and "稻香" not in ac._AI_CACHE_MATCH   # AI 掛了不記


def test_prepare_cover_asks_ai_only_when_title_not_exact():
    import inspect
    import services.auto_cover_pipeline as ac
    src = inspect.getsource(ac.prepare_cover_song)
    assert "if not _tag and not _has_cache(safe_name):" in src and "ai_match_cached_song(" in src


def test_midi_ai_pick_trusted_when_in_list():
    from services.piano_engine import _ai_pick_in_list, is_midi_match_valid
    files = ["Beethoven Moonlight Sonata.mid", "小星星.mid"]
    assert not is_midi_match_valid("月光奏鳴曲", files[0])     # 字串比對擋跨語言，所以 AI 挑的不再過它
    assert _ai_pick_in_list("beethoven moonlight sonata.mid", files)
    assert not _ai_pick_in_list("Clair de Lune.mid", files) and not _ai_pick_in_list("", files)


# ── 實機歌名測試抓到的（2026-10-27）──
def test_stop_after_another_song_is_not_a_duplicate():
    from core import eventlog
    from core.hard_command import is_stage_control
    log = eventlog.EventLog(":memory:")
    ns = load_main("_hard_cmd_seen_recently", eventlog=type("E", (), {"get": staticmethod(lambda: log)}),
                   is_stage_control=is_stage_control, _HARD_CMD_DEDUPE_SEC=20.0)
    seen = ns["_hard_cmd_seen_recently"]
    t = time.time()
    assert seen("pe.stop_virtual_piano", {}, t) is False
    assert seen("pe.stop_virtual_piano", {}, t + 1) is True            # 主腦又叫一次收琴：重複
    assert seen("pe.play_virtual_piano", {"song_name": "夜曲"}, t + 5) is False
    assert seen("pe.stop_virtual_piano", {}, t + 8) is False           # 中間點過歌：要收
    assert seen("stop_singing", {}, t + 9) is False
    assert seen("auto_sing_song", {"song_name": "晴天"}, t + 10) is False
    assert seen("stop_singing", {}, t + 12) is False


def test_cover_alias_makes_brain_retitle_a_duplicate(monkeypatch):
    import services.auto_cover_pipeline as ac
    monkeypatch.setattr(ac, "_TITLE_ALIAS", {})
    monkeypatch.setattr(ac, "_ACTIVE_TITLES", {ac._dedupe_key("周杰倫的晴天")})
    monkeypatch.setattr(ac, "_REQUESTED_AT", {ac._dedupe_key("周杰倫的晴天"): 1.0})
    ac._note_title_alias("周杰倫的晴天", "晴天")
    assert ac.is_song_active("晴天") and ac.is_song_active("周杰倫的晴天")
    assert ac._REQUESTED_AT == {"晴天": 1.0}
    monkeypatch.setattr(ac, "READY_SONGS", ac.deque([{"title": "晴天"}]))
    assert ac._same_song_queued("周杰倫的晴天")


def test_first_playable_ai_pick(monkeypatch):
    import services.piano_engine as pe
    monkeypatch.setattr(pe, "is_midi_playable", lambda p: "redone" in p)
    files = ["Beethoven Moonlight Sonata.mid", "Moonlight (redone).mid", "小星星.mid"]
    got = pe._first_playable_pick(["Beethoven Moonlight Sonata.mid", "Moonlight (redone).mid"], files)
    assert got.endswith("Moonlight (redone).mid")
    assert pe._first_playable_pick(["不在清單.mid"], files) is None


def test_same_midi_not_restarted_right_after_start():
    import inspect
    import services.piano_engine as pe
    src = inspect.getsource(pe.play_virtual_piano)
    assert "SAME_FILE_REPEAT_SEC" in src and "_LAST_WORKER_START" in inspect.getsource(pe._start_piano_worker)


def test_midi_fetch_no_longer_falls_back_to_youtube_transcription(tmp_path, monkeypatch):
    import services.pianist_midi_engine as pm
    monkeypatch.setattr(pm.onlinesequencer_engine, "fetch_and_download_first_match", lambda *a, **k: None)
    monkeypatch.setattr(pm.bitmidi_engine, "fetch_and_download_first_match", lambda *a, **k: None)

    def boom(*a, **k):
        raise AssertionError("不能自動拿 YouTube 音訊轉譜")
    monkeypatch.setattr(pm, "search_youtube_and_download_midi", boom)
    assert pm.fetch_and_download_pianist_match("Mythology 神話", str(tmp_path)) is None   # 曲名有 yt 也不算指定 YouTube


def test_watchdog_does_not_resend_slip_after_newer_speech():
    ns = load_main("_slip_superseded", "_unpack_slip", _LAST_HUMAN_SLIP_TS={})
    t = time.time()
    slip = ("[黑板同步] E5傳來文字訊息：彈周杰倫的夜曲", "dad", "彈周杰倫的夜曲", "")
    assert ns["_slip_superseded"](slip, t) is False
    ns["_LAST_HUMAN_SLIP_TS"][("dad", "")] = t + 10        # 老爸後來說了「收起鋼琴」
    assert ns["_slip_superseded"](slip, t) is True
    assert ns["_slip_superseded"]("[系統提示：…]", t) is False        # 系統紙條照舊撿回
    assert ns["_slip_superseded"](("…", "audience", "唱晴天", "小明"), t) is False   # 別人講話不算


def test_rescue_skips_song_already_dispatched():
    from core import eventlog
    log = eventlog.EventLog(":memory:")
    ns = load_main("_song_dispatched_since", eventlog=type("E", (), {"get": staticmethod(lambda: log)}),
                   log_swallowed=lambda: None)
    t = time.time()
    log.record("stage_cmd", 'auto_sing_song|{"song_name": "payphone"}', ts=t + 1)
    assert ns["_song_dispatched_since"]("Payphone", t) is True
    assert ns["_song_dispatched_since"]("晴天", t) is False
    assert ns["_song_dispatched_since"]("payphone", t + 5) is False


def test_cover_dedupe_by_vocal_file(monkeypatch):
    import services.auto_cover_pipeline as ac
    monkeypatch.setattr(ac, "_TITLE_ALIAS", {})
    monkeypatch.setattr(ac, "READY_SONGS", ac.deque())
    monkeypatch.setattr(ac, "_STAGED_VOCAL", {"path": "C:/x/Faded_7l_vocal.wav"})
    monkeypatch.setattr(ac, "_NOW_PLAYING_TITLE", "")
    assert ac._same_song_queued("Alan Walker - faded", "C:/x/Faded_7l_vocal.wav")   # 正要上台的同一個檔
    assert not ac._same_song_queued("晴天", "C:/x/晴天_7l_vocal.wav")
