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
