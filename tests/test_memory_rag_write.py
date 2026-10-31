# -*- coding: utf-8 -*-
"""哪些話進向量記憶庫（2026-10-26）：老爸的話（打字、麥克風、主持插話）、她的回覆、熟客（有觀眾檔的）的留言都存；
路人留言、系統事件、心想不存。以前只存老爸 text／voice 兩種來源，她查不到自己以前答過什麼、也查不到熟客說過什麼。"""
import asyncio

import core.memory as mem
import services.rag_memory_service as rag_service
from core.identity import get_owner_name


def _known(monkeypatch, *names):
    monkeypatch.setattr(mem, "_load_viewer_profiles", lambda: {n: {"call": n} for n in names})


def test_rag_memory_entry_rules(monkeypatch):
    _known(monkeypatch, "小明")
    f = mem.rag_memory_entry
    assert f("老爸", "7L", "彈小星星", "user", "text", "12:00:00") == ("[12:00:00] 老爸對7L說: 彈小星星", {"source": "user"})
    assert f("老爸", "7L", "妳喜歡貓還是狗？", "user", "web_console", "12:00:00")[0].endswith("妳喜歡貓還是狗？")
    assert f("老爸", "7L", "幫我數到三", "user", "mic", "12:00:00") is not None
    assert f("E5（主持）", "直播間", "大家晚安", "user", "owner_interject", "12:00:00") is not None
    # 她的回覆：拔表情標籤、對象 dad 換成老爸的名字
    her = f("7L", "dad", "[EXPRESSION: 思考] 貓咪還是狗狗喔... [EXPRESSION: 愛心] 我比較喜歡貓咪欸！ [WINK]", "assistant", "live_api", "11:50:53")
    assert her == (f"[11:50:53] 7L對{get_owner_name()}說: 貓咪還是狗狗喔... 我比較喜歡貓咪欸", {"source": "assistant"})
    assert f("7L", "觀眾「小明」", "[EXPRESSION: 正常] 明哥晚安～ [VIEWER_UPDATE:小明|CALL:明哥]", "assistant", "tts", "12:00:00")[0] \
        == "[12:00:00] 7L對觀眾「小明」說: 明哥晚安"
    # 熟客的留言：帶觀眾名、speaker 只留名字；路人不存
    assert f("TikTok 觀眾「小明」", "7L", "7L 以後叫我明哥", "user", "tiktok", "12:41:00") \
        == ("[12:41:00] 小明對7L說: 7L 以後叫我明哥", {"source": "user", "viewer": "小明", "viewer_key": "小明"})
    assert f("TikTok 觀眾「小明」", "老爸/直播間", "送了玫瑰", "user", "tiktok_gift", "12:00:00")[1]["viewer"] == "小明"
    assert f("TikTok 觀眾「路人甲」", "7L", "7L 晚安", "user", "tiktok", "12:00:00") is None
    # 不存：只剩標籤、系統事件、心想
    assert f("7L", "dad", "[EXPRESSION: 正常] [SILENCE]", "assistant", "live_api", "12:00:00") is None
    assert f("系統", "所有人", "鋼琴開始彈《小星星》", "system", "piano", "12:00:00") is None
    assert f("7L", "內心流動", "好無聊喔", "thought", "thought", "12:00:00") is None


def test_append_to_unified_memory_sends_dad_her_and_regulars_to_the_vector_store(monkeypatch):
    _known(monkeypatch, "小明")
    stored = []

    async def fake_add(text, source="dialogue", viewer="", viewer_key=""):
        stored.append((text.split("] ", 1)[1], source, viewer))

    monkeypatch.setattr(rag_service, "add_rag_memory", fake_add)

    async def go():
        mem.append_to_unified_memory(speaker="老爸", target="7L", content="妳喜歡貓還是狗？", role="user", source="web_console")
        mem.append_to_unified_memory(speaker="7L", target="dad", content="[EXPRESSION: 愛心] 我比較喜歡貓咪欸！",
                                     role="assistant", source="live_api")
        mem.append_to_unified_memory(speaker="TikTok 觀眾「小明」", target="7L", content="7L 以後叫我明哥", role="user", source="tiktok")
        mem.append_to_unified_memory(speaker="TikTok 觀眾「路人甲」", target="7L", content="7L 晚安", role="user", source="tiktok")
        mem.append_to_unified_memory(speaker="系統", target="所有人", content="鋼琴開始了", role="system", source="piano")
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert stored == [
        ("老爸對7L說: 妳喜歡貓還是狗？", "user", ""),
        (f"7L對{get_owner_name()}說: 我比較喜歡貓咪欸", "assistant", ""),
        ("小明對7L說: 7L 以後叫我明哥", "user", "小明"),
    ]
