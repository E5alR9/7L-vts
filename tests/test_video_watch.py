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


def test_video_being_watched_is_not_queued_again():
    """第一筆被 worker 拿走後，主腦換個網址寫法再點一次，同一部片看兩遍講兩遍（2026-10-25 實機）。"""
    vw.WATCH_QUEUE, vw.WATCH_HISTORY[:] = None, []
    assert asyncio.run(request_watch("https://www.youtube.com/watch?v=jNQXAC9IVRw", "E5"))["queued"] is True
    vw.WATCH_QUEUE.get_nowait()                    # worker 拿走開始看
    assert asyncio.run(request_watch("youtube.com/watch?v=jNQXAC9IVRw", "老爸"))["queued"] is False
    vw.WATCH_HISTORY[-1]["at"] -= vw.REWATCH_GAP_SEC + 1
    assert asyncio.run(request_watch("youtu.be/jNQXAC9IVRw", "E5"))["queued"] is True   # 隔夠久可以再看


def test_frames_are_described_as_video_not_the_owners_screen():
    """抽幀用看螢幕的提示詞，摘要冒出「這並非老爸操作電腦螢幕的畫面」（2026-10-25 實機）。"""
    import ast, os
    assert "螢幕" not in vw.FRAME_PROMPT.replace("不要提電腦螢幕", "")
    src = open(os.path.join(ROOT, "services", "video_watch.py"), encoding="utf-8").read()
    assert "look(b64, prompt=FRAME_PROMPT)" in src
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(main)) if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "get_lightweight_gemini_vision")
    assert "prompt" in [a.arg for a in fn.args.args]


def test_watch_note_is_not_shown_as_a_viewer_comment():
    import os
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    import ast, types
    seen = []

    async def request_watch(url, requester="觀眾"):
        seen.append(requester)
        return {"ok": True, "queued": True}
    fn = next(n for n in ast.walk(ast.parse(main)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute_tool_dispatch")
    from core.hard_command import is_stage_control
    ns = {"_AUDIENCE_DENIED_TOOLS": frozenset(), "is_stage_control": is_stage_control, "log_print": lambda *a: None,
          "video_watch": types.SimpleNamespace(request_watch=request_watch)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "x", "exec"), ns)
    for target, user in (("dad", ""), ("audience", ""), ("audience", "小明")):
        asyncio.run(ns["execute_tool_dispatch"]("video.request_watch", {"url": "youtu.be/jNQXAC9IVRw"},
                                                caller_target=target, caller_user=user))
    assert seen == ["老爸", "觀眾", "小明"]            # 子智能體不帶名字時照身分記，不再一律「觀眾」
