# -*- coding: utf-8 -*-
"""YT 伴看的畫面不再串流：每秒存著，記錄時這段的 3 張跟問題同一則訊息、高解析度送
（老爸 2026-11-01：用 Live 看圖的地方，有用低解析度串流的都改成高解析度同一則訊息送）。"""
import inspect

import services.yt_companion_service as yt


def test_picks_about_12_6_0_seconds_ago_old_to_new():
    now = 1000.0
    frames = [(now - s, f"f{s}".encode()) for s in range(19, -1, -1)]   # 20 秒每秒一張
    assert yt.pick_note_frames(frames, now) == [b"f12", b"f6", b"f0"]


def test_few_frames_do_not_repeat():
    now = 1000.0
    assert yt.pick_note_frames([(now - 1, b"a")], now) == [b"a"]                    # 剛開始只有一張：送一張
    assert yt.pick_note_frames([(now - 3, b"a"), (now, b"b")], now) == [b"a", b"b"]
    assert yt.pick_note_frames([], now) == []


def test_old_frames_are_never_sent_as_just_now():
    """截圖一直失敗時，存著的是一分鐘前的畫面：不能拿來說是「剛剛十幾秒」（Fable 2026-11-01）。"""
    now = 1000.0
    stale = [(now - 60 - s, b"old") for s in range(20)]
    assert yt.pick_note_frames(stale, now) == []
    assert yt.pick_note_frames(stale + [(now - 2, b"new")], now) == [b"new"]


def test_frames_go_with_the_question_not_as_a_stream():
    src = inspect.getsource(yt._yt_companion_session_loop)
    assert "video=types.Blob" not in src                                  # 畫面不再串流
    assert "send_client_content" in src and "NOTE_PROMPT" in src and "pick_note_frames" in src
    assert "MEDIA_RESOLUTION_HIGH" in src
    assert "audio=types.Blob" in src                                      # 聲音照樣一直串流
    assert "NO_INTERRUPTION" in src                                       # 影片裡有人講話不打斷筆記
    assert "if shots and" in src                                          # 沒畫面不問（不然會編畫面）
    assert "is_note" in src                                               # 只收有附畫面那一輪的回答
    assert "asyncio.to_thread(_grab" in src                               # 截圖不卡主迴圈
