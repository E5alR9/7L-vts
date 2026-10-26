"""Live 主腦斷線時麥克風改走舊 STT（2026-10-26）：斷線計時、mic_worker 只在斷線夠久才收音。"""
import ast
import asyncio
import os
import types as pytypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
TREE = ast.parse(MAIN)


def _load(*names, **ns):
    ns.setdefault("log_print", lambda *a, **k: None)
    for name in names:
        fn = next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), name, "exec"), ns)
    return ns


class _Clock:
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t


def test_down_clock_starts_when_the_brain_drops_and_keeps_running_while_reconnects_fail():
    clock = _Clock(100.0)
    ns = _load("is_live_brain_active", "_set_live_active", "live_brain_down_for",
               time=clock, LIVE_SESSION_ACTIVE=False, _LIVE_DOWN_SINCE=0.0)
    ns["_set_live_active"](True)
    assert ns["live_brain_down_for"]() == 0.0
    clock.t = 200.0
    ns["_set_live_active"](False)      # 斷線那一刻
    clock.t = 205.0
    ns["_set_live_active"](False)      # 重連又失敗：不重新起算
    clock.t = 212.0
    assert ns["live_brain_down_for"]() == 12.0
    ns["_set_live_active"](True)
    assert ns["live_brain_down_for"]() == 0.0


class _Done(BaseException):
    pass


def _run_mic_worker(downs):
    """downs：每圈 live_brain_down_for() 回的秒數；用完就結束。回 (listen 呼叫參數, 日誌)。"""
    downs = iter(downs)
    listens, logs = [], []

    def down_for():
        try:
            return next(downs)
        except StopIteration:
            raise _Done()

    class _Mic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    async def _no_sleep(_s):
        return None

    async def _to_thread(fn, *a):
        return fn(*a)

    def listen_once_fast(recognizer, wait_sec=None):
        listens.append(wait_sec)
        return ("", None)

    rec = pytypes.SimpleNamespace(energy_threshold=300, adjust_for_ambient_noise=lambda s, duration: None)
    ns = _load("mic_worker", live_brain_down_for=down_for, LIVE_FALLBACK_AFTER_SEC=8.0, IS_MIC_ENABLED=True,
               listen_once_fast=listen_once_fast, sr=pytypes.SimpleNamespace(Microphone=_Mic), os=os,
               asyncio=pytypes.SimpleNamespace(sleep=_no_sleep, to_thread=_to_thread),
               log_print=lambda m, *a, **k: logs.append(m), current_mic_action_str="", MIC_ENERGY_THRESHOLD=500)
    try:
        asyncio.run(ns["mic_worker"](rec, None))
    except _Done:
        pass
    return listens, logs


def test_mic_worker_leaves_the_mic_to_live_while_it_is_up_or_just_switching_lines():
    listens, logs = _run_mic_worker([0.0, 0.0, 3.0, 7.9])
    assert listens == []
    assert not any("舊 STT" in l for l in logs)


def test_mic_worker_listens_once_live_has_been_down_long_enough_and_hands_back_when_it_returns():
    listens, logs = _run_mic_worker([0.0, 9.0, 12.0, 0.0, 0.0])
    assert listens == [3.0, 3.0]   # 每次最多等 3 秒，回頭看 Live 回來沒
    assert any("改走 Google 語音辨識" in l for l in logs)
    assert any("交回 Live" in l for l in logs)
    assert sum("麥克風閥值就緒" in l for l in logs) == 1   # 只校一次


def test_listen_once_fast_gives_up_after_the_wait_when_nobody_speaks():
    waits = []

    class _Mic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Rec:
        def listen(self, source, timeout=None, phrase_time_limit=None):
            waits.append(timeout)
            raise TimeoutError("沒人開口")   # speech_recognition 的 WaitTimeoutError

    ns = _load("listen_once_fast", sr=pytypes.SimpleNamespace(Microphone=_Mic), os=os, time=_Clock(0.0),
               MIC_PHRASE_TIME_LIMIT=30.0, MIC_MIN_RMS_THRESHOLD=250.0)
    assert ns["listen_once_fast"](_Rec(), wait_sec=3.0) == ("", None)
    assert waits == [3.0]
    assert ns["is_user_listening"] is False


def test_main_starts_the_stt_fallback_with_the_live_brain():
    main = next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    src = ast.get_source_segment(MAIN, main)
    assert "spawn(mic_worker(recognizer, input_queue))" in src
