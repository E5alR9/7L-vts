"""記憶存檔（2026-10-22）：
1. 存檔在執行緒池跑，舊版在裡面 get_running_loop() 必定失敗，雲端備份從沒送出過；
2. 節流只存窗口開頭那筆，2 秒內的後續對話要等下一次有人說話才落地；
3. 關機／重開直接 os._exit，最後幾句記憶丟掉。"""
import ast
import asyncio
import os

import core.memory as mem


def test_schedule_on_loop_from_worker_thread_reaches_loop():
    ran = []

    async def coro():
        ran.append("cloud-sync")

    async def main():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mem._schedule_on_loop, coro(), loop)
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert ran == ["cloud-sync"]


def test_schedule_on_loop_without_loop_closes_coroutine():
    async def coro():
        raise AssertionError("不該執行")

    c = coro()
    mem._schedule_on_loop(c, None)  # 沒有 loop：關掉協程，不丟 "never awaited" 也不炸
    assert c.cr_frame is None


def test_trailing_save_catches_writes_inside_window(monkeypatch):
    calls = []
    monkeypatch.setattr(mem, "_save_unified_memory_to_disk", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(mem, "_SAVE_INTERVAL", 0.2)
    monkeypatch.setattr(mem, "_TRAILING_SAVE_HANDLE", None)
    monkeypatch.setattr(mem, "_LAST_UNIFIED_SAVE_TIME", 0.0)

    async def main():
        import time
        mem._request_unified_save(time.time())   # 窗口開頭：立刻存
        await asyncio.sleep(0.02)
        mem._request_unified_save(time.time())   # 窗口內：排補存
        mem._request_unified_save(time.time())   # 再一筆：不重複排
        await asyncio.sleep(0.02)
        first = len(calls)
        await asyncio.sleep(0.35)                # 窗口結束：補存觸發
        return first, len(calls)

    first, total = asyncio.run(main())
    assert first == 1
    assert total == 2
    assert mem._TRAILING_SAVE_HANDLE is None


def test_flush_skips_until_memory_loaded(monkeypatch):
    calls = []
    monkeypatch.setattr(mem, "_save_unified_memory_to_disk", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(mem, "_TRAILING_SAVE_HANDLE", None)
    monkeypatch.setattr(mem, "_MEMORY_LOADED", False)
    mem.flush_unified_memory()
    assert calls == []          # 還沒載入：不能用空記憶蓋掉磁碟檔
    monkeypatch.setattr(mem, "_MEMORY_LOADED", True)
    mem.flush_unified_memory()
    assert calls == [{"cloud": False}]


def _main_tree():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ast.parse(open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read())


def test_single_exit_path_flushes_before_restart():
    tree = _main_tree()
    exits = [(f.name) for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             for c in ast.walk(f) if isinstance(c, ast.Call) and ast.unparse(c.func) == "os._exit"]
    assert set(exits) == {"shutdown_7l"}, exits   # 只剩一個出口
    fn = next(f for f in tree.body if isinstance(f, ast.FunctionDef) and f.name == "shutdown_7l")
    line = {ast.unparse(c.func): c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert line["flush_unified_memory"] < line["subprocess.Popen"] < line["os._exit"]
