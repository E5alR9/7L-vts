# -*- coding: utf-8 -*-
"""翻唱排隊調度模擬：樁掉重活（下載/分離/RVC/播放），驗證不斷歌、不重複、不並發演唱。"""
import sys, os, asyncio
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.auto_cover_pipeline as acp

EVENTS = []
SLIPS = []
FAIL_TITLES = {"壞掉的歌"}


async def fake_prepare(title):
    EVENTS.append(f"prepare_start:{title}")
    await asyncio.sleep(0.2)
    if title in FAIL_TITLES:
        EVENTS.append(f"prepare_fail:{title}")
        return None, None
    EVENTS.append(f"prepare_done:{title}")
    return f"/tmp/{title}_vocal.wav", f"/tmp/{title}_inst.wav"


async def fake_play(vocal, title, inst_path=None):
    EVENTS.append(f"play_start:{title}")
    acp.IS_SINGING_ACTIVE = True
    await asyncio.sleep(1.0)  # 刻意播久一點，逼出「唱歌中開新準備」
    acp.IS_SINGING_ACTIVE = False
    EVENTS.append(f"play_end:{title}")


async def fake_wait_intro():
    return None


def fake_slip(text):
    SLIPS.append(text)
    return True


async def main():
    acp.prepare_cover_song = fake_prepare
    acp.play_cover_audio = fake_play
    acp.wait_for_intro_speech_complete = fake_wait_intro
    acp._send_brain_slip = fake_slip

    # --- 場景 1：A 立刻開工，B/C 排隊；同步段零競態（orch 只跑完迭代#1） ---
    m1 = acp.request_cover_song("歌A", "老爸")
    assert "背景準備好就開唱" in m1, m1
    await asyncio.sleep(0.05)  # 只放行 orch 迭代#1（pop A 開準備）；準備要 0.2s，READY 還空
    m2 = acp.request_cover_song("歌B", "觀眾甲")
    assert "排入點歌隊列" in m2 and "下一首就輪到它" in m2, m2
    m3 = acp.request_cover_song("歌C", "觀眾乙")
    assert "前面還有 1 首" in m3, m3  # QUEUE=[B]+C，READY 還空：0+2-1
    mdup = acp.request_cover_song("歌B ", "觀眾丙")  # 尾空白也算重複
    assert "不重複排入" in mdup, mdup
    # --- 場景 2：隊列滿額（B,C + 歌4,5,6 = 5 首待播，歌7/歌滿被拒） ---
    got_full = []
    for i in range(4, 8):
        m = acp.request_cover_song(f"歌{i}", "洗版仔")
        if "隊列滿了" in m:
            got_full.append(f"歌{i}")
    assert got_full == ["歌7"], got_full
    mfull = acp.request_cover_song("歌滿", "洗版仔")
    assert "隊列滿了" in mfull, mfull
    # --- 並行生效：等 A 開唱，B 必須在 A 播完前就開工（事件序斷言） ---
    await asyncio.sleep(0.8)
    ev = list(EVENTS)
    assert "prepare_start:歌B" in ev, ev
    assert "play_end:歌A" not in ev, ev  # A 還在唱，B 已經開工

    # 放行全部跑完
    for _ in range(200):
        if (not acp.SONG_REQUEST_QUEUE and not acp.READY_SONGS
                and not acp._stage_busy()
                and (acp._ORCH_TASK is None or acp._ORCH_TASK.done())
                and (acp._PREPARE_TASK is None or acp._PREPARE_TASK.done())):
            break
        await asyncio.sleep(0.1)

    plays = [e.split(":")[1] for e in EVENTS if e.startswith("play_start")]
    assert plays == ["歌A", "歌B", "歌C", "歌4", "歌5", "歌6"], plays
    # 演唱絕不重疊
    depth, mx = 0, 0
    for e in EVENTS:
        if e.startswith("play_start"):
            depth += 1
            mx = max(mx, depth)
        elif e.startswith("play_end"):
            depth -= 1
    assert mx == 1, f"concurrent play! {EVENTS}"
    # 謝幕紙條每首一張＋帶排隊深度
    assert len([s for s in SLIPS if "演唱完畢" in s]) == 6, SLIPS
    assert any("後面還有" in s for s in SLIPS), SLIPS
    assert acp._ORCH_TASK is None or acp._ORCH_TASK.done(), "orchestrator leaked"

    # --- 場景 3：唱到一半喊停 → 清空＋遲到準備丟棄 ---
    EVENTS.clear(); SLIPS.clear()
    acp.request_cover_song("長歌", "老爸")
    await asyncio.sleep(0.05)
    acp.request_cover_song("下一首", "觀眾甲")
    await asyncio.sleep(0.35)  # 此時長歌還在準備（0.2s）或剛備好，下一首躺在隊列；喊停要全清
    acp.stop_singing()
    await asyncio.sleep(0.6)
    late_plays = [e for e in EVENTS if e.startswith("play_start") and "下一首" in e]
    assert not late_plays, f"stopped song still played: {EVENTS}"
    assert not acp.SONG_REQUEST_QUEUE and not acp.READY_SONGS, "queue not cleared"

    # --- 場景 4：準備失敗 → 遞紙條＋不卡住後面 ---
    EVENTS.clear(); SLIPS.clear()
    acp.request_cover_song("壞掉的歌", "觀眾乙")
    acp.request_cover_song("好歌", "觀眾丙")
    for _ in range(200):
        if (not acp.SONG_REQUEST_QUEUE and not acp.READY_SONGS
                and not acp._stage_busy()
                and (acp._ORCH_TASK is None or acp._ORCH_TASK.done())
                and (acp._PREPARE_TASK is None or acp._PREPARE_TASK.done())):
            break
        await asyncio.sleep(0.1)
    assert any("準備失敗" in s for s in SLIPS), SLIPS
    assert any(e == "play_start:好歌" for e in EVENTS), EVENTS

    print("SING QUEUE SIM: ALL OK")
    print(f"  plays={len([e for e in EVENTS if e.startswith('play_start')])} slips={len(SLIPS)}")


asyncio.run(main())
