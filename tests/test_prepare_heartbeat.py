# -*- coding: utf-8 -*-
"""長任務心跳（分離/RVC 幾分鐘零輸出會像空轉）：ticker 會跑、結束會停、異常會停。"""
import asyncio
import time

import services.auto_cover_pipeline as ac


def test_heartbeat_ticks_and_stops(capsys):
    async def slow():
        await asyncio.sleep(0.45)
        return "done"

    out = asyncio.run(ac._run_with_heartbeat(slow, "測試任務", "測試歌", interval=0.2))
    assert out == "done"
    assert "進行中" in capsys.readouterr().out


def test_heartbeat_stops_on_error(capsys):
    async def boom():
        await asyncio.sleep(0.05)
        raise RuntimeError("x")

    try:
        asyncio.run(ac._run_with_heartbeat(boom, "測試任務", "測試歌", interval=0.2))
        raise SystemExit("should have raised")
    except RuntimeError:
        pass
    # 只跑 0.05 秒就炸，心跳不該響
    assert "進行中" not in capsys.readouterr().out


def test_heartbeat_no_lingering_tasks():
    async def quick():
        return 1

    async def main():
        before = len(asyncio.all_tasks())
        await ac._run_with_heartbeat(quick, "T", "S", interval=0.05)
        await asyncio.sleep(0.05)
        after = len(asyncio.all_tasks())
        assert after <= before, f"ticker 沒清乾淨：{before} -> {after}"

    asyncio.run(main())
