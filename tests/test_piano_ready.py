# -*- coding: utf-8 -*-
"""鋼琴子進程就緒/開彈驗證（2026-10-11：IPC 無回執，初始化窗口期指令靜默丟失）。
只測純邏輯，不啟真子進程（revive 不測）。"""
import asyncio
import time

import services.piano_engine as pe


def test_wait_ready_fast_when_heartbeat_fresh():
    pe.LAST_PIANO_HEARTBEAT_TIME = time.time()
    try:
        assert asyncio.run(pe.wait_piano_subprocess_ready(timeout=5.0)) is True
    finally:
        pe.LAST_PIANO_HEARTBEAT_TIME = 0.0


def test_wait_ready_times_out_when_silent():
    pe.LAST_PIANO_HEARTBEAT_TIME = 0.0
    t0 = time.time()
    assert asyncio.run(pe.wait_piano_subprocess_ready(timeout=0.6)) is False
    assert time.time() - t0 < 3.0


def test_wait_sounding_true_when_playing():
    old_active, old_state = pe.is_piano_active, dict(pe.GLOBAL_PIANO_REALTIME_STATE)
    pe.is_piano_active = True
    pe.GLOBAL_PIANO_REALTIME_STATE["is_playing"] = True
    try:
        assert asyncio.run(pe.wait_piano_sounding(pe.PIANO_SESSION_ID, timeout=2.0)) is True
    finally:
        pe.is_piano_active = old_active
        pe.GLOBAL_PIANO_REALTIME_STATE.clear()
        pe.GLOBAL_PIANO_REALTIME_STATE.update(old_state)


def test_wait_sounding_false_fast_when_off():
    old_active = pe.is_piano_active
    pe.is_piano_active = False
    try:
        assert asyncio.run(pe.wait_piano_sounding(999, timeout=5.0)) is False
    finally:
        pe.is_piano_active = old_active
