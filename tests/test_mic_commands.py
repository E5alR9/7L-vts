# -*- coding: utf-8 -*-
"""打字「開麥／關麥」（2026-10-26 功能實測；Discord *mic 指令 2026-10-27 拿掉）：
真的開麥克風會把房間的聲音送給 Live，所以用主程式原本的程式碼在測試裡跑，不碰麥克風。"""
import asyncio
import os

from dryrun import DryRun

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC as MAIN  # noqa: E402


def test_typing_mic_on_off_flips_the_mic_switch():
    async def go():
        async with DryRun(live=True) as d:
            d.ns["IS_MIC_ENABLED"] = False
            await d.dad("開麥")
            await d.settle(0.3)
            on = d.ns["IS_MIC_ENABLED"]
            await d.dad("關麥")
            await d.settle(0.3)
            return on, d.ns["IS_MIC_ENABLED"], d
    on, off, d = asyncio.run(go())
    assert on is True and off is False and d.problems == []


def test_discord_mic_command_removed():
    # 老爸不用 Discord 開關麥克風（2026-10-27）；講「開麥／關麥」和後台開關照舊
    assert '@discord_bot.command(name="mic"' not in MAIN and "async def control_mic(" not in MAIN
