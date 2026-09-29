# -*- coding: utf-8 -*-
"""ACE-Step 作曲腿純函式測試（組請求＋未啟用安全跳過）"""
import asyncio
from conftest import ROOT  # noqa: F401
from services.acestep_music import build_request, generate_song, status


def test_build_request():
    r = build_request("抒情歌", lyrics="啦啦", duration=90, style="鋼琴")
    assert "鋼琴" in r["caption"] and r["lyrics"] == "啦啦" and r["duration"] == 90
    r2 = build_request("", duration=9999)
    assert r2["lyrics"] == "[Instrumental]" and r2["duration"] == 600
    r3 = build_request("x", duration=1)
    assert r3["duration"] == 10


def test_disabled_skips():
    import os
    os.environ["ACESTEP_ENABLED"] = "0"
    r = asyncio.run(generate_song("test"))
    assert r["ok"] is False
    s = status()
    assert s["enabled"] is False and s["alive"] is False
