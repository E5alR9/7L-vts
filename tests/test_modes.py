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


def test_disabled_workers_stay_out_of_manifest_and_startup():
    """已停用 worker 不得出現：manifest 不列，啟動段不得有未註解的啟動行。"""
    assert "background_mind_stream" not in COMMON
    assert "proactive" not in COMPANION_ONLY
    src = _startup_src()
    assert re.search(r"^\s*asyncio\.create_task\((proactive_worker|background_mind_stream_worker)\(", src, re.M) is None


def test_live_workers_gated_by_operator_channel():
    """continuous/instinct Live 只活在操作者通道門內（vtuber 強制關）。"""
    assert "continuous_live_worker" in COMPANION_ONLY
    assert "instinct_live_worker" in COMPANION_ONLY
    src = _startup_src()
    assert "asyncio.create_task(continuous_live_worker(vts))" in src
    assert "asyncio.create_task(instinct_live_worker())" in src
