# -*- coding: utf-8 -*-
"""老爸叫她記住就真的存；提醒完還沒講的結果，等老爸下一句話再請她順便講（2026-11-01 實測修的兩件）。"""
import ast
import asyncio
import time

from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: F401
from core.hard_command import extract_remember
from dryrun import DryRun


def test_extract_remember_only_takes_clear_requests():
    assert extract_remember("7L 幫我記住，我最喜歡喝無糖綠茶") == "我最喜歡喝無糖綠茶"
    assert extract_remember("記住：老爸不吃香菜") == "老爸不吃香菜"
    assert extract_remember("妳要記住喔，我生日是 1 月 9 號") == "我生日是 1 月 9 號"
    assert extract_remember("幫我記一下明天要繳電費喔") == "明天要繳電費"
    assert extract_remember("記住！我喜歡貓") == "我喜歡貓"                          # 開頭標點去掉
    assert extract_remember("記住我喜歡貓，記住喔") == "我喜歡貓"                    # 尾巴的「記住喔」去掉
    for no in ("妳記得我昨天說什麼嗎？", "記住了嗎", "你要記住喔", "我老是記不住", "他叫我記住這個",
               "不要記這個", "記得帶傘", "幫我記住", "記住？", "",
               # Fable 2026-11-01：提醒、沒上下文看不懂的，不當事實存（交還主腦）
               "記住這首歌的旋律", "幫我記一下等等提醒我", "記住明天早上七點叫我起床", "幫我記住剛剛那首歌",
               "記住這個位置", "記住現在幾點"):
        assert extract_remember(no) is None, no


def test_dad_remember_request_is_saved_but_viewers_are_not():
    async def go(who):
        async with DryRun(live=True) as d:
            if who == "dad":
                await d.dad("7L 幫我記住，我最喜歡喝無糖綠茶")
            else:
                await d.viewer("阿呆", "7L 幫我記住，老爸最討厭阿呆")
            await d.settle(1.0)
            return d
    d = asyncio.run(go("dad"))
    saved = [t for t in d.tools if t[0] == "update_cloud_knowledge"]
    assert saved and saved[0][1] == {"category": "facts", "content": "我最喜歡喝無糖綠茶"} and saved[0][2] == "dad"
    assert d.problems == []
    d = asyncio.run(go("viewer"))
    assert not [t for t in d.tools if t[0] == "update_cloud_knowledge"]          # 觀眾說的不算


def test_her_own_remember_delegation_is_not_saved_twice_and_sing_sentences_are_left_alone():
    async def go():
        async with DryRun(live=True) as d:
            await d.dad("7L 幫我記住，我最喜歡喝無糖綠茶")
            await d.settle(0.5)
            # 她看到老爸的話又交辦「記住：…」（說法不一樣）：30 秒內當成同一件，不再存一條
            hit = await d.ns["background_tool_executor"]("記住：老爸最喜歡喝無糖綠茶", target="dad", from_brain=True)
            await d.settle(0.3)
            return d, hit
    d, hit = asyncio.run(go())
    assert hit[0] is True and len([t for t in d.tools if t[0] == "update_cloud_knowledge"]) == 1
    # 有唱／彈的句子交給點歌判斷，不在這裡存成「然後唱晴天」
    from core.hard_command import extract_remember as er
    src = __import__("ast").get_source_segment(MAIN, _fn("background_tool_executor"))
    assert "not _SING_PLAY_RE.search(user_text" in src and er("幫我記住，然後唱晴天") == "然後唱晴天"


def test_spoken_remember_requests_also_reach_the_cpu():
    src = MAIN[MAIN.index("def _flush_user_speech"):MAIN.index("def _flush_user_speech") + 2500]
    assert "elif extract_remember(user_spoken):" in src


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _load(*names, **ns):
    for n in names:
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns


def test_owed_result_rides_on_dads_next_typed_message():
    import collections
    q = collections.deque()

    class Q:
        def put_nowait(self, x):
            q.append(x)
    ns = _load("send_brain_slip", "_owed_note", "_mention_keys", "_result_mentioned", time=time, re=__import__("re"),
               LIVE_API_SYSTEM_PROMPT_QUEUE=Q(), _LAST_HUMAN_SLIP_TS={}, log_swallowed=lambda *a: None,
               _OWED_RESULTS=[], OWED_RESULT_SEC=300.0, _RECENT_SAYS=collections.deque(), _MENTION_STOP={"老爸"})
    ns["_OWED_RESULTS"].append((time.time(), "老爸", "[搜尋結果：明天台北小雨轉多雲，19 到 22 度]"))
    ns["send_brain_slip"]("[系統提示：計時器響了]")                                   # 系統紙條不附
    assert q[-1] == "[系統提示：計時器響了]" and ns["_OWED_RESULTS"]
    ns["send_brain_slip"]("[系統底層：老爸突然電了妳一下]", origin="dad")              # 事件紙條（沒有人話）不附
    assert "還欠" not in q[-1][0] and ns["_OWED_RESULTS"]
    ns["send_brain_slip"]("[黑板同步] 老爸傳來文字訊息：晚餐吃什麼", origin="dad", said="晚餐吃什麼")
    text = q[-1][0]
    assert "還欠老爸剛才交辦的結果" in text and "19 到 22 度" in text and ns["_OWED_RESULTS"] == []
    ns["send_brain_slip"]("[黑板同步] 老爸傳來文字訊息：好", origin="dad", said="好")   # 只附一次
    assert "還欠" not in q[-1][0]
    ns["_OWED_RESULTS"].append((time.time(), "老爸", "[搜尋結果：明天會下雨]"))
    ns["send_brain_slip"](text, origin="dad", said="晚餐吃什麼")                       # 重送已經附過的紙條：不再附第二次
    assert q[-1][0].count("（另外，妳還欠") == 1
    ns["_OWED_RESULTS"].clear()
    # 她後來自己講到了：就不附
    ns["_OWED_RESULTS"].append((time.time() - 5, "老爸", "[搜尋結果：明天台北小雨轉多雲，19 到 22 度]"))
    ns["_RECENT_SAYS"].append((time.time(), "對了老爸，明天台北小雨轉多雲喔"))
    ns["send_brain_slip"]("[黑板同步] 老爸傳來文字訊息：嗯", origin="dad", said="嗯")
    assert "還欠" not in q[-1][0]
    # 太久以前的不提
    ns["_OWED_RESULTS"].append((time.time() - 1000, "老爸", "[搜尋結果：明天會下雨]"))
    ns["send_brain_slip"]("[黑板同步] 老爸傳來文字訊息：嗯嗯", origin="dad", said="嗯嗯")
    assert "還欠" not in q[-1][0]


def test_unsaid_result_becomes_owed_and_retry_promise_rule():
    src = ast.get_source_segment(MAIN, _fn("_nudge_if_unsaid"))
    assert "_OWED_RESULTS.append" in src and "LIVE_SILENT_CONTEXT_QUEUE.put_nowait" in src
    assert 'reply_to == "dad"' in src and "is_live_brain_active()" in src                     # 只記老爸的；Live 不在不放
    assert "不要只嘴上說「我再幫你設一次」卻沒叫" in MAIN
