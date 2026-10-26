# -*- coding: utf-8 -*-
"""回話前查相關舊記憶（2026-10-26）：以前每句對話都存進向量庫（rag_memory_service.add_rag_memory），
從來沒有人查。現在老爸的紙條、觀眾的紙條、看板 REST 提示詞送出前都查一次，有就附上；
麥克風講的話轉寫到了就當背景資料補給主腦。挑法照實機量到的分數定（見 rag_memory_service 檔頭）。"""
import asyncio
import ast
import os
import re
import time
from datetime import datetime

import services.rag_memory_service as rag
from dryrun import DryRun

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
Q_CAT = "7L 我之前有問過妳貓跟狗哪個比較可愛，妳還記得我問過嗎？"


def _hit(text, score, age_sec):
    ts = datetime.fromtimestamp(time.time() - age_sec).isoformat()
    return {"text": f"[07:10:35] E5對7L說: {text}", "score": score, "metadata": {"source": "user", "timestamp": ts}}


def _bodies(picked):
    return [p["text"].split(": ", 1)[1] for p in picked]


def test_content_chars_drop_function_words():
    assert rag.content_chars("7L 幫我數到三") == {"數"}
    assert rag.content_chars("7L 早安") == {"早", "安"}
    assert rag.content_chars("彈 Hungarian Rhapsody No.2") == {"彈", "hungarian", "rhapsody", "no"}
    assert {"貓", "狗", "可", "愛"} <= rag.content_chars(Q_CAT)
    assert "前" not in rag.content_chars(Q_CAT)          # 「之前」整個拿掉


def test_pick_related_keeps_relevant_old_distinct_memories_only():
    hits = [
        _hit("跟我講一個關於貓咪的小故事", 0.73, 3 * 86400),       # 很像：直接收
        _hit("妳覺得貓跟狗哪個比較可愛？", 0.65, 2 * 86400),         # 普通像、有共同實詞：收
        _hit("妳覺得貓跟狗哪個比較可愛？", 0.64, 2 * 86400),         # 同一句存了兩份：去重
        _hit("7L 妳聽得到我嗎？回我一下", 0.66, 5 * 86400),          # 普通像、沒共同實詞（實機的噪音）：丟
        _hit("我也是", 0.48, 10 * 86400),                             # 分數不夠：丟
        _hit("剛剛說的貓叫咪咪", 0.80, 600),                          # 十分鐘前講的：她還記得，丟
        _hit(Q_CAT, 0.96, 2 * 86400),                                 # 跟這句一模一樣（以前問過同一句）：不算記憶
    ]
    assert _bodies(rag.pick_related(hits, Q_CAT)) == ["跟我講一個關於貓咪的小故事", "妳覺得貓跟狗哪個比較可愛？"]   # 照時間排
    assert _bodies(rag.pick_related(hits, Q_CAT, k=1)) == ["跟我講一個關於貓咪的小故事"]


def test_pick_related_skips_contentless_questions_even_with_lookalike_hits():
    """「幫我數到三」實機撈到「幫我想三個晚餐的選項」0.65、「給我 10000張 H100」0.67：都不是記憶。"""
    hits = [_hit("幫我想三個晚餐的選項", 0.65, 86400), _hit("給我 10000張 H100", 0.67, 86400)]
    assert rag.pick_related(hits, "7L 幫我數到三") == []
    assert rag.pick_related([_hit("7L 早安", 0.83, 86400)], "7L 早安") == []


def test_format_related_shows_date_and_strips_time_prefix():
    block = rag.format_related(rag.pick_related([_hit("跟我講一個關於貓咪的小故事", 0.73, 3 * 86400)], "我之前講過的貓咪小故事"))
    assert block.startswith("[相關的舊記憶（") and block.endswith("]")
    assert re.search(r"- \d\d/\d\d \d\d:\d\d E5對7L說: 跟我講一個關於貓咪的小故事", block)
    assert "[07:10:35]" not in block
    assert rag.format_related([]) == ""


def test_related_memories_block_never_blocks_the_reply(monkeypatch):
    calls = []

    async def slow(q, top_k=3):
        await asyncio.sleep(5)
        return [_hit("x", 0.9, 86400)]

    async def boom(q, top_k=3):
        raise RuntimeError("chroma 掛了")

    async def hits(q, top_k=3):
        calls.append(q)
        return [_hit("跟我講一個關於貓咪的小故事", 0.73, 3 * 86400)]

    q = "我之前講過的貓咪小故事妳還記得嗎"
    monkeypatch.setattr(rag, "search_rag_memory", slow)
    assert asyncio.run(rag.related_memories_block(q, timeout=0.05)) == ""
    monkeypatch.setattr(rag, "search_rag_memory", boom)
    assert asyncio.run(rag.related_memories_block(q)) == ""
    monkeypatch.setattr(rag, "search_rag_memory", hits)
    assert "關於貓咪的小故事" in asyncio.run(rag.related_memories_block(q))
    assert asyncio.run(rag.related_memories_block("7L 早安")) == "" and calls == [q]   # 沒內容的話連查都不查


MEM = "[相關的舊記憶（向量比對找的，可能不相關，自己判斷要不要提）：\n- 10/20 21:03 E5對7L說: 我家的貓叫咪咪]"


def test_dad_slip_carries_related_memories_live_and_rest():
    """老爸打字問舊事：Live 在線時紙條後面附舊記憶；Live 不在時 REST 大腦收到的也有。"""
    async def go(live):
        async with DryRun(live=live, related_memories=MEM) as d:
            await d.dad("我家的貓叫什麼？")
            await d.settle(1.0)
            return d
    d = asyncio.run(go(True))
    assert d.related_queries == ["我家的貓叫什麼？"]
    assert d.slips[0][0] == "[黑板同步] 老爸傳來文字訊息：我家的貓叫什麼？\n" + MEM
    assert d.slips[0][1:3] == ("dad", "我家的貓叫什麼？") and d.problems == []
    d = asyncio.run(go(False))
    assert any(MEM in user for _, user, _ in d.brain.calls) and d.problems == []


def test_viewer_slip_carries_related_memories_but_queries_only_the_words():
    async def go():
        async with DryRun(live=True, related_memories=MEM) as d:
            await d.viewer("阿呆", "7L 妳家貓咧")
            await d.settle(1.5)
            return d
    d = asyncio.run(go())
    assert d.related_queries == ["7L 妳家貓咧"]          # 查的是留言本文，不帶名字時間那些包裝
    assert len(d.slips) == 1 and MEM in d.slips[0][0] and d.slips[0][0].rstrip().endswith("]")
    assert d.slips[0][0].index(MEM) < d.slips[0][0].index("請妳綜合上述留言")   # 記憶在指示前面
    assert d.problems == []


def test_without_memories_slips_are_unchanged():
    async def go():
        async with DryRun(live=True) as d:
            await d.dad("早安")
            await d.settle(1.0)
            return d
    d = asyncio.run(go())
    assert d.slips[0][0] == "[黑板同步] 老爸傳來文字訊息：早安"


def test_rest_board_prompt_and_live_speech_also_look_up_memories():
    tree = ast.parse(MAIN)
    fn = next(x for x in ast.walk(tree) if isinstance(x, ast.AsyncFunctionDef) and x.name == "_streamer_mind_prompt")
    src = ast.get_source_segment(MAIN, fn)
    assert "related = await _related_memories_block(board_context)" in src and "{related}" in src
    flush = next(x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef) and x.name == "_flush_user_speech")
    assert "spawn(_related_context_for_speech(user_spoken))" in ast.get_source_segment(MAIN, flush)
    ctx = next(x for x in ast.walk(tree) if isinstance(x, ast.AsyncFunctionDef) and x.name == "_related_context_for_speech")
    assert "add_brain_context(" in ast.get_source_segment(MAIN, ctx)
