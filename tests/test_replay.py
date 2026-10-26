# -*- coding: utf-8 -*-
"""重播（tools/replay.py，2026-10-26）：帳本裡的輸入照順序丟進乾跑，結果跟實機一樣。"""
import asyncio
import os
import sys

from core.eventlog import EventLog

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import replay  # noqa: E402


def _db(tmp_path):
    p = os.path.join(tmp_path, "events.sqlite")
    log = EventLog(p)
    log.record("heard", "不是輸入，不重播", ts=99.0)
    log.record("input", "彈小星星", target="text_file", ts=100.0, source="text_file")
    log.record("input", "【TikTok 直播觀眾 小明 留言】：7L 晚安", who="小明", target="tiktok", ts=101.0,
               source="tiktok", platform_uid="xm01", viewer="小明", content="7L 晚安")
    log.record("input", "7L 妳在嗎", target="text_file", ts=102.0, source="text_file")
    log.record("input", "7L 妳在嗎", target="text_file", ts=103.0, source="text_file")
    log.close()
    return p


def test_load_inputs_reads_only_inputs_in_window(tmp_path):
    p = _db(tmp_path)
    assert [e["text"] for e in replay.load_inputs(p, last=2)] == ["7L 妳在嗎", "7L 妳在嗎"]
    got = replay.load_inputs(p, since=100.5, until=101.5)
    assert len(got) == 1 and replay.to_queue_item(got[0], now=5.0) == {
        "text": "【TikTok 直播觀眾 小明 留言】：7L 晚安", "timestamp": 5.0, "source": "tiktok",
        "platform_uid": "xm01", "viewer": "小明", "content": "7L 晚安", "user": "", "audio_base64": None}


def test_replay_runs_the_inputs_through_the_dispatcher(tmp_path):
    out = asyncio.run(replay.replay(replay.load_inputs(_db(tmp_path)), settle=1.2))
    song, viewer, ask, again = (r for _, r in out)
    assert song["tools"] == [("pe.play_virtual_piano", {"song_name": "小星星"})]
    assert any("彈小星星" in s for s in song["slips"]) and song["speech"]          # 罐頭應答講掉了
    assert any("小明" in s for s in viewer["slips"])                                # 看板轉給主腦
    assert ask["slips"] == ["[黑板同步] 老爸傳來文字訊息：7L 妳在嗎"]
    assert again["slips"] == [] and again["deduped"] == 1                          # 10 秒內同一張：去重
    assert all(not r["problems"] for _, r in out)
