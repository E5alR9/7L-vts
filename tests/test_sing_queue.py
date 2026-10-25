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
    acp._MIXED_RENDEZVOUS.clear()
    acp._NOW_PLAYING_TITLE = ""
    acp._PIPELINE_GEN = 0
    acp._ORCH_TASK = None
    acp._PREPARE_TASK = None
    acp.IS_SINGING_ACTIVE = False
    yield
    acp.SONG_REQUEST_QUEUE.clear()
    acp.READY_SONGS.clear()
    acp._ACTIVE_TITLES.clear()
    acp._MIXED_RENDEZVOUS.clear()
    acp._NOW_PLAYING_TITLE = ""
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


def test_cover_ready_or_playing():
    """混用會合判定：備好待播或正在唱才算數，排隊/準備中不算（鋼琴會等太早）。"""
    assert not acp.cover_ready_or_playing("晴天")
    assert not acp.cover_ready_or_playing("")
    acp.request_cover_song("晴天", "老爸")  # 只進隊列＋準備中
    assert not acp.cover_ready_or_playing("晴天")
    acp.READY_SONGS.append({"title": "晴天", "vocal": "v", "inst": "i",
                            "requester": "", "gen": 0})
    assert acp.cover_ready_or_playing("晴天")
    assert acp.cover_ready_or_playing("晴天 ")  # 空白模糊命中
    acp.READY_SONGS.clear()
    acp._NOW_PLAYING_TITLE = "晴天"
    try:
        assert acp.cover_ready_or_playing("晴天")
        assert not acp.cover_ready_or_playing("月光")
    finally:
        acp._NOW_PLAYING_TITLE = ""


def test_mixed_rendezvous_lifecycle():
    """
    會合點：開場建旗→鋼琴舉旗→翻唱側取出（一次性）→stop全清。"""
    rv = acp.arm_mixed_rendezvous("晴天")
    assert not rv["piano"].is_set() and not rv["sing"].is_set()
    rv["piano"].set()
    rv["sing"].set()
    # 模擬翻唱開唱時的取出（一次性，取走就沒了）
    key = acp._dedupe_key("晴天")
    got = acp._MIXED_RENDEZVOUS.pop(key, None)
    assert got is rv
    assert acp._MIXED_RENDEZVOUS.pop(key, None) is None
    # stop 清場
    acp.arm_mixed_rendezvous("月光")
    acp.stop_singing()
    assert len(acp._MIXED_RENDEZVOUS) == 0
    acp.disarm_mixed_rendezvous("不存在的歌")  # 不炸


def test_clear_prep_halo_only_halo_alone():
    """開唱清場：只有暈單獨在臉上才摘，有別的戲/沒暈不碰（2026-10-11 暈帶上台事件）。"""
    import asyncio
    import services.vts_client as vc

    class FakeVTS:
        def __init__(self, active):
            self._active = set(active)
            self.deactivated = []

        async def request(self, payload):
            mt = payload.get("messageType")
            if mt == "ExpressionStateRequest":
                return {"data": {"expressions": [
                    {"file": f, "active": True} for f in self._active]}}
            if mt == "ExpressionActivationRequest":
                f = (payload.get("data", {}) or {}).get("expressionFile", "")
                if not (payload.get("data", {}) or {}).get("active", True):
                    self._active.discard(f)
                    self.deactivated.append(f)
            return {"data": {}}

    halo = (vc.VTS_EXPRESSION_MAP or {}).get("暈")
    assert halo, "選單沒有暈"
    old_set, old_vts = getattr(vc, "CURRENT_ACTIVE_EXPS", set()), vc.GLOBAL_VTS
    try:
        # 只有暈（busy worker 經 trigger 登記在小本本）→摘掉
        vc.CURRENT_ACTIVE_EXPS = {halo}
        vc.GLOBAL_VTS = FakeVTS({halo})
        assert asyncio.run(acp._clear_prep_halo()) is True
        assert vc.GLOBAL_VTS.deactivated == [halo]
        # 臉空→不動
        vc.GLOBAL_VTS = FakeVTS(set())
        assert asyncio.run(acp._clear_prep_halo()) is False
        # 暈＋別的→不動（不搶戲）
        vc.GLOBAL_VTS = FakeVTS({halo, "星星眼.exp3.json"})
        vc.CURRENT_ACTIVE_EXPS = {"星星眼.exp3.json"}
        assert asyncio.run(acp._clear_prep_halo()) is False
        assert vc.GLOBAL_VTS.deactivated == []
    finally:
        vc.CURRENT_ACTIVE_EXPS = old_set
        vc.GLOBAL_VTS = old_vts


def test_stop_current_song_keeps_queue():
    """電擊打斷：只停當首，排隊保留，去重鍵不動；閒時回 False。"""
    acp.IS_SINGING_ACTIVE = True
    acp._NOW_PLAYING_TITLE = "歌A"
    acp.request_cover_song("歌A", "老爸")
    acp.request_cover_song("歌B", "老爸")
    assert acp.stop_current_song() is True
    assert acp.IS_SINGING_ACTIVE is False
    assert acp._NOW_PLAYING_TITLE == ""
    assert len(acp.SONG_REQUEST_QUEUE) == 2
    assert acp.is_song_active("歌A")
    assert acp.is_song_active("歌B")
    acp.stop_singing()
    assert acp.stop_current_song() is False


def test_stop_current_song_disarms_rendezvous():
    """電擊打斷混用歌：會合點一起拆，否則下次重點同首撿到屍體乾等 300 秒。"""
    acp.IS_SINGING_ACTIVE = True
    acp._NOW_PLAYING_TITLE = "混用歌"
    acp.arm_mixed_rendezvous("混用歌")
    assert acp._dedupe_key("混用歌") in acp._MIXED_RENDEZVOUS
    assert acp.stop_current_song() is True
    assert acp._dedupe_key("混用歌") not in acp._MIXED_RENDEZVOUS
    acp.stop_singing()


def test_cover_subprocess_output_decoded_as_utf8():
    """yt-dlp／demucs 輸出是 UTF-8；text=True 不指定編碼會用 cp950 解，讀取執行緒噴 UnicodeDecodeError（2026-10-25 實機）。"""
    import ast
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "services", "auto_cover_pipeline.py"), encoding="utf-8").read()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run":
            kw = {k.arg: ast.unparse(k.value) for k in n.keywords}
            if kw.get("text") == "True":
                assert kw.get("encoding") == "'utf-8'", ast.unparse(n)[:80]
