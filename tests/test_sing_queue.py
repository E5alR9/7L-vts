# -*- coding: utf-8 -*-
"""翻唱排隊 request_cover_song：去重／上限／狀態訊息（同步邏輯，不碰 GPU/loop）。"""
from conftest import ROOT  # noqa: F401
import pytest
import services.auto_cover_pipeline as acp


@pytest.fixture(autouse=True)
def _clean_state():
    acp.SONG_REQUEST_QUEUE.clear()
    acp.READY_SONGS.clear()
    acp._ACTIVE_TITLES.clear()
    acp._PIPELINE_GEN = 0
    acp._ORCH_TASK = None
    acp._PREPARE_TASK = None
    acp.IS_SINGING_ACTIVE = False
    yield
    acp.SONG_REQUEST_QUEUE.clear()
    acp.READY_SONGS.clear()
    acp._ACTIVE_TITLES.clear()
    acp.IS_SINGING_ACTIVE = False


def test_idle_starts_immediately():
    msg = acp.request_cover_song("晴天", "老爸")
    assert "背景準備好就開唱" in msg
    assert "晴天" in msg
    assert len(acp.SONG_REQUEST_QUEUE) == 1  # 無 loop，orchestrator 未啟動，停在隊列


def test_duplicate_rejected_same_and_similar_title():
    acp.request_cover_song("不再曼波", "觀眾甲")
    assert "不重複排入" in acp.request_cover_song("不再曼波", "觀眾乙")
    assert "不重複排入" in acp.request_cover_song("不再曼波 ", "觀眾丙")
    # 同一快取檔名也算重複（否則第二首會播出第一首的音檔）
    assert "不重複排入" in acp.request_cover_song("不再曼波！", "觀眾丁")
    assert len(acp.SONG_REQUEST_QUEUE) == 1


def test_queue_position_message():
    acp.IS_SINGING_ACTIVE = True  # 假裝台上在唱
    try:
        m1 = acp.request_cover_song("歌A", "老爸")
        assert "下一首就輪到它" in m1
        m2 = acp.request_cover_song("歌B", "觀眾甲")
        assert "前面還有 1 首" in m2
    finally:
        acp.IS_SINGING_ACTIVE = False


def test_cap():
    acp.IS_SINGING_ACTIVE = True
    try:
        for i in range(acp.MAX_PENDING_SONGS):
            msg = acp.request_cover_song(f"歌{i}", "洗版仔")
            assert "排入點歌隊列" in msg or "背景準備好就開唱" in msg
        assert "隊列滿了" in acp.request_cover_song("再來一首", "洗版仔")
        assert len(acp.SONG_REQUEST_QUEUE) == acp.MAX_PENDING_SONGS
    finally:
        acp.IS_SINGING_ACTIVE = False


def test_empty_title_skipped():
    assert "空的" in acp.request_cover_song("   ", "老爸")
    assert len(acp.SONG_REQUEST_QUEUE) == 0


def test_stop_clears_queues_and_bumps_gen():
    acp.IS_SINGING_ACTIVE = True
    acp.request_cover_song("歌A", "老爸")
    acp.request_cover_song("歌B", "觀眾甲")
    gen0 = acp._PIPELINE_GEN
    acp.stop_singing()
    assert acp._PIPELINE_GEN == gen0 + 1
    assert len(acp.SONG_REQUEST_QUEUE) == 0
    assert len(acp.READY_SONGS) == 0
    assert len(acp._ACTIVE_TITLES) == 0
    assert acp.IS_SINGING_ACTIVE is False
