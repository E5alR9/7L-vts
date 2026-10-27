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


def test_live_search_uses_the_shared_search_with_ddg_fallback():
    # 以前主檔另寫一份 Tavily 搜尋，沒有 DuckDuckGo 備援
    src = ast.get_source_segment(MAIN, _fn("live_search_tool_task"))
    assert 'search_google, query, "basic"' in src and "tavily_client" not in src


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


def test_live_disconnect_forgets_the_dead_session():
    # 斷線後 GLOBAL_LIVE_SESSION 還留著舊連線：看門狗照樣記「不回話」立 rotate，下一次正常換線被當額度用完冷卻金鑰
    src = ast.get_source_segment(MAIN, _fn("continuous_live_worker"))
    down = src.index("_set_live_active(False)")
    assert "GLOBAL_LIVE_SESSION = None" in src[down:down + 200]
    up = src.index("GLOBAL_LIVE_SESSION = session")
    assert '_LIVE_MUTE.update(strikes=0, rotate="")' in src[up:up + 500]


def test_remember_position_words_are_one_list():
    # 以前 vts_client 另有一份：她說「記住基準」只有位置標籤認得，說「記住模型」只有講話認得
    from core.hard_command import asks_to_remember_model_position as asks
    assert asks("記住基準") and asks("記住模型") and asks("SAVE_POSITION") and not asks("往左一點")
    src = open(os.path.join(ROOT, "services", "vts_client.py"), encoding="utf-8").read()
    assert "asks_to_remember_model_position(clean_pos)" in src and '"save_position"]' not in src


def test_core_does_not_import_services_or_plugins():
    # core 是最底層：向量庫由主程式 register_rag 接上，插話的聲紋評分由主程式傳進 BargeInDetector
    import re
    bad = []
    for fn in os.listdir(os.path.join(ROOT, "core")):
        if fn.endswith(".py"):
            src = open(os.path.join(ROOT, "core", fn), encoding="utf-8").read()
            bad += [f"{fn}: {m}" for m in re.findall(r"(?m)^\s*(?:from|import) (?:services|workers|mic_live_plugin)\b.*$", src)]
    assert bad == []
    assert "_memory_core.register_rag(rag_service)" in MAIN


def test_brain_knows_voice_is_always_dad():
    # 麥克風的聲音直送 Live、沒有標籤；以前規則只寫「觀眾＝其他所有人」，剛有觀眾留言時她把老爸的話算到觀眾頭上
    #（10/26 實機兩次；Live A/B：舊提示詞 6 次錯 2 次，加這條 6 次全對）
    from core import promptkit
    assert "妳直接聽到的人聲（不是文字）一定是老爸本人" in promptkit.brain_system("老爸", "7L", {}, "", mode="companion")


def _vision_ns(history, describe):
    slips, started = [], []
    ns = {"log_print": lambda *a: None, "describe_images": describe, "get_combined_temporal_screen_snapshot": lambda: ["x"],
          "_VISION_STATE": {"report_ts": 0.0, "mirror_ts": 0.0, "fail_ts": 0.0, "busy": False}, "time": __import__("time"),
          "send_brain_slip": slips.append, "_clean_result_for_brain": lambda t: t, "asyncio": asyncio,
          "VISION_TOOL_TIMEOUT_SEC": 45.0, "VISION_REPORT_QUIET_SEC": 15.0, "VISION_FAIL_QUIET_SEC": 90.0,
          "VISION_FALLBACK_MAX_AGE": 180.0, "VISION_HISTORY_STREAM": history}
    ns["spawn"] = lambda c: started.append(c)
    for n in ("_vision_report_recent", "_start_vision", "live_vision_tool_task"):
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns, slips, started


def test_failed_vision_does_not_retry_or_complain_again():
    # 10/26 22:37～22:41：看畫面一直失敗、她每 45 秒抱怨一次「看不清楚」，還有兩個同時在看
    import time as _t

    async def fail(prompt, images):
        return ""
    ns, slips, started = _vision_ns([], fail)
    assert ns["_start_vision"]() is True and ns["_start_vision"]() is False   # 正在看：不再開一個
    started[0].close()
    asyncio.run(ns["live_vision_tool_task"]())
    assert len(slips) == 1 and "沒看清楚畫面" in slips[0] and ns["_VISION_STATE"]["busy"] is False
    assert ns["_start_vision"]() is False                                     # 剛失敗：90 秒內不重看
    ns["_VISION_STATE"]["fail_ts"] = _t.time() - 100
    assert ns["_start_vision"]() is True
    started[-1].close()


def test_failed_vision_falls_back_to_what_peripheral_vision_saw():
    import time as _t

    async def fail(prompt, images):
        return ""
    ns, slips, _ = _vision_ns([{"time": _t.time() - 30, "text": "老爸在看鋼琴影片"}], fail)
    asyncio.run(ns["live_vision_tool_task"]())
    assert len(slips) == 1 and "餘光看到" in slips[0] and slips[0].endswith("老爸在看鋼琴影片")
    ns, slips, _ = _vision_ns([{"time": _t.time() - 600, "text": "很久以前的畫面"}], fail)
    asyncio.run(ns["live_vision_tool_task"]())
    assert "沒看清楚畫面" in slips[0]                                          # 太舊的不拿來講


def test_gemini_calls_use_block_none_but_live_must_not():
    # 老爸指定 Gemini 一律 BLOCK_NONE（2026-10-27）；但 Live API 不認這個欄位，帶了直接 1007 連不上（實測）
    missing, live_bad = [], []
    files = ["vts_7L_test.py"] + [os.path.join(d, f) for d in ("core", "services", "workers")
                                  for f in os.listdir(os.path.join(ROOT, d)) if f.endswith(".py")]
    for rel in files:
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                kws = {k.arg for k in n.keywords}
                if n.func.attr == "GenerateContentConfig" and "safety_settings" not in kws:
                    missing.append(f"{rel}:{n.lineno}")
                if n.func.attr == "LiveConnectConfig" and "safety_settings" in kws:
                    live_bad.append(f"{rel}:{n.lineno}")
                if n.func.attr == "generate_content" and "config" not in kws:
                    missing.append(f"{rel}:{n.lineno}（沒有 config）")
    assert missing == [] and live_bad == []


def test_gemini_36_flash_thinks_minimal_and_deep_think_low(monkeypatch):
    # 3.6-flash 預設帶工具一次 11～22 秒；minimal 約 3.5 秒、叫工具 4/4 照樣對（2026-10-27 實測，老爸指定調低）
    from core.llm_engine import thinking_config
    import core.rest_brain as rb
    assert thinking_config("gemini-3.6-flash").thinking_level.value.lower() == "minimal"
    assert thinking_config("gemini-3.6-flash", deep=True).thinking_level.value.lower() == "low"
    assert thinking_config("gemini-3.5-flash-lite") is None
    seen = []

    async def once(key, model, parts, cfg, timeout):
        seen.append((model, cfg.thinking_config))
        raise RuntimeError("換下一個")
    monkeypatch.setattr(rb, "_gemini_once", once)
    monkeypatch.setattr(rb, "gemini_pairs", lambda models, attempts, keys=None: [("k1", m) for m in models])
    monkeypatch.setattr(rb, "report_gemini_key_error", lambda *a, **k: None)
    asyncio.run(rb.rest_chat("", "hi", models=["gemini-3.6-flash", "gemini-3.5-flash-lite"], tools=["t"], attempts=2))
    assert seen[0][0] == "gemini-3.6-flash" and seen[0][1].thinking_level.value.lower() == "minimal"
    assert seen[1] == ("gemini-3.5-flash-lite", None)


def _afterthought_ns(reply_text, origin, later_origin=None, singing=False):
    import re as _re
    import time as _t
    slips, asked = [], []

    async def live_one_shot(system, prompt, pool, **k):
        asked.append((prompt, k))
        if later_origin:
            ns["_BRAIN_INPUT_ORIGIN"].update(later_origin)   # 想的時候又有人講話
        return reply_text

    class _Role:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    ns = {"re": _re, "time": _t, "AFTERTHOUGHT_ENABLED": True, "AFTERTHOUGHT_TIMEOUT_SEC": 25.0,
          "AFTERTHOUGHT_MAX_AGE_SEC": 60.0, "_AFTERTHOUGHT": {"origin_ts": 0.0}, "_BRAIN_INPUT_ORIGIN": dict(origin),
          "IS_SLEEPING": False, "is_singing_active": lambda: singing, "pe": type("P", (), {"is_piano_active": False}),
          "_owner_name": lambda: "E5", "usage": type("U", (), {"as_role": staticmethod(lambda r: _Role())}),
          "live_one_shot": live_one_shot, "promptkit": type("K", (), {"afterthought_system": staticmethod(lambda o: "sys")}),
          "GEMINI_KEYS": ["k"], "DEEP_THINK_LIVE_MODEL": "deep", "send_brain_slip": slips.append,
          "log_print": lambda *a: None, "log_swallowed": lambda *a: None}
    for n in ("_afterthought_wanted", "_afterthought"):
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns, slips, asked


def test_afterthought_adds_a_line_after_she_answers():
    # 說完又想到（老爸點的）：主腦回完人話後，長思考 Live 在背後再想，有補充就遞紙條
    import time as _t
    o = {"who": "dad", "said": "3 紅 2 藍拿 2 顆都紅的機率？", "human": True, "ts": _t.time(), "name": ""}
    ns, slips, asked = _afterthought_ns("啊對了，正確是 30% 才對！", o)
    asyncio.run(ns["_afterthought"]("大概 50% 吧"))
    assert asked[0][1]["model"] == "deep" and asked[0][1]["thinking_level"] == "low"
    assert "E5說：3 紅 2 藍" in asked[0][0] and "7L 剛才回答：大概 50% 吧" in asked[0][0]
    assert len(slips) == 1 and slips[0].endswith("啊對了，正確是 30% 才對！")
    asyncio.run(ns["_afterthought"]("又講了一段"))            # 同一句人話只想一次
    assert len(asked) == 1
    # 觀眾也觸發，稱呼帶名字
    o2 = {"who": "audience", "said": "7L 會唱晴天嗎", "human": True, "ts": _t.time(), "name": "小美"}
    ns, slips, asked = _afterthought_ns("欸我剛想到，晴天副歌我最喜歡", o2)
    asyncio.run(ns["_afterthought"]("會呀！"))
    assert "觀眾「小美」說" in asked[0][0] and "觀眾「小美」" in slips[0]


def test_afterthought_stays_quiet_when_nothing_to_add_or_stale():
    import time as _t
    o = {"who": "dad", "said": "妳開心嗎", "human": True, "ts": _t.time(), "name": ""}
    ns, slips, _ = _afterthought_ns("[SILENCE]", o)
    asyncio.run(ns["_afterthought"]("超開心"))
    assert slips == []
    ns, slips, _ = _afterthought_ns("啊對了", o, later_origin={"ts": _t.time() + 5, "said": "下一句"})
    asyncio.run(ns["_afterthought"]("超開心"))
    assert slips == []                                          # 想的時候已經有人講下一句：過時不補
    for bad in ({**o, "human": False}, {**o, "ts": _t.time() - 120}):   # 系統通知、太舊
        ns, slips, asked = _afterthought_ns("啊對了", bad)
        asyncio.run(ns["_afterthought"]("好"))
        assert asked == [] and slips == []
    ns, slips, asked = _afterthought_ns("啊對了", o, singing=True)        # 唱歌中不想
    asyncio.run(ns["_afterthought"]("好"))
    assert asked == []


def test_live_brain_turn_spawns_the_afterthought():
    recv = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == "receive_from_live")
    assert "spawn(_afterthought(_spoken))" in ast.get_source_segment(MAIN, recv)


def test_she_does_not_describe_the_screen_before_seeing_it():
    # 2026-10-27 老爸同意的實測：還沒看就說「老爸在看《晴天》鋼琴教學」，4 秒後看完才改口講對
    import re as _re
    ns = {"re": _re}
    exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n, ast.Assign)
                                  and getattr(n.targets[0], "id", "") == "_CLAUSE_END_RE"] + [_fn("_vision_wait_text")],
                            type_ignores=[]), "v", "exec"), ns)
    f = ns["_vision_wait_text"]
    assert f("[EXPRESSION: 正常] 我看看～ [EXPRESSION: 驚訝] 哇！老爸你在看 YouTube 晴天教學耶！") == "[EXPRESSION: 正常] 我看看～"
    assert f("等我看一下喔！老爸在寫程式吧") == "等我看一下喔！"
    assert f("[EXPRESSION: 思考]～我瞧瞧。") == "[EXPRESSION: 思考]～我瞧瞧。"
    assert f("我看看") == "我看看"
    recv = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == "receive_from_live")
    src = ast.get_source_segment(MAIN, recv)
    assert 'turn_vision = turn_vision or "[TOOL:VISION]" in text_chunk' in src
    assert 'if turn_vision and _VISION_STATE.get("busy"):' in src and src.count("turn_vision = False") == 3


def test_rest_brain_waits_for_the_screen_only_while_a_look_is_running():
    import re as _re
    said = []

    async def speak(vts, iq, text, who, reply_to, source, **k):
        said.append(text)
        return text
    for busy, want in ((True, "我看看～"), (False, "我看看～老爸在用 Gemini")):
        said.clear()
        ns = {"re": _re, "normalize_silence_token": lambda t: t, "_start_marker_tools": lambda t: t.replace("[TOOL:VISION]", ""),
              "_VISION_STATE": {"busy": busy}, "_speak_brain_turn": speak, "log_print": lambda *a: None}
        exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n, ast.Assign)
                                      and getattr(n.targets[0], "id", "") == "_CLAUSE_END_RE"]
                                + [_fn("_vision_wait_text"), _fn("_rest_speak")], type_ignores=[]), "v", "exec"), ns)
        asyncio.run(ns["_rest_speak"](None, None, "我看看～[TOOL:VISION]老爸在用 Gemini", "dad"))
        assert said == [want]                 # 看完回報後她順手又帶標籤（沒在看）：描述照念
