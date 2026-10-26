# -*- coding: utf-8 -*-
"""情境測試（2026-10-26）：用乾跑包裝（tests/dryrun.py）把一整串跑過一次——
輸入 → 分派 → 看板／紙條 → 主腦 → 子智能體／舞台指令 → 說話佇列。AI 和硬體是假的，其他是主程式原樣。
以前這些都只能開實機、等兩三分鐘、用 /call 戳。"""
import asyncio

from dryrun import DryRun, FakeBrain


def run(coro):
    return asyncio.run(coro)


def test_dad_types_a_song_live_brain_up():
    """老爸打字「彈小星星」，Live 在線：CPU 硬指令直接派給鋼琴（點播的是老爸）、罐頭應答排進說話佇列、
    紙條照老爸身分給 Live 主腦。"""
    async def go():
        async with DryRun(live=True) as d:
            await d.dad("彈小星星")
            await d.settle(1.0)
            return d
    d = run(go())
    assert d.tools == [("pe.play_virtual_piano", {"song_name": "小星星"}, "dad", "老爸")]
    assert any("小星星" in x["text"] for x in d.speech)                       # 罐頭應答
    dad_slips = [s for s in d.slips if s[1] == "dad"]
    assert dad_slips == [("[黑板同步] 老爸傳來文字訊息：彈小星星", "dad", "彈小星星", "")]
    assert any(m["content"] == "彈小星星" and m["role"] == "user" for m in d.memory)
    assert d.problems == []


def test_viewer_cannot_put_the_piano_away():
    """觀眾說「收起鋼琴」：CPU 不幫觀眾停鋼琴；看板哨兵把留言轉給主腦時是觀眾身分、帶名字。"""
    async def go():
        async with DryRun(live=True) as d:
            await d.viewer("阿呆", "7L 收起鋼琴啦")
            await d.settle(1.5)
            return d
    d = run(go())
    assert d.tools == []
    assert [s[1:] for s in d.slips] == [("audience", "7L 收起鋼琴啦", "阿呆")]
    assert "阿呆" in d.slips[0][0]
    assert d.problems == []


def test_owner_account_in_chat_speaks_as_dad():
    """老爸用自己的直播帳號留言（平台帳號對得上）：當老爸處理，不當觀眾。"""
    async def go():
        async with DryRun(live=True) as d:
            await d.viewer("E5", "大家晚安", uid="dad_uid")
            await d.settle(1.0)
            return d
    d = run(go())
    assert [s[:2] for s in d.slips] == [("[文字輸入] 老爸 (在直播間留言)：大家晚安", "dad")]
    assert d.problems == []


def test_without_live_the_rest_brain_answers_and_relays_the_search():
    """Live 斷線很久：老爸的紙條由 REST 大腦接；她叫子智能體查天氣、先答應一聲，結果回來再講。"""
    brain = FakeBrain(("", [("invoke_subagent", {"task_instruction": "查明天台北天氣", "action": "other"})]),
                      ("好，我去查！", []), ("明天台北晴天，記得防曬喔！", []))

    async def go():
        async with DryRun(live=False, brain=brain, subagent=("report", "[搜尋結果：明天台北晴]")) as d:
            await d.dad("幫我查明天台北天氣")
            await d.settle(2.0)
            return d
    d = run(go())
    assert d.slips == []                                                      # 沒留給 Live
    assert d.subagent_tasks == [("查明天台北天氣", "dad", "老爸")]
    assert [x["text"] for x in d.speech] == ["好，我去查！", "明天台北晴天，記得防曬喔！"]
    assert all(x["target"] == "dad" and x["private"] for x in d.speech)
    assert brain.calls[0][2] is True and "[搜尋結果：明天台北晴]" in brain.calls[2][1]
    assert d.problems == []


def test_rest_brain_cannot_replay_an_old_song_request():
    """老爸只是說早安，REST 大腦卻想彈之前點過的晴天：擋下來、不派鋼琴，請她改口。"""
    brain = FakeBrain(("好喔，來彈晴天～", [("invoke_subagent", {"task_instruction": "彈晴天", "action": "play_piano",
                                                                 "song": "晴天"})]),
                      ("早安老爸！", []))

    async def go():
        async with DryRun(live=False, brain=brain) as d:
            await d.dad("7L 早安")
            await d.settle(1.5)
            return d
    d = run(go())
    assert d.tools == []
    assert "沒有人點歌" in brain.calls[1][1] and "晴天" in brain.calls[1][1]
    assert [x["text"] for x in d.speech][-1] == "早安老爸！"
    assert d.problems == []


def test_vtuber_mode_viewer_gets_a_public_reply_from_the_board():
    """VTuber 模式（沒有 Live 主腦）：觀眾留言由看板直接叫 REST 回，對觀眾公開講（不是給老爸的私話）。"""
    brain = FakeBrain(("[EXPRESSION: 開心] 小明晚安～", []))

    async def go():
        async with DryRun(live=False, brain=brain, sentry={"should_speak": True, "target": "小明", "focus": "晚安"}) as d:
            await d.viewer("小明", "7L 晚安")
            await d.settle(1.5)
            return d
    d = run(go())
    assert [(x["text"], x["target"]) for x in d.speech] == [("小明晚安～", "audience")]
    assert "（看板提示詞：小明）" in brain.calls[0][0] and brain.calls[0][2] is False   # 看板不給工具
    assert any(m.get("role") == "assistant" and "小明晚安" in m["content"] for m in d.memory)
    assert d.problems == []


def test_sentry_silence_means_no_reply():
    async def go():
        async with DryRun(live=False, sentry={"should_speak": False, "raw": "[SILENCE]"}) as d:
            await d.viewer("路人", "666666")
            await d.settle(1.5)
            return d
    d = run(go())
    assert d.speech == [] and d.brain.calls == [] and d.problems == []


def test_system_slip_without_live_is_spoken_publicly():
    """沒有 Live 主腦時系統紙條（唱完謝幕）也有人接：REST 大腦講出來、公開。"""
    brain = FakeBrain(("謝謝大家聽我唱晴天～", []))

    async def go():
        async with DryRun(live=False, brain=brain) as d:
            d.slip("[系統提示：妳剛才演唱完畢了歌曲《晴天》，請自然地向老爸與觀眾謝幕]")
            await d.settle(1.5)
            return d
    d = run(go())
    assert [(x["text"], x["target"], x["private"]) for x in d.speech] == [("謝謝大家聽我唱晴天～", "audience", False)]
    assert d.problems == []


def test_dad_cuts_in_while_she_is_answering_viewers():
    """她正在回觀眾時老爸打字：排隊中的觀眾回話丟掉，給老爸的話照講。"""
    async def go():
        async with DryRun(live=True) as d:
            d.ns["CURRENT_SPEAKING_TARGET"] = "audience"
            q = d.ns["speech_queue"]
            q.put_nowait({"text": "小明晚安～", "target": "audience"})
            q.put_nowait({"text": "老爸等一下喔", "target": "dad"})
            q.put_nowait({"text": "阿呆你好", "target": "audience"})
            await d.dad("7L 先停一下，聽我說")
            await d.settle(0.5)
            return d
    d = run(go())
    assert [x["text"] for x in d.speech] == ["老爸等一下喔"]
    assert any("2 則觀眾回話不講了" in l for l in d.logs) and d.problems == []

