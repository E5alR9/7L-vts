"""Live 主腦斷線時麥克風改走舊 STT（2026-10-26）：斷線計時、mic_worker 只在斷線夠久才收音。"""
import ast
import asyncio
import os
import types as pytypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE, load_main  # noqa: E402


_load = load_main


class _Clock:
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t


def test_down_clock_starts_when_the_brain_drops_and_keeps_running_while_reconnects_fail():
    clock = _Clock(100.0)
    ns = _load("is_live_brain_active", "_set_live_active", "live_brain_down_for",
               time=clock, LIVE_SESSION_ACTIVE=False, _LIVE_DOWN_SINCE=0.0, _LIVE_UP_SINCE=0.0, LIVE_STABLE_SEC=10.0)
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


def test_down_clock_keeps_running_while_the_brain_flaps():
    """連上幾秒又斷（麥克風壞掉、連上就被踢）：斷線時間接著算，REST 大腦才接得到（2026-10-31 Fable 審查）。"""
    clock = _Clock(100.0)
    ns = _load("is_live_brain_active", "_set_live_active", "live_brain_down_for",
               time=clock, LIVE_SESSION_ACTIVE=True, _LIVE_DOWN_SINCE=0.0, _LIVE_UP_SINCE=0.0, LIVE_STABLE_SEC=10.0)
    ns["_set_live_active"](False)       # 穩定的連線斷了：從 100 起算
    for t in (103.0, 109.0):
        clock.t = t
        ns["_set_live_active"](True)    # 連上
        clock.t = t + 2.0
        ns["_set_live_active"](False)   # 兩秒又斷
    clock.t = 112.0
    assert ns["live_brain_down_for"]() == 12.0


def test_rest_brain_takes_over_while_the_live_brain_stays_mute():
    """連線在但一直不出聲、換了兩次都一樣：REST 大腦先接；她一出聲就換回 Live。"""
    import time
    ns = _load("is_live_brain_active", "live_brain_down_for", "use_rest_brain", "_brain_output_seen",
               time=time, LIVE_SESSION_ACTIVE=True, _LIVE_DOWN_SINCE=0.0, LIVE_FALLBACK_AFTER_SEC=8.0,
               LAST_BRAIN_OUTPUT_TS=0.0, _LIVE_MUTE={"strikes": 0, "rotate": "", "rotations": 2, "rest_until": time.time() + 300})
    assert ns["use_rest_brain"]()
    ns["_brain_output_seen"]()
    assert not ns["use_rest_brain"]() and ns["_LIVE_MUTE"]["rotations"] == 0


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
               listen_once_fast=listen_once_fast, sr=pytypes.SimpleNamespace(Microphone=_Mic), os=os, time=_Clock(0.0),
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

    swallowed = []
    ns = _load("listen_once_fast", sr=pytypes.SimpleNamespace(Microphone=_Mic, WaitTimeoutError=TimeoutError), os=os,
               time=_Clock(0.0), MIC_PHRASE_TIME_LIMIT=30.0, MIC_MIN_RMS_THRESHOLD=250.0,
               log_swallowed=lambda *a, **k: swallowed.append(1))
    assert ns["listen_once_fast"](_Rec(), wait_sec=3.0) == ("", None)
    assert waits == [3.0]
    assert ns["is_user_listening"] is False
    assert swallowed == []                      # 沒人開口是正常的，不記

    class _BrokenMic(_Mic):
        def __enter__(self):
            raise OSError("裝置被占用")
    ns["sr"] = pytypes.SimpleNamespace(Microphone=_BrokenMic, WaitTimeoutError=TimeoutError)
    assert ns["listen_once_fast"](_Rec(), wait_sec=3.0) == ("", None)
    assert swallowed == [1]                     # 麥克風開不起來要留紀錄（以前整個吞掉）


def test_main_starts_the_stt_fallback_with_the_live_brain():
    main = next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    src = ast.get_source_segment(MAIN, main)
    assert "spawn(mic_worker(recognizer, input_queue))" in src
