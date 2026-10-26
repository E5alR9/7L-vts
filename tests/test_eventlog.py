# -*- coding: utf-8 -*-
"""流水帳（core.eventlog，2026-10-26）：記、查、去重用的 seen／last、舊對話記憶匯入、對話記憶雙寫。"""
import os

from core import eventlog
from core.eventlog import EventLog


def test_record_and_recent_in_order_with_meta_filter():
    log = EventLog()
    log.record("slip", "a", who="dad", ts=1.0, brain="live")
    log.record("slip", "b", ts=2.0, brain="rest")
    log.record("heard", "c", ts=3.0)
    assert [e["text"] for e in log.recent("slip")] == ["a", "b"]
    assert [e["text"] for e in log.recent("slip", brain="live")] == ["a"]
    assert [e["text"] for e in log.recent(since=1.5)] == ["b", "c"]
    assert [e["text"] for e in log.recent(limit=2)] == ["b", "c"]          # 最新兩筆，舊到新
    assert log.recent("slip")[0]["meta"] == {"brain": "live"} and log.recent("slip")[0]["who"] == "dad"


def test_seen_window_is_open_on_the_old_side():
    log = EventLog()
    log.record("stage_cmd", "x", ts=100.0)
    assert log.seen("stage_cmd", "x", 20.0, now=119.9)
    assert not log.seen("stage_cmd", "x", 20.0, now=120.0)                 # 剛好 20 秒：過窗
    assert not log.seen("stage_cmd", "x", 20.0, now=99.0)                  # 未來的不算
    assert not log.seen("slip", "x", 20.0, now=110.0)


def test_last_with_prefixes():
    log = EventLog()
    log.record("stage_cmd", "pe.pause|{}", ts=1.0)
    log.record("stage_cmd", "sing|{}", ts=2.0)
    assert log.last("stage_cmd")["text"] == "sing|{}"
    assert log.last("stage_cmd", prefixes=["pe.pause|", "pe.resume|"])["text"] == "pe.pause|{}"
    assert log.last("stage_cmd", since=1.5, prefixes=["pe.pause|"]) is None


def test_file_db_survives_reopen(tmp_path):
    p = os.path.join(tmp_path, "e.sqlite")
    log = EventLog(p)
    log.record("said", "晚安", who="7L")
    log.close()
    log = EventLog(p)
    assert log.recent("said")[0]["text"] == "晚安"
    log.close()


def test_memory_kind():
    assert eventlog.memory_kind("7L", "assistant") == "said"
    assert eventlog.memory_kind("老爸", "user") == "heard"
    assert eventlog.memory_kind("7L", "thought") == "thought"
    assert eventlog.memory_kind("小明", "user", source="tiktok") == "heard"


def test_import_old_memory_only_once():
    log = EventLog()
    old = [{"time": 2.0, "speaker": "7L", "target": "老爸", "content": "早安", "role": "assistant"},
           {"time": 1.0, "speaker": "老爸", "target": "7L", "content": "7L 早", "role": "user"},
           {"time": 3.0, "speaker": "7L", "content": " ", "role": "assistant"}]
    assert eventlog.import_memory_entries(log, old) == 2
    assert [(e["kind"], e["text"]) for e in log.recent()] == [("heard", "7L 早"), ("said", "早安")]
    assert eventlog.import_memory_entries(log, old) == 0                   # 帳本不是空的就不再匯


def test_unified_memory_is_double_written():
    from core import memory
    memory.append_to_unified_memory("老爸", "7L", "幫我查天氣", role="user", source="text")
    memory.append_to_unified_memory("7L", "老爸", "好喔我查查", role="assistant", source="live_api")
    got = [(e["kind"], e["who"], e["text"]) for e in eventlog.get().recent(("heard", "said"))]
    assert got[-2:] == [("heard", "老爸", "幫我查天氣"), ("said", "7L", "好喔我查查")]
