# -*- coding: utf-8 -*-
"""Firestore 只當備份、本地優先（2026-10-26，老爸決定）：
觀眾檔、知識庫先讀本機，開機不等雲端；記憶推雲端節流；流水帳定期推一份備份（畫面描述不上傳）。"""
import asyncio
import json
import os
import types

import core.memory as mem
from core import eventlog


class FakeDoc:
    def __init__(self, store, calls, key):
        self.store, self.calls, self.key = store, calls, key

    async def get(self):
        self.calls.append(("get", self.key))
        data = self.store.get(self.key)
        return types.SimpleNamespace(exists=data is not None, to_dict=lambda: dict(data or {}))

    async def set(self, data, merge=False):
        self.calls.append(("set", self.key))
        self.store[self.key] = data
        return 200


class FakeDB:
    def __init__(self, store=None):
        self.store, self.calls = dict(store or {}), []

    def collection(self, c):
        return types.SimpleNamespace(document=lambda d: FakeDoc(self.store, self.calls, (c, d)))


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def test_viewer_profile_reads_local_first_and_caches_cloud_hits(monkeypatch):
    db = FakeDB({("viewer_profiles", "小華"): {"call": "華華"}})
    monkeypatch.setattr(mem.db_module, "db", db)
    _write(mem.VIEWER_PROFILES_FILE, {"小明": {"call": "明明"}})
    assert asyncio.run(mem.get_viewer_profile("小明"))["call"] == "明明"
    assert db.calls == []                                                   # 本機有：不問雲端
    assert asyncio.run(mem.get_viewer_profile("小華"))["call"] == "華華"   # 本機沒有：問一次雲端
    assert asyncio.run(mem.get_viewer_profile("小華"))["call"] == "華華"
    assert db.calls == [("get", ("viewer_profiles", "小華"))]              # 第二次就讀本機了
    assert "小華" in json.load(open(mem.VIEWER_PROFILES_FILE, encoding="utf-8"))
    monkeypatch.setattr(mem, "_CLOUD_PROFILE_MISSES", set())
    asyncio.run(mem.get_viewer_profile("新來的"))
    asyncio.run(mem.get_viewer_profile("新來的"))
    assert db.calls.count(("get", ("viewer_profiles", "新來的"))) == 1         # 雲端也沒有：這次開機只問一次
    os.remove(mem.VIEWER_PROFILES_FILE)


def test_knowledge_does_not_wait_for_cloud_and_takes_newer_cloud_copy(monkeypatch):
    cloud = {"persona_core": "雲端版", "last_updated": "2026-10-26 10:00:00"}
    db = FakeDB({("cloud_mind_knowledge", "core_knowledge"): cloud})
    monkeypatch.setattr(mem.db_module, "db", db)
    monkeypatch.setattr(mem, "CLOUD_KNOWLEDGE_CACHE", None)
    monkeypatch.setattr(mem, "_KNOWLEDGE_CLOUD_CHECK", {"task": None})
    _write(mem.CLOUD_KNOWLEDGE_FILE, {"persona_core": "本機版", "last_updated": "2026-09-21 23:47:26"})

    async def go():
        first = await mem.get_cloud_knowledge()               # 先拿本機的，不等雲端
        await mem._KNOWLEDGE_CLOUD_CHECK["task"]              # 背景看一眼雲端
        return first, await mem.get_cloud_knowledge()
    first, after = asyncio.run(go())
    assert first["persona_core"] == "本機版" and after["persona_core"] == "雲端版"
    assert json.load(open(mem.CLOUD_KNOWLEDGE_FILE, encoding="utf-8"))["persona_core"] == "雲端版"


def test_knowledge_keeps_newer_local_copy(monkeypatch):
    db = FakeDB({("cloud_mind_knowledge", "core_knowledge"): {"persona_core": "舊雲端", "last_updated": "2026-09-01 00:00:00"}})
    monkeypatch.setattr(mem.db_module, "db", db)
    monkeypatch.setattr(mem, "CLOUD_KNOWLEDGE_CACHE", None)
    monkeypatch.setattr(mem, "_KNOWLEDGE_CLOUD_CHECK", {"task": None})
    _write(mem.CLOUD_KNOWLEDGE_FILE, {"persona_core": "新本機", "last_updated": "2026-10-26 10:00:00"})

    async def go():
        await mem.get_cloud_knowledge()
        await mem._KNOWLEDGE_CLOUD_CHECK["task"]
        mem.CLOUD_KNOWLEDGE_CACHE = None
        return await mem.get_cloud_knowledge()
    assert asyncio.run(go())["persona_core"] == "新本機"


def test_memory_cloud_push_is_throttled(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(mem.db_module, "db", db)
    monkeypatch.setattr(mem, "_LAST_CLOUD_PUSH_TIME", 0.0)

    async def go():
        loop = asyncio.get_running_loop()
        for _ in range(3):
            mem._save_unified_memory_to_disk(loop)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert [c for c in db.calls if c[0] == "set"] == [("set", ("unified_memory", "live_stream_timeline"))]


def test_event_backup_pushes_new_rows_once_and_skips_vision(tmp_path):
    log = eventlog.EventLog()
    log.record("heard", "7L 晚安", who="小明")
    log.record("vision", "畫面上是程式碼")
    log.record("said", "晚安～", who="7L")
    db, state = FakeDB(), os.path.join(tmp_path, "state.json")
    assert asyncio.run(eventlog.backup_once(log, db, "event_backup_test", state)) == 2
    doc = db.store[("event_backup_test", "0000000001")]
    assert [r["text"] for r in doc["rows"]] == ["7L 晚安", "晚安～"] and doc["last_id"] == 3
    assert asyncio.run(eventlog.backup_once(log, db, "event_backup_test", state)) == 0   # 沒有新的：不推
    log.record("heard", "還在嗎")
    assert asyncio.run(eventlog.backup_once(log, db, "event_backup_test", state)) == 1
    assert ("event_backup_test", "0000000004") in db.store


def test_event_backup_stops_on_failure_and_retries_from_same_row(tmp_path):
    log = eventlog.EventLog()
    log.record("heard", "一")

    class Down(FakeDB):
        def collection(self, c):
            async def fail(data, merge=False):
                return 429
            return types.SimpleNamespace(document=lambda d: types.SimpleNamespace(set=fail))
    state = os.path.join(tmp_path, "state.json")
    assert asyncio.run(eventlog.backup_once(log, Down(), "c", state)) == 0
    assert not os.path.exists(state)
    db = FakeDB()
    assert asyncio.run(eventlog.backup_once(log, db, "c", state)) == 1
