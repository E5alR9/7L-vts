# -*- coding: utf-8 -*-
"""pytest 共用設定：把專案根目錄加進 sys.path"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


import ast  # noqa: E402

import pytest  # noqa: E402

# 主檔原始碼：測試要抽主檔的函式出來單獨跑（主檔一 import 就會開機），全部共用這一份，只讀一次、parse 一次
MAIN_SRC = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
MAIN_TREE = ast.parse(MAIN_SRC)


def main_def(name):
    """主檔頂層的 def／async def 節點（找不到就 StopIteration，測試直接紅）。"""
    return next(n for n in MAIN_TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def load_main(*names, **ns):
    """把主檔幾個頂層函式 exec 進 ns 回傳；函式用到的全域由呼叫端用關鍵字塞進來。log_print 預設不印。"""
    ns.setdefault("log_print", lambda *a, **k: None)
    for name in names:
        exec(compile(ast.Module(body=[main_def(name)], type_ignores=[]), name, "exec"), ns)
    return ns

_MEMORY_FILES = ("UNIFIED_MEMORY_FILE", "DIALOGUE_MEMORY_FILE", "THOUGHT_MEMORY_FILE", "VIEWER_PROFILES_FILE",
                 "CLOUD_KNOWLEDGE_FILE", "USER_PROFILE_FILE", "MEMORY_CONFIG_FILE")


@pytest.fixture(autouse=True, scope="session")
def _memory_files_in_tmp(tmp_path_factory):
    """記憶檔在測試裡全指到暫存資料夾、不連雲端。
    2026-10-26 事故：鋼琴測試呼叫到真的 append_to_unified_memory，沒有事件迴圈時會同步存檔，
    每跑一次全套測試就把 data/ 裡 7L 的對話記憶蓋成一兩句（10/25 下午加了那個測試以後一直這樣）。"""
    import core.db as db
    import core.memory as mem
    import services.rag_memory_service as rag_service

    async def _no_rag(*a, **k):
        return None   # 2026-10-26 起她的回覆也會進向量庫：測試裡有事件迴圈時不能真的寫 data/rag/

    tmp = str(tmp_path_factory.mktemp("data"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mem, "DATA_DIR", tmp)
        for name in _MEMORY_FILES:
            mp.setattr(mem, name, os.path.join(tmp, os.path.basename(getattr(mem, name))))
        mp.setattr(db, "db", None)
        mp.setattr(rag_service, "add_rag_memory", _no_rag)
        yield tmp


@pytest.fixture(autouse=True)
def _cover_cache_in_tmp(tmp_path_factory, monkeypatch):
    """翻唱快取（songs_library/cover_cache）在測試裡指到暫存資料夾（另開一個，不佔測試自己的 tmp_path）。
    2026-10-27 健檢：三個翻唱測試直接寫進真的快取，其中一個還整個 rmtree 掉實機 Demucs 分離好的 stems。"""
    import sys
    acp = sys.modules.get("services.auto_cover_pipeline")
    if acp is not None:
        monkeypatch.setattr(acp, "CACHE_DIR", str(tmp_path_factory.mktemp("cover_cache")))
    yield


@pytest.fixture(autouse=True)
def _eventlog_in_memory():
    """流水帳（core.eventlog）在測試裡記在記憶體，不寫到 data/。"""
    from core import eventlog
    eventlog.set_default(eventlog.EventLog(":memory:"))
    yield
    eventlog.set_default(None)
