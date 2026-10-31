"""做夢整理（老爸 2026-10-31）：閒著時把對話整理成日記、知識去重。"""
import asyncio
import json

import core.dream as D

T0 = 1793440000.0   # 2026-10-31 17:46（台北）


def _it(t, who, text, role="user", target="7L"):
    return {"time": t, "speaker": who, "target": target, "content": text, "role": role, "source": "text"}


def test_only_new_dialogue_is_taken_and_thoughts_are_left_out():
    items = [_it(T0, "老爸", "舊的"), _it(T0 + 10, "老爸", "幫我查天氣"),
             _it(T0 + 11, "7L", "我想想", role="thought", target="內心流動"), _it(T0 + 12, "7L", "好喔", role="assistant")]
    got = D.new_dialogue(items, T0 + 1)
    assert [i["content"] for i in got] == ["幫我查天氣", "好喔"]


def test_chunks_split_by_day_and_size_and_remember_the_last_time():
    day2 = T0 + 8 * 3600   # 跨過午夜
    items = [_it(T0 + i, "老爸", "x" * 50) for i in range(5)] + [_it(day2, "小明", "晚安")]
    chunks = D.by_day_chunks(items, max_chars=150)
    assert [c[0] for c in chunks] == ["2026-10-31", "2026-10-31", "2026-10-31", "2026-11-01"]
    assert all(len(c[1]) <= 150 for c in chunks) and chunks[-1][2] == day2 and "小明" in chunks[-1][1]


def test_knowledge_dedupe_only_removes_duplicates():
    kn = {"memes_and_slang": ["原地起飛（操作天秀）", "笑死（很好笑）", "原地起飛（萬物皆可失控）", "太狠了 (霸氣)", "太狠了（強悍）"],
          "learned_facts": ["老爸喜歡咖啡", "老爸 喜歡咖啡。", "老爸住台北"], "banned_phrases": ["請問還有什麼"],
          "persona_core": "不動"}
    new, removed = D.dedupe_knowledge(kn)
    assert new["memes_and_slang"] == ["原地起飛（操作天秀）", "笑死（很好笑）", "太狠了 (霸氣)"]
    assert new["learned_facts"] == ["老爸喜歡咖啡", "老爸住台北"] and new["persona_core"] == "不動"
    assert set(removed) == {"memes_and_slang", "learned_facts"}
    assert D.dedupe_knowledge({"learned_facts": ["a", "b"]})[1] == {}


def test_when_to_dream():
    now = T0 + 10000
    assert D.should_dream(now, 0, 40, 700, False).startswith("閒了")
    assert D.should_dream(now, 0, 40, 100, False) == ""                  # 還沒閒夠
    assert D.should_dream(now, 0, 10, 9999, False) == ""                 # 新對話太少
    assert D.should_dream(now, 0, 300, 0, False).startswith("新對話")    # 快被擠掉：不等閒著
    assert D.should_dream(now, 0, 300, 9999, True) == ""                 # 睡著不做（睡覺保證不呼叫 AI）
    assert D.should_dream(now, now - 60, 300, 9999, False) == ""         # 剛整理過


def test_diary_block_for_the_brain():
    d = {"days": {"2026-10-29": "老爸教我彈卡農", "2026-10-30": "", "2026-10-31": "小明說他是頭號粉絲"}}
    block = D.diary_block(d, today="2026-10-31")
    assert "10/29：老爸教我彈卡農" in block and "今天：小明說他是頭號粉絲" in block and "10/30" not in block
    assert D.diary_block({"days": {}}) == ""


def test_dream_once_writes_the_diary_and_only_advances_what_was_written(tmp_path, monkeypatch):
    path = str(tmp_path / "diary.json")
    monkeypatch.setattr(D, "diary_file", lambda: path)
    calls = []

    async def merge(existing, chat, date):
        calls.append((existing, date))
        return "" if date == "2026-11-01" else f"{existing}+日記({chat.count(chr(10)) + 1}句)"
    monkeypatch.setattr(D, "merge_into_diary", merge)
    import core.memory as mem
    from types import SimpleNamespace
    saved = []

    async def kn():
        return {"learned_facts": ["a", "a"]}

    async def save(k):
        saved.append(k)

    async def add(*a, **k):
        saved.append(("rag", a, k))
    monkeypatch.setattr(mem, "get_cloud_knowledge", kn)
    monkeypatch.setattr(mem, "save_cloud_knowledge", save)
    monkeypatch.setattr(mem, "_RAG", SimpleNamespace(add_rag_memory=add))
    items = [_it(T0 + i, "老爸", f"第{i}句") for i in range(3)] + [_it(T0 + 8 * 3600, "小明", "隔天的")]
    res = asyncio.run(D.dream_once(items, "測試"))
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["days"]["2026-10-31"] == "+日記(3句)" and "2026-11-01" not in data["days"]
    assert data["last_ts"] == T0 + 2                         # 隔天那段沒寫成：下次再整理
    assert res["days"] == ["2026-10-31"] and res["removed"] == {"learned_facts": ["a"]}
    assert {"learned_facts": ["a"]} in saved and any(s[0] == "rag" and s[2]["source"] == "diary" for s in saved if isinstance(s, tuple))
    asyncio.run(D.dream_once(items, "再一次"))               # 已整理的不重寫，只補沒寫成的那天
    assert calls[-1] == ("", "2026-11-01")


def test_brain_prompt_carries_the_diary_and_the_worker_is_started():
    from conftest import MAIN_SRC
    assert "diary = dream.diary_block()" in MAIN_SRC and "spawn(dream.dream_worker(_idle_seconds))" in MAIN_SRC


def test_repeated_paragraphs_and_sentences_are_dropped():
    """2026-10-31 實測：模型併日記時把同兩段抄了兩次。"""
    t = "老爸讓我彈小星星。我很開心！\n小駭客想刪檔案。我生氣了。\n老爸讓我彈小星星。我很開心！\n小駭客想刪檔案。晚上老爸摸頭。"
    assert D.drop_repeats(t) == "老爸讓我彈小星星。我很開心！\n小駭客想刪檔案。我生氣了。\n晚上老爸摸頭。"


def test_long_diary_is_clipped_at_a_sentence_end():
    t = "老爸讓我彈琴。" * 10 + "最後老爸問台北天氣，降雨機率只有兩成"
    out = D.clip_at_sentence(t, 75)
    assert out.endswith("。") and len(out) <= 75
    assert D.clip_at_sentence("短的", 75) == "短的"


def test_first_start_only_dreams_about_what_happens_from_now_on(tmp_path, monkeypatch):
    """以前的時間線混著測試對話：第一次啟用從現在開始記。"""
    path = str(tmp_path / "diary.json")
    monkeypatch.setattr(D, "diary_file", lambda: path)
    monkeypatch.setattr(D, "DREAM_CHECK_SEC", 3600)

    async def go():
        t = asyncio.create_task(D.dream_worker(lambda: 0.0))
        await asyncio.sleep(0.05)
        t.cancel()
    import time as _t
    before = _t.time()
    asyncio.run(go())
    assert D.load_diary()["last_ts"] >= before
