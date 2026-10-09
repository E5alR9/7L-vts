"""表情去重查詢（2026-10-10：本能腦主做表情、NV 子代理備用）。

toggle 語義：同檔已在臉上再下一次＝關掉。NV 動手前查臉，
本能做了就閉嘴。以下全是純函數測試，不碰 VTS、不碰網路。
"""
import asyncio
import time

import services.vts_client as v


def _seed(files=(), **timers):
    v.CURRENT_ACTIVE_EXPS = set(files)
    now = time.time()
    v.wink_timer = timers.get("wink", 0.0)
    v.shock_timer = timers.get("shock", 0.0)
    v.frown_timer = timers.get("frown", 0.0)
    v.eye_roll_timer = timers.get("eye_roll", 0.0)
    return now


def test_map_hit_means_active():
    key = next(iter(v.VTS_EXPRESSION_MAP))
    f = v.VTS_EXPRESSION_MAP[key]
    _seed()
    assert not v.is_expression_active(key)
    _seed((f,))
    assert v.is_expression_active(key)
    # 括號標籤格式也認（腦子常帶殼輸出）
    _seed((f,))
    assert v.is_expression_active(f"[EXPRESSION: {key}]")


def test_timer_routes_use_timers_not_files():
    now = _seed()
    assert not v.is_expression_active("WINK")
    _seed(wink=now + 10)
    assert v.is_expression_active("WINK")
    assert v.is_expression_active("眨眼")
    _seed(shock=now + 10)
    assert v.is_expression_active("震驚")
    _seed(frown=now + 10)
    assert v.is_expression_active("皺眉")
    _seed(eye_roll=now + 10)
    assert v.is_expression_active("翻白眼")


def test_reset_means_empty_face():
    _seed()
    assert v.is_expression_active("正常")
    assert v.is_expression_active("_RESET_")
    key = next(iter(v.VTS_EXPRESSION_MAP))
    _seed((v.VTS_EXPRESSION_MAP[key],))
    assert not v.is_expression_active("正常")


def test_unknown_and_empty_never_active():
    _seed()
    assert not v.is_expression_active("")
    assert not v.is_expression_active(None)
    assert not v.is_expression_active("法藍朵星人")


def test_wait_returns_fast_when_already_active():
    key = next(iter(v.VTS_EXPRESSION_MAP))
    _seed((v.VTS_EXPRESSION_MAP[key],))
    assert asyncio.run(v.wait_expression_active(key, timeout=2.5)) is True


def test_wait_times_out_when_nobody_acts():
    _seed()
    key = next(iter(v.VTS_EXPRESSION_MAP))
    t0 = time.time()
    assert asyncio.run(v.wait_expression_active(key, timeout=0.7)) is False
    assert time.time() - t0 < 2.0


def test_wait_sees_late_arrival():
    _seed()
    key = next(iter(v.VTS_EXPRESSION_MAP))
    f = v.VTS_EXPRESSION_MAP[key]

    async def main():
        async def late():
            await asyncio.sleep(0.4)
            v.CURRENT_ACTIVE_EXPS.add(f)

        await asyncio.create_task(late())
        return await v.wait_expression_active(key, timeout=2.5)

    assert asyncio.run(main()) is True
