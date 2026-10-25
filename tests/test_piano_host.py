# -*- coding: utf-8 -*-
"""鋼琴模組跟主程式的介面（2026-10-25）：以前 MainProxy 從 __main__ 動態撈，撈不到就默默變空函式；
現在主程式啟動時 bind_host 明確交進來，其他東西直接從各自模組 import。"""
import asyncio
import os

from conftest import ROOT
import core.llm_engine as le
import services.piano_engine as pe


def test_unbound_host_is_quiet_noop(monkeypatch):
    monkeypatch.setattr(pe, "_HOST", dict.fromkeys(pe._HOST))
    monkeypatch.setattr(pe, "CURRENT_SPEAKING_TARGET", "")

    async def run():
        await pe._show_subtitle("x")
        await pe._say({"text": "x"})
        return await pe._user_profile()
    assert asyncio.run(run()) == {}
    assert pe._speech_pending() is False
    assert pe.get_current_speaking_target() == "dad"


def test_bound_host_is_used(monkeypatch):
    monkeypatch.setattr(pe, "_HOST", dict.fromkeys(pe._HOST))
    subs, target = [], {"v": "audience"}

    async def profile():
        return {"custom_name": "E5"}

    async def run():
        q = asyncio.Queue()
        pe.bind_host(update_subtitle=subs.append, speech_queue=q, get_user_profile=profile,
                     get_speaking_target=lambda: target["v"])
        await pe._show_subtitle("🎹 晴天")
        await pe._say({"text": "來了"})
        return q, await pe._user_profile()
    q, prof = asyncio.run(run())
    assert subs == ["🎹 晴天"] and q.get_nowait() == {"text": "來了"} and prof == {"custom_name": "E5"}
    assert pe.get_current_speaking_target() == "audience"
    target["v"] = "dad"
    assert pe.get_current_speaking_target() == "dad"                      # 每次現問，不是綁定當下的值


def test_piano_engine_no_longer_reads_main_module():
    src = open(os.path.join(ROOT, "services", "piano_engine.py"), encoding="utf-8").read()
    assert "import __main__" not in src and "class MainProxy" not in src and "main_obj" not in src
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    assert "pe.bind_host(" in main and "pe.GEMINI_KEYS =" not in main
    assert pe.get_piano_gemini_keys() is le.GEMINI_KEYS                    # 同一份金鑰清單


def test_pingpong_helpers_live_in_llm_engine():
    assert [le.get_pingpong_alternating_index(5, s) for s in range(5)] == [0, 4, 1, 3, 2]
    assert sorted(le.get_pingpong_ring_indices(5, 1)) == [0, 1, 2, 3, 4]
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    assert "def get_pingpong_alternating_index(" not in main and "def get_pingpong_ring_indices(" not in main


def test_services_do_not_reach_back_into_main():
    """翻唱、看片以前從 sys.modules 撈主程式、或 from vts_7L_test import（2026-10-25 健檢）：改成 main() 用 bind_host 交進來。"""
    import glob
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    for f in glob.glob(os.path.join(root, "services", "*.py")) + glob.glob(os.path.join(root, "core", "*.py")):
        src = open(f, encoding="utf-8").read()
        if re.search(r"^\s*(from vts_7L_test import|import vts_7L_test|import __main__)|sys\.modules\.get\(\"(vts_7L_test|__main__)\"\)",
                     src, re.M):
            bad.append(os.path.basename(f))
    assert not bad, bad
    main = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    for call in ("pe.bind_host(", "auto_cover.bind_host(", "video_watch.bind_host("):
        assert call in main
