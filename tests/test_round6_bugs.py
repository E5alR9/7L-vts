# -*- coding: utf-8 -*-
"""2026-10-27 健檢找到的 bug：計時器中文數字、拒絕被當答應、搜尋備援、喚醒等級、看板平台標籤、電擊摸頭的紙條、曉伊自己鎖死、
曉伊攔輸出換掉全域 sys.stdout 害狀態列 print 崩潰（直播 0xC0000005 的真兇）。"""
import asyncio
import ast
import os
import sys
import threading

from conftest import ROOT
from core.live_timer_sensor import LiveTimerSensorHub, cn_number
from core.hard_command import stage_request_unasked
import services.web_search as ws

from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE, main_def  # noqa: E402


_fn = main_def


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


def test_xiaoyi_does_not_deadlock_when_model_not_loaded(monkeypatch):
    """模型還沒載好就合成：要回空 bytes 讓 tts_router 換下一個引擎，不能卡死在自己的鎖上。"""
    from services import local_xiaoyi_service as lx
    monkeypatch.setattr(lx, "_tts_pipeline", None)
    monkeypatch.setitem(sys.modules, "TTS_infer_pack.TTS", None)   # 載入模型馬上失敗，不真的吃顯卡
    out = []
    t = threading.Thread(target=lambda: out.append(lx.synthesize_xiaoyi_bytes("哈囉")), daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), "synthesize_xiaoyi_bytes 鎖死了"
    assert out == [b""]


def test_tts_capture_never_swaps_stdout_back(monkeypatch):
    """攔曉伊輸出時全域 sys.stdout 只換一次、之後不再換回：換回會讓別的執行緒正在 print 的暫時物件被釋放 → 整個 python 崩潰。"""
    import io
    from services import local_xiaoyi_service as lx
    real = io.StringIO()
    monkeypatch.setattr(sys, "stdout", real)
    monkeypatch.setattr(sys, "stderr", real)
    with lx.capture_tts_output():
        router = sys.stdout
        print("推理中 這行進後台、不進終端")
    assert sys.stdout is router and isinstance(router, lx._ThreadRoutedStream)
    with lx.capture_tts_output():
        assert sys.stdout is router   # 第二次也是同一個，沒有再換
    assert "推理中" not in real.getvalue()

    # 別的執行緒在攔輸出的時候，主執行緒照常印到真終端
    inside, done = threading.Event(), threading.Event()

    def tts():
        with lx.capture_tts_output():
            inside.set()
            done.wait(5)
    t = threading.Thread(target=tts)
    t.start()
    inside.wait(5)
    print("狀態列")
    done.set()
    t.join(5)
    assert "狀態列" in real.getvalue()
    assert lx._CAPTURES == {}


def test_spatial_move_reports_failure_and_lets_conscious_moves_win(monkeypatch):
    """VTS 沒連線不能回「已成功」；本能走位跟表情一樣讓意識優先 6 秒。"""
    import services.vts_client as vc
    moves = []

    async def fake_move(**kw):
        moves.append(kw["target_pos"])
        return fake_move.ok
    monkeypatch.setattr(vc, "move_vts_spatial", fake_move)
    monkeypatch.setattr(vc, "log_print", lambda *a, **k: None)
    fake_move.ok = False
    assert "沒移成" in asyncio.run(vc.apply_spatial_position("左邊"))
    fake_move.ok = True
    assert "已成功" in asyncio.run(vc.apply_spatial_position("右邊"))              # 主腦叫的
    assert "本能走位先不動" in asyncio.run(vc.apply_spatial_position("中間", is_instinct=True))
    assert moves == ["左邊", "右邊"]
    monkeypatch.setattr(vc, "LAST_CONSCIOUS_ACTION_TIME", 0.0)
    assert "已成功" in asyncio.run(vc.apply_spatial_position("中間", is_instinct=True))


def test_temp_reply_cleanup_covers_wav_segments():
    src = ast.get_source_segment(MAIN, _fn("_remove_temp_mp3"))
    assert '"temp_reply_*"' in src and "GPT-SoVITS" not in src


def test_speech_cleanup_is_one_helper_and_never_stops_shared_music():
    """念完、被取消、出錯三條路共用 _release_playback：只關自己的通道，不再 mixer.music.stop() 掐掉唱歌／音效。"""
    src = ast.get_source_segment(MAIN, _fn("play_voice_complete"))
    assert src.count("_release_playback()") == 4   # 定義一次＋三條路各叫一次
    assert "in locals() and" not in src and "in locals():" not in src   # 不再一個個猜變數有沒有建好
    assert "mixer.music.stop()" not in src.split("except asyncio.CancelledError")[1]   # 取消、出錯不再掐共用的 music


def test_expression_action_words_have_one_source():
    """眨眼／驚訝／皺眉／白眼：舞台動作、本能腦、set_vts_expression 都用 vts_client.action_kind（以前三份、還不一樣）。"""
    import services.vts_client as vc
    assert [vc.action_kind(t) for t in ("WINK", "SURPRISE", "難過眉", "鄙視", "開心")] ==         ["wink", "shock", "frown", "eye_roll", None]
    stage_src = open(os.path.join(ROOT, "services", "stage_actions.py"), encoding="utf-8").read()
    assert "vc.action_kind(exp_tag)" in stage_src
    assert MAIN.count("vc.action_kind(exp_tag)") == 1


def test_xiaoyi_uses_the_router_text_cleaning(monkeypatch):
    """曉伊跟其他引擎同一份清洗：標籤、括號也要拿掉（以前曉伊另抄一份，會把 (笑) 念出來）。"""
    import numpy as np
    import types as pytypes
    from services import local_xiaoyi_service as lx
    calls = []

    class FakePipe:
        configs = pytypes.SimpleNamespace(max_sec=54)

        def run(self, inputs):
            calls.append(inputs["text"])
            yield 32000, (np.sign(np.sin(np.arange(32000 * 2) * 0.05)) * 8000).astype(np.int16)

    monkeypatch.setattr(lx, "_tts_pipeline", FakePipe())
    monkeypatch.setattr(lx, "_REF_ZH", "ref.wav")
    assert lx.synthesize_xiaoyi_bytes("[EXPRESSION: 開心]7L 收到(笑)～～")
    assert calls[0] == "小七 收到！"
