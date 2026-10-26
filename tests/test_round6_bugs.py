# -*- coding: utf-8 -*-
"""2026-10-27 健檢找到的 bug：計時器中文數字、拒絕被當答應、搜尋備援、喚醒等級、看板平台標籤、電擊摸頭的紙條。"""
import asyncio
import ast
import os

from conftest import ROOT
from core.live_timer_sensor import LiveTimerSensorHub, cn_number
from core.hard_command import stage_request_unasked
import services.web_search as ws

MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
TREE = ast.parse(MAIN)


def _fn(name):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_timer_understands_multi_char_chinese_numbers():
    assert [cn_number(s) for s in ("五", "十", "十五", "二十", "二十五", "兩百", "一百二十", "三百零五")] == \
        [5, 10, 15, 20, 25, 200, 120, 305]
    assert cn_number("") is None and cn_number("幾") is None
    hub = LiveTimerSensorHub()
    assert hub.detect_timer_intent("十五分鐘後叫我")[0] == 900         # 以前算成 60
    assert hub.detect_timer_intent("二十秒後提醒我喝水") == (20, "喝水")
    assert hub.detect_timer_intent("半小時後叫我")[0] == 1800
    assert hub.detect_timer_intent("5分鐘後叫我吃藥") == (300, "吃藥")


def test_refusing_her_offer_is_not_a_song_request():
    her = "要不要我彈小星星給你聽？"
    for no in ("不要", "不用了", "不行", "算了", "改天吧"):
        assert stage_request_unasked(no, ["小星星"], her_last=her) is True, no
    for yes in ("好啊", "可以", "要", "來啊"):
        assert stage_request_unasked(yes, ["小星星"], her_last=her) is False, yes


def test_search_falls_back_to_duckduckgo_when_tavily_fails(monkeypatch):
    class Dead:
        def search(self, **kw):
            return {"error": "All Tavily keys failed or exceeded quota"}

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, q, max_results=3):
            return [{"title": "天氣", "body": "台北明天晴"}]

    import sys
    import types
    monkeypatch.setattr(ws, "tavily_client", Dead())
    monkeypatch.setitem(sys.modules, "duckduckgo_search", types.SimpleNamespace(DDGS=FakeDDGS))
    assert ws.search_google("台北明天天氣") == "- 天氣: 台北明天晴"   # 以前回 "{'error': ...}"


def test_live_search_passes_tavily_options_by_name():
    src = ast.get_source_segment(MAIN, _fn("live_search_tool_task"))
    assert 'search_depth="basic", topic="general"' in src


def test_medium_screen_change_wakes_her():
    src = ast.get_source_segment(MAIN, _fn("autonomous_wander_worker"))
    assert '"medium"' not in src and '("med", "high")' in src


def test_board_batch_labels_each_platform():
    ns = {"is_operator": lambda s: False, "_PLATFORM_LABEL": {"twitch": "Twitch", "youtube": "YouTube"}}
    exec(compile(ast.Module(body=[_fn("_format_board_batch")], type_ignores=[]), "x", "exec"), ns)
    text, viewers, _ = ns["_format_board_batch"]([
        {"unique_id": "a", "user": "阿呆", "source": "twitch", "time_str": "21:00", "content": "嗨"},
        {"unique_id": "b", "user": "路人", "source": "youtube", "time_str": "21:01", "content": "安"},
        {"unique_id": "c", "user": "小明", "source": "tiktok", "time_str": "21:02", "content": "哈"}])
    assert "【Twitch 直播觀眾「阿呆」】" in text and "【YouTube 直播觀眾「路人」】" in text
    assert "【TikTok 直播觀眾「小明」】" in text and viewers == ["阿呆", "路人", "小明"]


def test_shock_and_pat_go_to_the_brain_as_slips_not_as_dad_typing():
    for name in ("execute_punish_action", "execute_reward_action"):
        src = ast.get_source_segment(MAIN, _fn(name))
        assert '"source": "web_console"' not in src and "send_brain_slip(" in src, name


def test_timer_detect_returns_none_for_unknown_numbers():
    assert LiveTimerSensorHub().detect_timer_intent("幾分鐘後叫我") is None


def test_related_memories_has_one_overall_timeout(monkeypatch):
    import services.rag_memory_service as rag

    async def slowish(q, top_k=3, where=None):
        await asyncio.sleep(0.04)
        return []

    monkeypatch.setattr(rag, "search_rag_memory", slowish)
    monkeypatch.setattr(rag, "latest_viewer_lines", lambda v, q="": [])
    # 三次查詢各 0.04 秒，總時限 0.06 秒：整段超時、回空字串
    assert asyncio.run(rag.related_memories_block("我之前講過的貓咪小故事", viewers=["小明"], timeout=0.06)) == ""
