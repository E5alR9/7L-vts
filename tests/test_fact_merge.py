# -*- coding: utf-8 -*-
"""知識庫的事實會更新，不只會累加（core/fact_merge，2026-11-01）。"""
import asyncio

import core.fact_merge as fm


FACTS = ["老爸最喜歡喝無糖綠茶", "老爸生日是 1 月 9 號", "老爸在寫 7L 的程式", "老爸不吃香菜"]


def test_candidates_find_related_facts_only():
    assert fm.candidates("其實老爸最喜歡喝紅茶", FACTS)[0] == 0
    assert fm.candidates("我最喜歡喝無糖綠茶", FACTS) == [0]
    assert fm.candidates("老爸養了一隻貓叫咪咪", FACTS) == []


def test_parse_decision():
    cand = [0, 3]
    assert fm.parse_decision('{"op": "update", "index": 1, "merged": "老爸最喜歡喝紅茶"}', cand, FACTS) == ("update", 0, "老爸最喜歡喝紅茶")
    assert fm.parse_decision('{"op": "update", "index": 2, "merged": "老爸不吃香菜和蔥"}', cand, FACTS) == ("update", 3, "老爸不吃香菜和蔥")
    assert fm.parse_decision('{"op":"skip","index":null,"merged":""}', cand, FACTS) == ("skip", None, "")
    assert fm.parse_decision('{"op": "update", "index": 9, "merged": "x"}', cand, FACTS)[0] == "add"   # 編號亂填：當新增
    assert fm.parse_decision("看不懂", cand, FACTS)[0] == "add"


def test_saving_updates_instead_of_piling_up(monkeypatch):
    import core.memory as mem
    store = {"learned_facts": list(FACTS)}

    async def get_kn():
        return store

    async def save_kn(kn):
        store.update(kn)

    async def decide(new, facts):
        if "紅茶" in new:
            return "update", 0, "老爸最喜歡喝紅茶（以前是無糖綠茶）"
        if "無糖綠茶" in new:
            return "skip", None, ""
        return "add", None, ""
    monkeypatch.setattr(mem, "get_cloud_knowledge", get_kn)
    monkeypatch.setattr(mem, "save_cloud_knowledge", save_kn)
    monkeypatch.setattr(fm, "reconcile", decide)
    asyncio.run(mem.update_cloud_prompt_field("facts", "我最喜歡喝無糖綠茶"))
    assert store["learned_facts"] == FACTS                                           # 重複：不存
    asyncio.run(mem.update_cloud_prompt_field("facts", "其實我最喜歡喝紅茶"))
    assert store["learned_facts"][0] == "老爸最喜歡喝紅茶（以前是無糖綠茶）" and len(store["learned_facts"]) == 4
    asyncio.run(mem.update_cloud_prompt_field("facts", "老爸養了一隻貓"))
    assert store["learned_facts"][-1] == "老爸養了一隻貓" and len(store["learned_facts"]) == 5


def test_groq_down_falls_back_to_add(monkeypatch):
    import core.groq_router as gr

    async def dead(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(gr, "groq_chat", dead)
    assert asyncio.run(fm.reconcile("其實老爸最喜歡喝紅茶", FACTS)) == ("add", None, "")
