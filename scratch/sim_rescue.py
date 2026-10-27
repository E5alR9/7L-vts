# -*- coding: utf-8 -*-
"""斷線救援端到端模擬：重演 2026-10-09「唱 5:20am」紙條送達→session死亡→重連撿回。"""
import sys, os, asyncio
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.hard_command import parse_slip_for_song, build_slip_text
import services.auto_cover_pipeline as acp

PLAYED = []
SLIPS = []


async def fake_prepare(title):
    await asyncio.sleep(0.1)
    return f"/tmp/{title}_v.wav", f"/tmp/{title}_i.wav"


async def fake_play(vocal, title, inst_path=None):
    PLAYED.append(title)
    acp.IS_SINGING_ACTIVE = True
    await asyncio.sleep(0.2)
    acp.IS_SINGING_ACTIVE = False


async def fake_wait():
    return None


def rescue_one(prompt):
    """照抄 vts _rescue_missed_song_requests 的核心判斷（薄包裝，邏輯以單元測試為準）"""
    tool, args = parse_slip_for_song(prompt)
    if not tool:
        return "skip: not a song slip"
    song = (args or {}).get("song_name", "")
    if not song or acp.is_song_active(song):
        return "skip: already active"
    msg = acp.request_cover_song(song, "")
    SLIPS.append(build_slip_text("auto_sing_song", {"song_name": song}, ""))
    return msg


async def drain():
    for _ in range(200):
        if (not acp.SONG_REQUEST_QUEUE and not acp.READY_SONGS
                and not acp._stage_busy()
                and (acp._ORCH_TASK is None or acp._ORCH_TASK.done())
                and (acp._PREPARE_TASK is None or acp._PREPARE_TASK.done())):
            break
        await asyncio.sleep(0.05)


async def main():
    acp.prepare_cover_song = fake_prepare
    acp.play_cover_audio = fake_play
    acp.wait_for_intro_speech_complete = fake_wait

    # 事故重演：CPU 漏判（舊碼）→紙條送達→G3 死亡（腦什麼都沒做）→G4 重連救援
    incident = "[文字輸入] 老爸 (在直播間留言)：唱 5:20am"
    # 第一遍：無人認領 → 撿回＋排入＋補中性紙條
    r1 = rescue_one(incident)
    assert "5:20am" in r1 and "不重複" not in r1, r1
    assert len(SLIPS) == 1 and "不是點歌的人" in SLIPS[0] and "老爸" not in SLIPS[0], SLIPS
    # 第二遍（歌已在準備／在唱）→ 跳過，絕不唱兩次
    await asyncio.sleep(0.15)
    r2 = rescue_one(incident)
    assert r2 == "skip: already active", r2
    await drain()
    assert PLAYED == ["5:20am"], PLAYED
    # 非點歌紙條不碰
    assert rescue_one("[環境動態] 電腦畫面剛剛發生變化：右下角跳出通知") == "skip: not a song slip"
    assert rescue_one("[系統提示：妳剛才演唱完畢了歌曲《晴天》，請謝幕！]") == "skip: not a song slip"
    print("RESCUE SIM: ALL OK")


asyncio.run(main())
