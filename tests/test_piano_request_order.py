# -*- coding: utf-8 -*-
"""點曲先後（2026-10-25 實機）：先點稻香（要等 AI 判斷、上網抓譜），再點小星星（本機就有、先開彈），
稻香判斷完開新場次，把正在彈的小星星取消掉，小星星連一行日誌都沒有。後點的已經開彈，先點的要排在後面。"""
import asyncio

import services.piano_engine as pe


def _setup(monkeypatch, delays):
    started, fetched = [], []
    monkeypatch.setattr(pe, "log_print", lambda *a, **k: None)
    monkeypatch.setattr(pe, "init_piano_synthesizer", lambda: None)
    monkeypatch.setattr(pe, "save_persisted_piano_state", lambda *a, **k: None)
    monkeypatch.setattr(pe, "is_piano_window_alive", lambda: False)    # 視窗還在開，偵測不到
    monkeypatch.setattr(pe, "bring_piano_window_to_front", lambda: None)
    monkeypatch.setattr(pe, "_remember", lambda *a: None)
    monkeypatch.setattr(pe, "_fetch_validated_midi", lambda q, title="": fetched.append(q))

    async def intent(q, files, **k):
        await asyncio.sleep(delays.get(q, 0))
        return {"_from_ai": True, "is_song_request": True, "action_type": "song_request", "song_title": q,
                "matched_files": [f for f in files if f == q + ".mid"]}
    monkeypatch.setattr(pe, "resolve_piano_intent_by_ai", intent)

    def start(title, midi, **k):
        started.append(title)
        pe.current_piano_song_title, pe.current_piano_midi_file, pe.is_piano_active = title, midi, True
        pe.current_piano_task = asyncio.get_running_loop().create_task(asyncio.sleep(30))
    monkeypatch.setattr(pe, "_start_piano_worker", start)
    pe.PIANO_REQUEST_QUEUE.clear()
    pe.PENDING_PIANO_PRELOADS.clear()
    pe.LAST_PLAY_REQUEST_TIME.clear()
    pe.GLOBAL_PIANO_REALTIME_STATE["is_playing"] = False
    pe.is_piano_active, pe.current_piano_song_title, pe.current_piano_task = False, "", None
    return started, fetched


def test_older_slow_request_queues_behind_the_newer_one(monkeypatch):
    started, fetched = _setup(monkeypatch, {"不存在的測試曲": 0.3})

    async def go():
        older = asyncio.create_task(pe.play_virtual_piano("不存在的測試曲", is_direct_song_name=True))
        await asyncio.sleep(0.05)
        await pe.play_virtual_piano("小星星", is_direct_song_name=True)
        r = await older
        await asyncio.sleep(0.05)
        pe.current_piano_task.cancel()
        return r
    r = asyncio.run(go())
    assert started == ["小星星"]                          # 小星星照彈，沒被先點的蓋掉
    assert pe.current_piano_song_title == "小星星"
    assert "排入下一首" in r and fetched == ["不存在的測試曲"]   # 先點的排在後面（本機沒有，背景抓譜後入隊）


def test_newer_song_started_while_the_older_one_was_still_looking_up_files(monkeypatch):
    """判斷完先後之後，先點的還會再查一次本機曲庫（又問一次 AI）；後點的在這段開彈，一樣不能被蓋掉（實機第二次重現）。"""
    started, fetched = _setup(monkeypatch, {})
    orig = pe.resolve_local_midi_file

    async def slow_lookup(q):
        if q == "不存在的測試曲":
            await asyncio.sleep(0.3)
            return None, ""
        return await orig(q)
    monkeypatch.setattr(pe, "resolve_local_midi_file", slow_lookup)

    async def go():
        older = asyncio.create_task(pe.play_virtual_piano("不存在的測試曲", is_direct_song_name=True))
        await asyncio.sleep(0.05)
        await pe.play_virtual_piano("小星星", is_direct_song_name=True)
        r = await older
        await asyncio.sleep(0.05)
        pe.current_piano_task.cancel()
        return r
    r = asyncio.run(go())
    assert started == ["小星星"] and pe.current_piano_song_title == "小星星"
    assert "排入下一首" in r and fetched == ["不存在的測試曲"]


def test_requests_in_order_still_play_right_away(monkeypatch):
    started, _ = _setup(monkeypatch, {})

    async def go():
        await pe.play_virtual_piano("小星星", is_direct_song_name=True)
        pe.current_piano_task.cancel()
    asyncio.run(go())
    assert started == ["小星星"]


def test_owner_stop_is_not_swallowed_by_the_just_opened_guard(monkeypatch):
    """主腦自己點曲剛拿出鋼琴，老爸說「收起鋼琴」被「3.5 秒內忽略」擋掉，主腦還說收好了（2026-10-25 實機）。"""
    import time
    monkeypatch.setattr(pe, "log_print", lambda *a, **k: None)
    monkeypatch.setattr(pe, "save_persisted_piano_state", lambda *a, **k: None)
    monkeypatch.setattr(pe, "is_piano_window_alive", lambda: False)
    monkeypatch.setattr(pe, "_remember", lambda *a: None)
    monkeypatch.setattr(pe.vc, "GLOBAL_VTS", None)
    monkeypatch.setattr(pe, "SOUND_ENGINE", None)
    monkeypatch.setattr(pe, "current_piano_process", None)
    monkeypatch.setattr(pe, "current_piano_task", None)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(pe, "_show_subtitle", _noop)
    pe.LAST_PIANO_OPEN_TIME = time.time()
    pe.is_piano_active = True
    assert asyncio.run(pe.stop_virtual_piano()) == "" and pe.is_piano_active      # 主腦轉述的：照舊擋
    assert "收起鋼琴" in asyncio.run(pe.stop_virtual_piano(force=True))           # 老爸親口說的：照收
    assert pe.is_piano_active is False


def test_cpu_owner_stop_is_sent_with_force():
    import os
    main = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vts_7L_test.py"),
                encoding="utf-8").read()
    assert 'await pe.stop_virtual_piano(force=bool(fn_args.get("force")))' in main
    assert 'if fn_name == "pe.stop_virtual_piano" and not from_brain:' in main


def test_piano_does_not_wait_on_a_missing_vts(monkeypatch):
    """VTS 關著，開彈前的走位卡在重連幾十秒，鋼琴視窗遲遲沒開、被看門狗收掉（2026-10-25 實機）。"""
    import inspect
    import time as _t
    monkeypatch.setattr(pe, "log_swallowed", lambda *a, **k: None)

    async def stuck(*a, **k):
        await asyncio.sleep(30)
    t0 = _t.time()
    assert asyncio.run(pe._vts_soon(stuck(), timeout=0.2)) is None
    assert _t.time() - t0 < 1.0
    for fn in (pe.play_piano_worker, pe.open_virtual_piano, pe.stop_virtual_piano):
        src = inspect.getsource(fn)
        assert "await move_vts_spatial(" not in src and "await set_vts_expression(" not in src, fn.__name__
