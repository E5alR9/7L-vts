# -*- coding: utf-8 -*-
"""後台 callback 拆出 main()（2026-10-23）：services/dashboard_bridge.py。
1) CORE_ATTRS 契約：橋用到的主程式名稱都有登記、主程式也真的都有定義（主檔太重不 import，用 AST 核對）。
2) 用假 core 跑開關／模式／鋼琴核實，確認搬家沒改行為。"""
import ast
import asyncio
import inspect
import os
import types

from conftest import ROOT  # noqa: F401
import services.dashboard_bridge as db


def _src(rel):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def _main_top_level_names():
    names = set()
    for n in ast.parse(_src("vts_7L_test.py")).body:
        for sub in (ast.walk(n) if isinstance(n, (ast.Try, ast.If)) else [n]):
            if isinstance(sub, ast.Assign):
                names.update(x.id for t in sub.targets for x in ast.walk(t) if isinstance(x, ast.Name))
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(sub.name)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in sub.names)
    return names


def test_core_attrs_defined_in_main():
    missing = [a for a in db.CORE_ATTRS if a not in _main_top_level_names()]
    assert missing == []


def test_bridge_only_uses_registered_core_attrs():
    """橋裡所有 c.<名稱>／self.core.<名稱> 都要在 CORE_ATTRS 登記。"""
    used = set()
    for n in ast.walk(ast.parse(_src("services/dashboard_bridge.py"))):
        if isinstance(n, ast.Attribute):
            v = n.value
            if isinstance(v, ast.Name) and v.id == "c":
                used.add(n.attr)
            elif isinstance(v, ast.Attribute) and v.attr == "core" and isinstance(v.value, ast.Name) and v.value.id == "self":
                used.add(n.attr)
    assert used - set(db.CORE_ATTRS) == set()


def test_main_is_assembly_only():
    tree = ast.parse(_src("vts_7L_test.py"))
    main = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main"][0]
    nested = [n.name for n in ast.walk(main) if n is not main and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert nested == []
    assert "DashboardBridge(" in ast.get_source_segment(_src("vts_7L_test.py"), main)


def _fake_core(**kw):
    calls = {"set_ai_state": [], "sleep": []}
    pe = types.SimpleNamespace(IS_PIANO_AUTO_RADIO_MODE=False, is_piano_active_and_alive=lambda: False,
                               current_piano_song_title="", GLOBAL_PIANO_REALTIME_STATE={})

    async def set_sleep_mode(enable):
        calls["sleep"].append(enable)
        core.IS_SLEEPING = bool(enable)

    core = types.SimpleNamespace(
        pe=pe, tk_listener=types.SimpleNamespace(IS_STREAMING=False),
        yt_comp=types.SimpleNamespace(IS_YT_WATCHER_ENABLED=False, IS_YT_COMPANION_ACTIVE=False, CURRENT_YT_TITLE="",
                                      LATEST_YT_FRAME_BYTES=None),
        live_timer_hub=types.SimpleNamespace(get_sensor_summary=lambda: {}),
        IS_AUTO_PIANO_ENABLED=False, IS_AUTO_WANDER_ENABLED=True, IS_PROACTIVE_SPEAK_ENABLED=True,
        IS_PERIPHERAL_VISION_ENABLED=True, IS_FACE_TRACKING_ENABLED=True, IS_MIC_ENABLED=True, IS_SLEEPING=False,
        current_ai_status_str=" 正常運作中", current_mic_action_str="待命",
        is_user_listening=False, CURRENT_SYSTEM_AUDIO_VOL_PERCENT=0, CURRENT_MIC_VOL_PERCENT=0,
        LATEST_SYSTEM_AUDIO_TEXT="", LATEST_SYSTEM_AUDIO_TEXT_TIME=0.0, LATEST_SYSTEM_MUSIC_INFO="",
        LATEST_SYSTEM_MUSIC_TIME=0.0, LATEST_REALWORLD_SPEECH_TEXT="", LATEST_REALWORLD_SPEECH_TIME=0.0,
        current_screen_context="", current_system_audio_context="", IS_LIVE_MODE_ACTIVE=True, TOTAL_API_CALLS=0,
        CURRENT_VISION_CHANGE_LEVEL="low", CURRENT_VISION_CHANGE_SCORE=0, VISION_HISTORY_STREAM=[],
        LAST_VISION_LOOK_TIME=0.0, get_api_stress_metrics=lambda: {}, set_sleep_mode=set_sleep_mode,
        **kw,
    )

    import core.stage_state as stage
    stage.AI_STATE = "PIANO"

    def set_ai_state(new, reason="", only_from=None):
        calls["set_ai_state"].append((new, only_from))
        return stage.set_ai_state(new, reason, only_from=only_from)
    core.set_ai_state = set_ai_state
    return core, calls


def test_set_switch_writes_core_globals():
    core, calls = _fake_core()
    b = db.DashboardBridge(core, vts=None, input_queue=None, run_mode="vtuber")
    assert asyncio.run(b.set_switch("IS_AUTO_PIANO_ENABLED", sync_cloud=False)) is True  # None＝反轉
    assert core.IS_AUTO_PIANO_ENABLED is True
    assert asyncio.run(b.set_switch("IS_STREAM_CHAT_ENABLED", True, sync_cloud=False)) is True
    assert core.tk_listener.IS_STREAMING is True
    assert asyncio.run(b.set_switch("IS_SLEEPING", True, sync_cloud=False)) is True
    assert calls["sleep"] == [True] and core.IS_SLEEPING is True


def test_mode_toggle_updates_bridge_mode(monkeypatch):
    for k in ("MODE", "OPERATOR_INPUT", "OPERATOR_SPEECH"):
        monkeypatch.delenv(k, raising=False)
    core, _ = _fake_core()
    b = db.DashboardBridge(core, vts=None, input_queue=None, run_mode="vtuber")
    mode_sw = lambda: [s for s in b.get_switches() if s["key"] == "MODE_TOGGLE"][0]["value"]
    assert mode_sw() is False
    asyncio.run(b.set_switch("MODE_TOGGLE", True, sync_cloud=False))
    assert b.run_mode == "companion" and mode_sw() is True
    assert os.environ["MODE"] == "companion" and os.environ["OPERATOR_INPUT"] == "1"


def test_system_state_resets_dead_piano():
    core, calls = _fake_core()
    b = db.DashboardBridge(core, vts=None, input_queue=None, run_mode="vtuber")
    st = b.get_system_state()
    assert calls["set_ai_state"] == [("IDLE", "PIANO")]
    assert st["ai_state"] == "idle" and st["vts_expression"] == "未連線"
    assert st["audio_perception"]["sys_tag"] == "安靜無聲"


def test_callbacks_match_dashboard_signature():
    import services.web_dashboard as web_dash
    core, _ = _fake_core(STREAMER_MIND_BOARD=[], execute_punish_action=None, execute_reward_action=None)
    b = db.DashboardBridge(core, vts=None, input_queue=None, run_mode="vtuber")
    params = set(inspect.signature(web_dash.start_web_dashboard).parameters)
    keys = set(b.dashboard_callbacks())
    assert keys <= params
    # 原 main() 交出去的 callback 一個都不能少
    assert params - keys == {"port", "get_tools_cb"}


# —— 後台手動工具走主派發器（2026-10-25 健檢）：以前另寫一份，少 13 個工具、行為也不同步 ——

def _manual(tool, args=None):
    sent = []

    async def execute_tool_dispatch(fn, a, caller_target="", caller_user=""):
        sent.append((fn, dict(a), caller_target))
        return " [EXPRESSION: 星星眼] 曲庫有 239 首"
    core, _ = _fake_core(execute_tool_dispatch=execute_tool_dispatch)
    b = db.DashboardBridge(core, vts=None, input_queue=None, run_mode="companion")
    return asyncio.run(b.execute_tool_manually(tool, args or {})), sent


def test_manual_tools_go_through_the_main_dispatcher():
    res, sent = _manual("list_piano_sheets")                      # 舊後台派發器沒有這個
    assert sent == [("list_piano_sheets", {}, "dad")] and res == "曲庫有 239 首"
    _, sent = _manual("pe.stop_virtual_piano")
    assert sent[0][1] == {"force": True}                         # 後台按的就是老爸本人
    _, sent = _manual("video.request_watch", {"url": "youtu.be/jNQXAC9IVRw"})
    assert sent[0][0] == "video.request_watch"


def test_unknown_manual_tool_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        _manual("no_such_tool")


def test_catalog_lists_every_tool_the_brain_can_call():
    import services.web_dashboard as wd
    from core.tool_schema import INTERACTIONS_TOOLS
    names = [t["name"].split(".")[-1] for t in wd.full_tools_catalog()]
    assert len(names) == len(set(names))
    declared = {wd._TOOL_ALIASES.get(n, n) for n in (t["name"].split(".")[-1] for t in INTERACTIONS_TOOLS)}
    assert declared <= set(names)
    assert "auto_sing_song" not in names                          # 跟手寫目錄的 sing_song 是同一個


def test_catalog_tools_are_all_handled_by_the_dispatcher():
    import re
    import services.web_dashboard as wd
    tree = ast.parse(_src("vts_7L_test.py"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute_tool_dispatch")
    handled = {s.split(".")[-1] for s in re.findall(r'"([\w.]+)"', ast.get_source_segment(_src("vts_7L_test.py"), fn))}
    missing = [t["name"] for t in wd.full_tools_catalog()
               if t["name"].split(".")[-1] not in handled | db.DashboardBridge._BRIDGE_ONLY_TOOLS]
    assert not missing, missing
