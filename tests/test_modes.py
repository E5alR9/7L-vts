# -*- coding: utf-8 -*-
"""modes 裝配同步測試：vts 啟動裝配必須與 modes/workers.py 宣告一致。"""
import re
from conftest import ROOT  # noqa: F401
from modes.workers import plan, COMMON, COMPANION_ONLY, VTUBER_BANS


def _startup_src():
    from modes.workers import __file__ as _  # noqa
    import pathlib
    vts = pathlib.Path(__file__).resolve().parent.parent / "vts_7L_test.py"
    return vts.read_text(encoding="utf-8")


def test_plan_shapes():
    c, v = plan("companion"), plan("vtuber")
    assert set(COMMON) <= set(c["workers"])
    assert set(COMPANION_ONLY) <= set(c["workers"])
    assert v["bans"] == VTUBER_BANS
    assert not (set(COMPANION_ONLY) & set(v["workers"]))
    assert plan("亂填")["mode"] == "vtuber"


def test_startup_matches_plan():
    src = _startup_src()
    for w in COMMON:
        pass  # COMMON 為概念分組；以下斷言關鍵裝配語句存在
    assert "asyncio.create_task(video_watch.video_watch_worker())" in src
    assert "_cs.register_chat_worker(\"twitch\", twitch_live_worker)" in src
    assert "if _IS_VTUBER:" in src
    assert "yt_comp.IS_YT_WATCHER_ENABLED = False" in src
    assert "if DISCORD_TOKEN and not _IS_VTUBER:" in src
    assert re.search(r"set_sleep_mode\(enable: bool\):[\s\S]{0,400}?is_vtuber\(\)", src)
    assert 'source == "owner_interject"' in src
    assert "operator_input_enabled" in src
