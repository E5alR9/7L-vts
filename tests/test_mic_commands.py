# -*- coding: utf-8 -*-
"""打字「開麥／關麥」和 Discord *mic 指令（2026-10-26 功能實測）：
真的開麥克風會把房間的聲音送給 Live，所以用主程式原本的程式碼在測試裡跑，不碰麥克風。"""
import ast
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


def _discord_cmds():
    tree = ast.parse(MAIN)
    out = {}
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name in ("control_mic", "discord_mic_on", "discord_mic_off"):
            n.decorator_list = []                 # 拿掉 @discord_bot.command，只跑函式本體
            out[n.name] = n
    return out


def test_discord_mic_command():
    sent = []

    class Ctx:
        async def send(self, text):
            sent.append(text)
    ns = {"IS_MIC_ENABLED": False, "log_print": lambda *a: None}
    for n in _discord_cmds().values():
        exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
    asyncio.run(ns["control_mic"](Ctx(), "on"))
    assert ns["IS_MIC_ENABLED"] is True and "已開啟" in sent[-1]
    asyncio.run(ns["control_mic"](Ctx(), "off"))
    assert ns["IS_MIC_ENABLED"] is False and "已關閉" in sent[-1]
    asyncio.run(ns["control_mic"](Ctx(), ""))
    assert "關閉中" in sent[-1]
    asyncio.run(ns["discord_mic_on"](Ctx()))
    assert ns["IS_MIC_ENABLED"] is True
    asyncio.run(ns["discord_mic_off"](Ctx()))
    assert ns["IS_MIC_ENABLED"] is False
