# -*- coding: utf-8 -*-
"""pytest 共用設定：把專案根目錄加進 sys.path"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


import pytest  # noqa: E402

_MEMORY_FILES = ("UNIFIED_MEMORY_FILE", "DIALOGUE_MEMORY_FILE", "THOUGHT_MEMORY_FILE", "VIEWER_PROFILES_FILE",
                 "CLOUD_KNOWLEDGE_FILE", "USER_PROFILE_FILE", "MEMORY_CONFIG_FILE")


@pytest.fixture(autouse=True, scope="session")
def _memory_files_in_tmp(tmp_path_factory):
    """記憶檔在測試裡全指到暫存資料夾、不連雲端。
    2026-10-26 事故：鋼琴測試呼叫到真的 append_to_unified_memory，沒有事件迴圈時會同步存檔，
    每跑一次全套測試就把 data/ 裡 7L 的對話記憶蓋成一兩句（10/25 下午加了那個測試以後一直這樣）。"""
    import core.db as db
    import core.memory as mem
    tmp = str(tmp_path_factory.mktemp("data"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mem, "DATA_DIR", tmp)
        for name in _MEMORY_FILES:
            mp.setattr(mem, name, os.path.join(tmp, os.path.basename(getattr(mem, name))))
        mp.setattr(db, "db", None)
        yield tmp
