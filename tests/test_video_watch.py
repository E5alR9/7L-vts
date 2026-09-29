# -*- coding: utf-8 -*-
"""點播看全片純函式測試（URL 正規化＋隊列去重）"""
import asyncio
from conftest import ROOT  # noqa: F401
from services.video_watch import normalize_video_url, max_minutes, frame_interval, request_watch
import services.video_watch as vw


def test_normalize_video_url():
    assert normalize_video_url("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert normalize_video_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert normalize_video_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert normalize_video_url("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert normalize_video_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert normalize_video_url("") == ""
    assert normalize_video_url("https://www.youtube.com/@LofiGirl") == ""
    assert normalize_video_url("not a url at all!!!") == ""


def test_env_defaults():
    assert max_minutes() >= 1
    assert frame_interval() >= 5


def test_request_watch_dedup():
    vw.WATCH_QUEUE = None
    r1 = asyncio.run(request_watch("https://youtu.be/dQw4w9WgXcQ", requester="甲"))
    assert r1["ok"] and r1["queued"] is True
    r2 = asyncio.run(request_watch("dQw4w9WgXcQ", requester="乙"))
    assert r2["ok"] and r2["queued"] is False
    r3 = asyncio.run(request_watch("嗯嗯", requester="丙"))
    assert r3["ok"] is False
