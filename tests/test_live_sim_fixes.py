"""2026-10-25 模擬直播實測修正的回歸測試：
TTS 念一半就停、看螢幕卡 4 分鐘、15 分鐘換線失憶、漫遊從沒跑過、截圖溢位、主動搭話開關、
睡著時老爸打字被忽略、後台與記憶的控制標籤、表情別名、過時的點歌應答、送禮名字。"""
import ast
import io
import os
import shutil
import subprocess
import time
import types as pytypes
import wave

import pytest

import services.tts_router as tr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from conftest import MAIN_SRC as MAIN, MAIN_TREE as TREE  # noqa: E402


def _fn(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _src(name):
    return ast.get_source_segment(MAIN, _fn(name))


def _wav(segments, rate=16000):
    """segments: [(秒數, 有聲?)]；有聲用 440Hz 方波，無聲全 0。"""
    frames = bytearray()
    for sec, voiced in segments:
        n = int(sec * rate)
        for i in range(n):
            v = (6000 if (i // 18) % 2 else -6000) if voiced else 0
            frames += int(v).to_bytes(2, "little", signed=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# ── TTS ──────────────────────────────────────────────────────────────

def test_tts_check_catches_trailing_silence():
    """念一兩個字就停、後面全是靜音到長度上限：舊檢查只看中段靜音，這種會被放行。"""
    text = "收到。沒問題，一分鐘後準時提醒你。"
    bad = _wav([(0.5, True), (22.0, False)])
    assert tr._audio_profile(bad)[1] >= 20       # 舊的兩值介面照舊
    assert "沒念完" in tr._quality_problem(text, bad)
    short_bad = _wav([(0.4, True), (20.0, False)])
    assert tr._quality_problem("好喔", short_bad)  # 短句也要抓


def test_tts_check_passes_normal_speech():
    text = "收到。沒問題，一分鐘後準時提醒你。"
    good = _wav([(1.2, True), (0.3, False), (2.5, True)])
    assert tr._quality_problem(text, good) == ""


def test_tts_cache_version_bumped_for_new_reference():
    assert tr.TTS_CACHE_VERSION != "v2"   # v2 裡有放行過的尾巴靜音檔，換參考音也要重抽


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_tight_reference_shortens_pauses(tmp_path, monkeypatch):
    from services import local_xiaoyi_service as lx
    src = tmp_path / "ref.wav"
    src.write_bytes(_wav([(0.8, True), (1.5, False), (0.8, True), (1.5, False), (0.8, True)]))
    out = lx._tight_ref(str(src))
    assert out != str(src) and os.path.exists(out)
    dur = float(subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                               capture_output=True, text=True).stdout.strip())
    assert dur < 4.0                                  # 原本 5.4 秒，停頓壓短
    monkeypatch.setattr(lx, "_USE_TIGHT_REF", False)
    assert lx._tight_ref(str(src)) == str(src)       # 可以關掉
    assert lx._tight_ref(str(tmp_path / "沒有這個檔.wav")).endswith("沒有這個檔.wav")


# ── 看螢幕 ────────────────────────────────────────────────────────────

def test_looking_at_images_is_tool_free_and_time_limited():
    """看畫面、照鏡子只要描述：不給工具（以前競速的每個通道都會各自執行模型回的工具，2026-10-25 星星眼一開一關抵銷），
    整段限時；圖片跟著文字送，不走 Groq。"""
    import asyncio
    import base64
    from google.genai import types
    calls = []

    async def rest_chat(system, prompt, **k):
        calls.append(k)
        return pytypes.SimpleNamespace(text="老爸在看鋼琴影片")
    ns = {"types": types, "base64": base64, "rest_chat": rest_chat, "GEMINI_MODELS": ["m"], "VISION_TOOL_TIMEOUT_SEC": 45.0,
          "usage": __import__("core.usage", fromlist=["usage"])}
    for n in ("_image_parts", "describe_images"):
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    img = base64.b64encode(b"\xff\xd8jpeg").decode()
    assert asyncio.run(ns["describe_images"]("描述這個畫面", [("【全景】", img), img])) == "老爸在看鋼琴影片"
    k = calls[0]
    assert "tools" not in k and k["total_timeout"] == 45.0 and len(k["extra_parts"]) == 3
    prompt = next(n.value for n in ast.walk(_fn("live_vision_tool_task"))
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and "描述這個畫面" in n.value)
    for kw in ("程式碼", "寫程式", "寫代碼", "分析"):     # 讓她把畫面講成程式碼（2026-10-25 實機）
        assert kw not in prompt


# ── Live 續接 ─────────────────────────────────────────────────────────

def _resume_ns():
    ns = {"time": time, "Optional": __import__("typing").Optional,
          "_LIVE_RESUME": {"handle": None, "model": None, "key": None, "ts": 0.0}, "_LIVE_RESUME_MAX_AGE": 3600.0}
    for n in ("_remember_live_resume_handle", "_take_live_resume_handle"):
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    return ns


def test_live_resume_handle_rules():
    ns = _resume_ns()
    remember, take = ns["_remember_live_resume_handle"], ns["_take_live_resume_handle"]
    now = time.time()
    assert not remember(pytypes.SimpleNamespace(new_handle="h0", resumable=False), "m", 0, now)  # 不可續接的時間點不記
    assert remember(pytypes.SimpleNamespace(new_handle="h1", resumable=True), "m", 0, now)
    assert take("m", 0, now + 5) == "h1"
    assert take("m", 0, now + 6) is None                         # 只用一次
    remember(pytypes.SimpleNamespace(new_handle="h2", resumable=True), "m", 0, now)
    assert take("other-model", 0, now) is None                   # 換模型不續接
    remember(pytypes.SimpleNamespace(new_handle="h3", resumable=True), "m", 0, now)
    assert take("m", 3, now) is None                             # 換金鑰不續接
    remember(pytypes.SimpleNamespace(new_handle="h4", resumable=True), "m", 0, now)
    assert take("m", 0, now + 4000) is None                      # 放太久不續接


def test_live_session_uses_resumption_and_handles_goaway():
    src = _src("continuous_live_worker")
    assert "session_resumption=types.SessionResumptionConfig(handle=_resume_handle)" in src
    assert "context_window_compression=" in src
    recv = _src("receive_from_live")
    assert "session_resumption_update" in recv and "_remember_live_resume_handle" in recv
    assert "go_away" in recv and "goaway_pending" in recv


# ── 閒置行為 ──────────────────────────────────────────────────────────

def test_wander_worker_is_no_longer_dead_code():
    fn = _fn("autonomous_wander_worker")
    src = _src("autonomous_wander_worker")
    none_assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                    and n.value.value is None and any(getattr(t, "id", "") == "idle_seconds" for t in n.targets)]
    assert not none_assigns
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef) and n.name == "now"]
    assert "idle_seconds = idle_ticks" in src and "now = time.time()" in src
    assert "pe.is_piano_performing()" in src
    assert "log_swallowed()" in src


def test_piano_performing_vs_waiting(monkeypatch):
    import services.piano_engine as pe
    monkeypatch.setattr(pe, "is_piano_active", True)
    monkeypatch.setattr(pe, "current_piano_song_title", "小星星")
    assert pe.is_piano_performing()
    monkeypatch.setattr(pe, "current_piano_song_title", "")    # 彈完留在台上待命
    assert not pe.is_piano_performing()


def test_idle_chatter_respects_switch_and_waiting_piano():
    src = _src("idle_chatter_worker")
    assert "not IS_PROACTIVE_SPEAK_ENABLED" in src
    assert "pe.is_piano_performing()" in src and "bool(pe.is_piano_active)" not in src


def test_dad_typing_wakes_her_up():
    """老爸打字是刻意對她說話，不用喚醒詞也叫醒（判斷 2026-10-25 搬到 core.input_sources）。"""
    from core.input_sources import InputItem, sleep_wake_decision
    assert sleep_wake_decision(InputItem(text="在嗎", source="web_console"), True) == "wake_operator"
    assert "sleep_wake_decision(item, operator_input_enabled())" in _src("chat_processor_worker")


def test_desktop_helper_absence_is_remembered():
    assert "_DESKTOP_DOWN_UNTIL = time.time() + _DESKTOP_DOWN_SEC" in _src("_desktop_dad_reply")
    assert "time.time() >= _DESKTOP_DOWN_UNTIL" in MAIN


# ── 截圖 ──────────────────────────────────────────────────────────────

def test_gdi_capture_declares_handle_types_on_private_dlls():
    path = os.path.join(ROOT, "services", "screen_capture.py")
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "gdi_capture_screen")
    body = ast.get_source_segment(src, fn)
    assert 'ctypes.WinDLL("user32")' in body and 'ctypes.WinDLL("gdi32")' in body
    calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert not [c for c in calls if c.startswith("ctypes.windll")]   # 不動其他套件共用的 windll
    assert "_DXCAM_LAST_FRAME" in src                                 # dxcam 沒新畫面沿用上一張
    assert "grab_screen()" in _src("capture_screen_multi_view")


def test_screen_capture_is_not_duplicated():
    """截圖只剩共用模組一份（以前三份，修好一份另外兩份還壞著）。"""
    for f in ("vts_7L_test.py", "services/web_dashboard.py", "run_dashboard.py"):
        src = open(os.path.join(ROOT, f), encoding="utf-8").read()
        assert "BitBlt" not in src and "StretchBlt" not in src, f


# ── 顯示與記憶 ────────────────────────────────────────────────────────

def test_dashboard_strips_control_tags():
    js = open(os.path.join(ROOT, "web", "dashboard.js"), encoding="utf-8").read()
    assert "stripControlTags(text)" in js and "this.stripControlTags(text)" in js
    assert "\x08" not in js


def test_memory_drops_prosody_tags():
    """主腦說的話存進記憶前拿掉語速／音高標籤（一句話常夾十幾個），表情標籤和內容留著。Live 和 REST 共用。"""
    import re
    from core.prompts import TextCleanEngine
    ns = {"re": re, "TextCleanEngine": TextCleanEngine}
    exec(compile(ast.Module(body=[_fn("_brain_text_for_memory")], type_ignores=[]), "m", "exec"), ns)
    out = ns["_brain_text_for_memory"]("[EXPRESSION: 花花] [SPEED:+8%][PITCH:+2Hz] 好呀 [SPEED+8%]～[INTERRUPT_SELF]")
    assert out == "[EXPRESSION: 花花] 好呀 ～"
    assert "_speak_brain_turn(" in _src("receive_from_live")
    assert "_brain_text_for_memory(text)" in _src("_speak_brain_turn")


def test_expression_aliases_and_action_only_tags():
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import services.vts_client as vc
    assert vc.VTS_EXPRESSION_MAP.get("思考") == vc.VTS_EXPRESSION_MAP.get("問號")
    assert vc.VTS_EXPRESSION_MAP.get("調皮") == vc.VTS_EXPRESSION_MAP.get("吐舌")
    src = open(os.path.join(ROOT, "services", "vts_client.py"), encoding="utf-8").read()
    assert "if not action_hit:" in src


def test_stale_speech_is_skipped_once_singing():
    assert 'item.get("skip_if_singing") and is_singing()' in _src("speech_queue_worker")


def test_gift_events_keep_the_giver_name():
    """送禮、訂閱、提問箱的人是誰：TikTok 監聽器直接帶 viewer，主程式不再從「觀眾「X」」這種內文撈名字。"""
    src = open(os.path.join(ROOT, "services", "tiktok_listener.py"), encoding="utf-8").read()
    for item in ('"tiktok_gift", u_name, f"{gift_desc}', '"tiktok_gift", user_name, "付費訂閱',
                 '"tiktok", user_name, f"（官方提問箱）{q_text}"'):   # 項目由 chat_source.make_chat_item 拼（2026-10-26）
        assert item in src, item
    assert "aud_u = item.viewer or" in MAIN and "_m_name = re.search(" not in MAIN


def test_vision_reply_uses_whole_text_not_first_char():
    """舊碼取 resp[0] 只拿到第一個字，主腦只收到「這」（2026-10-25 實機）。"""
    import asyncio
    slips = []

    async def describe_images(prompt, images):
        return "這是鋼琴影片和 Minecraft"
    ns = {"log_print": lambda *a: None, "describe_images": describe_images, "get_combined_temporal_screen_snapshot": lambda: ["x"],
          "_VISION_STATE": {"report_ts": 0.0}, "time": time, "send_brain_slip": slips.append, "VISION_HISTORY_STREAM": [],
          "_clean_result_for_brain": lambda t: t, "asyncio": asyncio, "VISION_TOOL_TIMEOUT_SEC": 45.0}
    exec(compile(ast.Module(body=[_fn("live_vision_tool_task")], type_ignores=[]), "v", "exec"), ns)
    asyncio.run(ns["live_vision_tool_task"]())
    assert len(slips) == 1 and slips[0].endswith("這是鋼琴影片和 Minecraft")


def test_vision_without_a_screen_does_not_ask_the_model():
    """沒有畫面（截圖失敗、測試擋截圖）就不問模型：2026-10-26 實測沒圖也照問，模型編出「在 main.py 裡改迴圈」。"""
    import asyncio
    slips, asked = [], []

    async def describe_images(prompt, images):
        asked.append(images)
        return "畫面中開著 main.py"
    ns = {"log_print": lambda *a: None, "describe_images": describe_images, "get_combined_temporal_screen_snapshot": lambda: None,
          "_VISION_STATE": {"report_ts": 0.0}, "time": time, "send_brain_slip": slips.append, "VISION_HISTORY_STREAM": [],
          "_clean_result_for_brain": lambda t: t, "asyncio": asyncio, "VISION_TOOL_TIMEOUT_SEC": 45.0}
    exec(compile(ast.Module(body=[_fn("live_vision_tool_task")], type_ignores=[]), "v", "exec"), ns)
    asyncio.run(ns["live_vision_tool_task"]())
    assert asked == [] and len(slips) == 1 and "沒看清楚畫面" in slips[0]


def test_vision_report_does_not_retrigger_vision():
    ns = {"_VISION_STATE": {"report_ts": 0.0}, "VISION_REPORT_QUIET_SEC": 15.0}
    exec(compile(ast.Module(body=[_fn("_vision_report_recent")], type_ignores=[]), "v", "exec"), ns)
    now = time.time()
    assert not ns["_vision_report_recent"](now)
    ns["_VISION_STATE"]["report_ts"] = now
    assert ns["_vision_report_recent"](now + 5)          # 她在回答剛看到的畫面：不重看
    assert not ns["_vision_report_recent"](now + 20)     # 之後老爸再叫她看：照看
    assert '_VISION_STATE["report_ts"] = time.time()' in _src("live_vision_tool_task")
    assert "_start_vision()" in _src("_start_marker_tools")
    assert "_start_marker_tools(text_chunk)" in _src("receive_from_live")


def test_screen_requests_sent_to_subagent_are_not_answered_by_guessing():
    import re
    pat = next(n.value.args[0].value for n in TREE.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_SUBAGENT_VISION_TASK_RE")
    for t in ("看老爸螢幕上面有什麼", "幫我看一下畫面", "看看桌面上開了什麼"):
        assert re.search(pat, t), t
    for t in ("查明天台北天氣", "彈琴 小星星", "一分鐘後提醒關瓦斯"):
        assert not re.search(pat, t), t
    src = _src("_run_subagent_task")
    assert "_SUBAGENT_VISION_TASK_RE.search(_task_ins)" in src


def test_long_sentences_are_split_at_sentence_ends():
    from services import local_xiaoyi_service as lx
    t = "路人甲你問得好。關於今天要玩什麼遊戲，這就要問老爸喔。老爸，你有什麼好玩的計劃嗎？"
    segs = lx._split_for_tts(t, 22)
    assert "".join(segs) == t and len(segs) == 3 and all(len(s) <= 22 for s in segs)
    assert lx._split_for_tts("收到。沒問題，一分鐘後準時提醒你。", 22) == ["收到。沒問題，一分鐘後準時提醒你。"]  # 短句不切
    assert lx._split_for_tts(t, 0) == [t]                                                   # 可以關掉


def test_segment_check_rejects_unfinished_audio():
    import numpy as np
    from services import local_xiaoyi_service as lx
    sr = 32000
    tone = (np.sign(np.sin(np.arange(int(sr * 2.0)) * 0.05)) * 8000).astype(np.int16)
    assert lx._segment_ok(tone, sr, 9)                                        # 9 字、2 秒：正常
    stuck = np.concatenate([tone[: int(sr * 0.4)], np.zeros(sr * 20, np.int16)])
    assert not lx._segment_ok(stuck, sr, 9)                                   # 念兩個字就停、後面全空白
    holed = np.concatenate([tone[: sr], np.zeros(sr * 4, np.int16), tone[: sr]])
    assert not lx._segment_ok(holed, sr, 9)                                   # 中間 4 秒空白


def test_sampling_top_p_is_not_nucleus_truncated():
    """top_p<1 時停頓處只剩靜音可選，念一半就停的根本原因（2026-10-25 對照實驗）。"""
    from services import local_xiaoyi_service as lx
    assert lx._TOP_P == 1.0
    src = open(os.path.join(ROOT, "services/local_xiaoyi_service.py"), encoding="utf-8").read()
    assert "top_p = 0.8" not in src and "top_p = 0.75" not in src
    assert src.count("top_p = _TOP_P") == 2          # 中文、日文兩條都改


def test_generation_cap_follows_segment_length():
    from services import local_xiaoyi_service as lx
    assert lx._segment_max_sec(3) == 8                 # 短句至少 8 秒
    assert lx._segment_max_sec(22) == 14               # 22 字：約 4.8 秒的 3 倍
    src = open(os.path.join(ROOT, "services/local_xiaoyi_service.py"), encoding="utf-8").read()
    assert "_tts_pipeline.configs.max_sec = _orig_max_sec" in src   # 用完一定還原


def test_comma_only_long_sentence_is_split_too():
    from services import local_xiaoyi_service as lx
    t = "一邊玩Minecraft，一邊跑程式，旁邊還開着鋼琴影片跟自動點擊器，這是要多工初理到極限嗎？"
    segs = lx._split_for_tts(t, 22)
    assert "".join(segs) == t and all(len(s) <= 22 for s in segs) and len(segs) >= 2


def test_whole_sentence_first_then_segments_as_fallback(monkeypatch):
    """先整句（快、自然）；整句不合格才切段重來。短句不切段，整句重抽。"""
    import numpy as np
    from services import local_xiaoyi_service as lx
    sr = 32000
    good = (np.sign(np.sin(np.arange(sr * 3) * 0.05)) * 8000).astype(np.int16)
    stuck = np.concatenate([good[: int(sr * 0.4)], np.zeros(sr * 20, np.int16)])
    calls = []

    class FakePipe:
        configs = pytypes.SimpleNamespace(max_sec=54)

        def run(self, inputs):
            calls.append((inputs["text"], self.configs.max_sec))
            whole = inputs["text"].startswith("路人甲你問得好。關於")
            yield sr, (stuck if whole else good)

    monkeypatch.setattr(lx, "_tts_pipeline", FakePipe())
    monkeypatch.setattr(lx, "_REF_ZH", "ref.wav")
    long_text = "路人甲你問得好。關於今天要玩什麼遊戲，這就要問老爸喔。老爸，你有什麼好玩的計劃嗎？"
    assert lx.synthesize_xiaoyi_bytes(long_text)
    texts = [c[0] for c in calls]
    import unicodedata
    assert texts[0] == unicodedata.normalize("NFKC", long_text)   # 合成前會轉半形標點
    assert len(texts) == 4                                     # 整句 1 次 → 切 3 段各 1 次就好
    assert all(c[1] < 54 for c in calls)                       # 生成上限跟著字數縮短
    assert FakePipe.configs.max_sec == 54                      # 用完還原
    calls.clear()
    assert lx.synthesize_xiaoyi_bytes("收到。沒問題。")
    assert [c[0] for c in calls] == ["收到。沒問題。"]           # 短句整句一次就過


def test_mixed_zh_ja_boundary_repair():
    """中日交界的漢字歸屬（2026-10-25 實測 split-lang 分錯：夜→中文、老爸→日文）。"""
    from services import local_xiaoyi_service as lx

    def seg(*pairs):
        return [{"lang": l, "text": t} for l, t in pairs]

    def run(*pairs):
        return [(s["lang"], s["text"]) for s in lx._repair_lang_segments(seg(*pairs))]

    # 假名助詞前的漢字屬於日文詞
    assert run(("zh", "這首歌叫做夜"), ("ja", "に駆ける，"), ("zh", "是的歌喔。")) == [
        ("zh", "這首歌叫做"), ("ja", "夜に駆ける，"), ("zh", "是的歌喔。")]
    # 中文專用字不搬（說）
    assert run(("zh", "老爸說"), ("ja", "の歌。")) == [("zh", "老爸說"), ("ja", "の歌。")]
    # 不是助詞開頭的日文詞不搬（謝謝｜ありがとう）
    assert run(("zh", "謝謝"), ("ja", "ありがとう。")) == [("zh", "謝謝"), ("ja", "ありがとう。")]
    # 假名後面的中文稱呼切回中文
    assert run(("ja", "さすが老爸，"), ("zh", "這個太厲害了。")) == [("ja", "さすが"), ("zh", "老爸，這個太厲害了。")]
    assert run(("ja", "ありがとう大家。")) == [("ja", "ありがとう"), ("zh", "大家。")]
    # 日文本身的漢字不動（様、一日）
    assert run(("ja", "今日も一日お疲れ様でした。"), ("zh", "晚安囉老爸。")) == [
        ("ja", "今日も一日お疲れ様でした。"), ("zh", "晚安囉老爸。")]
    # 其他語言原樣
    assert run(("zh", "是"), ("en", "YOASOBI"), ("zh", "的歌")) == [("zh", "是"), ("en", "YOASOBI"), ("zh", "的歌")]


def test_lang_repair_is_installed_on_pipeline_init():
    src = open(os.path.join(ROOT, "services/local_xiaoyi_service.py"), encoding="utf-8").read()
    assert "_tts_pipeline = TTS(config)\n            _install_lang_repair()" in src
    assert "segs if (default_lang or not _LANG_REPAIR_ON) else _repair_lang_segments(" in src
    assert "zh_main=not is_japanese_sentence(text)" in src


def test_chinese_segments_are_not_read_as_japanese():
    """split-lang 只看漢字分不出中日：純中文段被判成日文、用日文發音念（2026-10-25 老爸回報；實測
    「感覺很有節奏感喔」「沒問題。」都被切成 ja）。中文為主的句子裡，沒假名的段一律算中文。"""
    from services import local_xiaoyi_service as lx

    def run(zh_main, *pairs):
        segs = [{"lang": l, "text": t} for l, t in pairs]
        return [(s["lang"], s["text"]) for s in lx._repair_lang_segments(segs, zh_main=zh_main)]

    assert run(True, ("ja", "沒問題。"), ("zh", "經典的小星星來囉～"), ("ja", "聽聽看我有沒有談得比上次更厲害。")) == [
        ("zh", "沒問題。經典的小星星來囉～聽聽看我有沒有談得比上次更厲害。")]
    assert run(True, ("zh", "我看看～老爸一邊聽"), ("en", "Lemon Tree"), ("ja", "感覺很有節奏感喔")) == [
        ("zh", "我看看～老爸一邊聽"), ("en", "Lemon Tree"), ("zh", "感覺很有節奏感喔")]
    # 真的有假名的日文段照舊；日文為主的句子也不動
    assert run(True, ("zh", "這首歌叫做"), ("ja", "夜に駆ける")) == [("zh", "這首歌叫做"), ("ja", "夜に駆ける")]
    assert run(False, ("ja", "今日も一日お疲れ様でした。")) == [("ja", "今日も一日お疲れ様でした。")]


def test_chinese_with_english_uses_zh_mode_not_auto(monkeypatch):
    """有英文字母（連還沒換成「小七」的 7L 也算）舊碼就改 auto，auto 會把中文當日文念。實際送進 GPT-SoVITS 的模式為準。"""
    import numpy as np
    from services import local_xiaoyi_service as lx
    sr, modes = 32000, []
    good = (np.sign(np.sin(np.arange(sr * 3) * 0.05)) * 8000).astype(np.int16)

    class FakePipe:
        configs = pytypes.SimpleNamespace(max_sec=54)

        def run(self, inputs):
            modes.append(inputs["text_lang"])
            yield sr, good
    monkeypatch.setattr(lx, "_tts_pipeline", FakePipe())
    monkeypatch.setattr(lx, "_REF_ZH", "ref.wav")
    monkeypatch.setattr(lx, "_REF_JA", "ref_ja.wav")
    for text in ("7L 覺得沒問題。", "老爸一邊聽Lemon Tree一邊敲代碼呀？", "這首歌叫做夜に駆ける喔。"):
        modes.clear()
        assert lx.synthesize_xiaoyi_bytes(text)
        assert modes[0] == ("auto" if "に" in text else "zh"), (text, modes)
    import services.tts_router as tr
    assert tr.TTS_CACHE_VERSION not in ("v2", "v3", "v4")   # 舊快取裡有念錯的，要重抽


def test_tuning_knobs_are_constants_not_env():
    """.env 只放 API 金鑰（2026-10-25 老爸要求）：這些調整值寫在程式裡，不從環境變數讀。"""
    names = ["XIAOYI_TIGHT_REF", "XIAOYI_TOP_P", "XIAOYI_SEGMENT_CHARS", "XIAOYI_LANG_REPAIR", "NV_SUBAGENT_MODEL",
             "TTS_QUALITY_RETRIES", "FASTEMBED_CACHE_DIR", "OWNER_ACCOUNT_IDS", "CONSOLE_QUICKEDIT",
             "VISION_TIME_BUDGET_SEC", "VTS_PORT"]
    files = ["vts_7L_test.py", "services/local_xiaoyi_service.py", "services/tts_router.py", "services/embedder.py",
             "services/vts_client.py", "core/identity.py", "core/env_config.py"]
    for f in files:
        src = open(os.path.join(ROOT, f), encoding="utf-8").read()
        for n in names:
            assert f'getenv("{n}"' not in src and f'"key": "{n}"' not in src, (f, n)


def test_playback_state_lives_in_stage_module():
    """播放／嘴型狀態在 core.stage_state；翻唱流程不再用 setattr 改主程式的全域變數。"""
    import core.stage_state as stage
    stage.start_playback(envelope=[0.1, 0.5], start_time=12.0)
    assert stage.IS_MP3_PLAYING and stage.CURRENT_MOUTH_ENVELOPE == [0.1, 0.5] and stage.CURRENT_SPEECH_START_TIME == 12.0
    stage.clear_mouth()
    assert stage.IS_MP3_PLAYING and stage.CURRENT_MOUTH_ENVELOPE == [] and stage.CURRENT_SMOOTH_MOUTH == 0.0
    stage.stop_playback()
    assert not stage.IS_MP3_PLAYING and stage.CURRENT_SPEECH_START_TIME == 0.0
    names = ("IS_MP3_PLAYING", "CURRENT_MOUTH_ENVELOPE", "CURRENT_SMOOTH_MOUTH", "CURRENT_SPEECH_START_TIME")
    pipe = open(os.path.join(ROOT, "services", "auto_cover_pipeline.py"), encoding="utf-8").read()
    assert not [n for n in names if f'"{n}"' in pipe]
    main_defs = [n.targets[0].id for n in TREE.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)]
    assert not [n for n in names if n in main_defs]


def test_status_bar_error_does_not_kill_7l():
    """狀態列畫壞一格就跳過，不能讓 main() 的 _status_bar_loop 丟例外把整個 7L 帶走（2026-10-25 實機崩潰）。"""
    import asyncio
    tree = ast.parse(MAIN)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_status_bar_loop")
    calls, swallowed = [], []

    def boom(ch):
        calls.append(ch)
        raise AttributeError("'_WebLogStream' object has no attribute 'buffer'")
    import types as _t
    ns = {"asyncio": asyncio, "_draw_status_bar": boom, "log_swallowed": lambda: swallowed.append(1),
          "sys": _t.SimpleNamespace(__stdout__=_t.SimpleNamespace(isatty=lambda: True))}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "x", "exec"), ns)

    async def run():
        try:
            await asyncio.wait_for(ns["_status_bar_loop"](), timeout=0.35)
        except asyncio.TimeoutError:
            return "still running"
    assert asyncio.run(run()) == "still running" and len(calls) >= 3 and len(swallowed) == len(calls)

    # 輸出不是終端機（導到檔案、管線）：一格都不畫，但照樣撐住 main 不結束（2026-10-25 健檢：日誌被狀態列灌爆）
    calls.clear()
    ns["sys"] = _t.SimpleNamespace(__stdout__=_t.SimpleNamespace(isatty=lambda: False))
    assert asyncio.run(run()) == "still running" and calls == []


def test_main_crash_exits_instead_of_lingering():
    """主迴圈崩潰後要走 shutdown_7l 結束進程：只存記憶就返回的話背景執行緒還活著，
    殘留程序佔住鋼琴埠，下一個 7L 收不到鋼琴心跳（2026-10-25 實機）。"""
    src = _src("main")
    tail = src[src.index("await _status_bar_loop()"):]
    handler = tail[tail.index("except Exception as e:"):]
    assert "shutdown_7l()" in handler[:600]


def test_nothing_is_spoken_while_asleep():
    """按下休眠時主腦已經在想的回覆幾秒後才進佇列，舊碼照講（SLEEP → TALKING，2026-10-25 實機）。"""
    src = _src("speech_queue_worker")
    assert "if IS_SLEEPING:" in src
    assert src.index("if IS_SLEEPING:") < src.index('set_ai_state("TALKING"')


def test_instinct_worker_survives_an_empty_key_pool():
    """金鑰池空的時候 random.choice 丟錯，except 裡又用到還沒設定的 live_key，本能腦整個掛掉（2026-10-25 實機）。"""
    import asyncio as _a
    logs = []
    fn = next(n for n in ast.walk(ast.parse(MAIN)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "instinct_live_worker")

    async def _stop(*a, **k):
        raise _a.CancelledError()
    fake_asyncio = pytypes.SimpleNamespace(sleep=_stop, CancelledError=_a.CancelledError)
    ns = {"asyncio": fake_asyncio, "log_print": logs.append, "KEYS_AUDIENCE_LIVE": [], "GEMINI_KEYS": [],
          "INSTINCT_LIVE_SESSION": None, "report_gemini_key_error": lambda *a, **k: None}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "x", "exec"), ns)
    _a.run(ns["instinct_live_worker"]())                 # 舊碼在這裡丟 UnboundLocalError
    assert any("沒有可用的 Gemini 金鑰" in m for m in logs)


def test_companion_notes_reach_the_live_brain_without_a_reply():
    """伴看筆記以前只附在老爸打字的紙條裡，老爸用講的問影片在演什麼，她看不到筆記只能亂接（2026-10-25 實機）。
    現在筆記一寫好就悄悄放進主腦對話：send_client_content(turn_complete=False) 不觸發回話（2026-10-26 實測）。"""
    import asyncio as _a
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(main)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in ("_owner_text_slip", "add_brain_context")]
    q = _a.Queue(maxsize=2)
    live = {"on": True}
    ns = {"asyncio": _a, "LIVE_SILENT_CONTEXT_QUEUE": q, "is_live_brain_active": lambda: live["on"]}
    exec(compile(ast.Module(body=fns, type_ignores=[]), "f", "exec"), ns)
    assert ns["_owner_text_slip"]("E5", "這部在演什麼") == "[黑板同步] E5傳來文字訊息：這部在演什麼"
    assert ns["add_brain_context"]("[影片筆記] 男生在大象前講話") is True
    assert ns["add_brain_context"]("b") is True and ns["add_brain_context"]("c") is False   # 滿了就丟，不報錯
    live["on"] = False
    assert ns["add_brain_context"]("d") is False          # 主腦沒連上不送（REST 備援自己讀筆記）
    assert q.get_nowait() == "[影片筆記] 男生在大象前講話"
    # 主腦那邊：用 send_client_content、turn_complete=False（送 realtime 文字會讓她開口回話）
    sender = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "send_silent_context_to_live")
    src = ast.get_source_segment(main, sender)
    assert "send_client_content(" in src and "turn_complete=False" in src and "send_realtime_input" not in src
    assert "yt_comp.ON_NOTE_CB = " in main
    import services.yt_companion_service as yc
    got = []
    old_cb, old_title = yc.ON_NOTE_CB, yc.CURRENT_YT_TITLE
    yc.ON_NOTE_CB, yc.CURRENT_YT_TITLE = (lambda t, n: got.append((t, n))), "大象"
    try:
        yc.add_perception_memory("男生在大象前講話（測試）")
    finally:
        yc.ON_NOTE_CB, yc.CURRENT_YT_TITLE = old_cb, old_title
        if yc.YT_PERCEPTION_LOG and yc.YT_PERCEPTION_LOG[-1]["content"] == "男生在大象前講話（測試）":
            yc.YT_PERCEPTION_LOG.pop()
    assert got == [("大象", "男生在大象前講話（測試）")]

def test_mirror_report_does_not_retrigger_the_mirror():
    """照完鏡子她講描述時又帶 [TOOL:MIRROR]，以前會再照一次、再講一次（2026-10-26 實機）；看畫面早就有這個防護。"""
    import re
    started = []
    ns = {"re": re, "time": time, "log_print": lambda *a: None, "_VISION_STATE": {"report_ts": 0.0, "mirror_ts": 0.0},
          "VISION_REPORT_QUIET_SEC": 15.0, "VISION_FAIL_QUIET_SEC": 90.0, "strip_blob_noise": lambda t: t, "sanitize_search_query": lambda q: q,
          "spawn": lambda c: started.append(c), "live_mirror_tool_task": lambda: "mirror",
          "live_vision_tool_task": lambda: "vision", "live_search_tool_task": lambda q: "search"}
    ns["_BRAIN_INPUT_ORIGIN"] = {"human": False}
    ns["_VISION_ASK_RE"] = re.compile(r"螢幕|畫面")
    for n in ("_vision_report_recent", "_vision_wanted", "_start_vision", "_start_mirror", "_start_marker_tools"):
        exec(compile(ast.Module(body=[_fn(n)], type_ignores=[]), n, "exec"), ns)
    assert ns["_start_marker_tools"]("我照照看～[TOOL:MIRROR]") == "我照照看～" and started == ["mirror"]
    ns["_VISION_STATE"]["mirror_ts"] = time.time()
    assert ns["_start_marker_tools"]("白髮紅眼超可愛[TOOL:MIRROR]") == "白髮紅眼超可愛" and started == ["mirror"]
    assert ns["_start_marker_tools"]("我看看～[TOOL:VISION]") == "我看看～" and started == ["mirror", "vision"]
