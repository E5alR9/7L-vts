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
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
TREE = ast.parse(MAIN)


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
    import local_xiaoyi_service as lx
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

def test_vision_is_tool_free_time_limited_and_not_routed_as_code():
    src = _src("live_vision_tool_task")
    assert "use_tools=False" in src and "VISION_TOOL_TIMEOUT_SEC" in src
    prompt = next(n.value for n in ast.walk(_fn("live_vision_tool_task"))
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and "描述這個畫面" in n.value)
    for kw in ("程式碼", "寫程式", "寫代碼", "分析"):     # 會被 get_prioritized_gemini_models 當高智商任務
        assert kw not in prompt
    assert "use_tools=False" in _src("live_mirror_tool_task")


def test_fetch_ai_response_can_skip_tools_and_races_other_models():
    src = _src("fetch_ai_response")
    assert "use_tools: bool = True" in src
    assert 'if use_tools:\n                config_kwargs["tools"] = active_tools' in src
    assert "running_models" in src and "ch[1] not in running_models" in src


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
    src = _src("chat_processor_worker")
    assert "is_dad_typed" in src and "(has_wake_word or is_dad_typed)" in src


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
    recv = _src("receive_from_live")
    assert "(?:SPEED|PITCH|VOLUME|RATE)" in recv


def test_expression_aliases_and_action_only_tags():
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import services.vts_client as vc
    assert vc.VTS_EXPRESSION_MAP.get("思考") == vc.VTS_EXPRESSION_MAP.get("問號")
    assert vc.VTS_EXPRESSION_MAP.get("調皮") == vc.VTS_EXPRESSION_MAP.get("吐舌")
    src = open(os.path.join(ROOT, "services", "vts_client.py"), encoding="utf-8").read()
    assert "if not action_hit:" in src


def test_stale_song_ack_is_skipped_once_singing():
    assert '"skip_if_singing": True' in _src("_song_ack")
    assert 'item.get("skip_if_singing") and is_singing()' in _src("speech_queue_worker")


def test_gift_events_keep_the_giver_name():
    import re
    seg = next(l for l in MAIN.splitlines() if "_m_name = re.search(" in l)
    pat = re.search(r"re\.search\(r'(.+?)', aud_c\)", seg).group(1)
    m = re.search(pat, "觀眾「土豪哥」送出了 嘉年華 x1（價值 30000 鑽石）！")
    assert m and m.group(1) == "土豪哥"


def test_vision_reply_uses_whole_text_not_first_char():
    for name in ("live_vision_tool_task", "live_mirror_tool_task"):
        assert "reply_text = resp[0]" not in _src(name)
        assert "isinstance(resp, str)" in _src(name)


def test_vision_report_does_not_retrigger_vision():
    ns = {"_VISION_STATE": {"report_ts": 0.0}, "VISION_REPORT_QUIET_SEC": 15.0}
    exec(compile(ast.Module(body=[_fn("_vision_report_recent")], type_ignores=[]), "v", "exec"), ns)
    now = time.time()
    assert not ns["_vision_report_recent"](now)
    ns["_VISION_STATE"]["report_ts"] = now
    assert ns["_vision_report_recent"](now + 5)          # 她在回答剛看到的畫面：不重看
    assert not ns["_vision_report_recent"](now + 20)     # 之後老爸再叫她看：照看
    assert '_VISION_STATE["report_ts"] = time.time()' in _src("live_vision_tool_task")
    assert "_vision_report_recent(time.time())" in _src("receive_from_live")


def test_screen_requests_sent_to_subagent_are_not_answered_by_guessing():
    import re
    pat = next(n.value.args[0].value for n in TREE.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_SUBAGENT_VISION_TASK_RE")
    for t in ("看老爸螢幕上面有什麼", "幫我看一下畫面", "看看桌面上開了什麼"):
        assert re.search(pat, t), t
    for t in ("查明天台北天氣", "彈琴 小星星", "一分鐘後提醒關瓦斯"):
        assert not re.search(pat, t), t
    src = _src("_handle_invoke_subagent")
    assert "_SUBAGENT_VISION_TASK_RE.search(_task_ins)" in src


def test_long_sentences_are_split_at_sentence_ends():
    import local_xiaoyi_service as lx
    t = "路人甲你問得好。關於今天要玩什麼遊戲，這就要問老爸喔。老爸，你有什麼好玩的計劃嗎？"
    segs = lx._split_for_tts(t, 22)
    assert "".join(segs) == t and len(segs) == 3 and all(len(s) <= 22 for s in segs)
    assert lx._split_for_tts("收到。沒問題，一分鐘後準時提醒你。", 22) == ["收到。沒問題，一分鐘後準時提醒你。"]  # 短句不切
    assert lx._split_for_tts(t, 0) == [t]                                                   # 可以關掉


def test_segment_check_rejects_unfinished_audio():
    import numpy as np
    import local_xiaoyi_service as lx
    sr = 32000
    tone = (np.sign(np.sin(np.arange(int(sr * 2.0)) * 0.05)) * 8000).astype(np.int16)
    assert lx._segment_ok(tone, sr, 9)                                        # 9 字、2 秒：正常
    stuck = np.concatenate([tone[: int(sr * 0.4)], np.zeros(sr * 20, np.int16)])
    assert not lx._segment_ok(stuck, sr, 9)                                   # 念兩個字就停、後面全空白
    holed = np.concatenate([tone[: sr], np.zeros(sr * 4, np.int16), tone[: sr]])
    assert not lx._segment_ok(holed, sr, 9)                                   # 中間 4 秒空白


def test_sampling_top_p_is_not_nucleus_truncated():
    """top_p<1 時停頓處只剩靜音可選，念一半就停的根本原因（2026-10-25 對照實驗）。"""
    import local_xiaoyi_service as lx
    assert lx._TOP_P == 1.0
    src = open(os.path.join(ROOT, "local_xiaoyi_service.py"), encoding="utf-8").read()
    assert "top_p = 0.8" not in src and "top_p = 0.75" not in src
    assert src.count("top_p = _TOP_P") == 2          # 中文、日文兩條都改


def test_generation_cap_follows_segment_length():
    import local_xiaoyi_service as lx
    assert lx._segment_max_sec(3) == 8                 # 短句至少 8 秒
    assert lx._segment_max_sec(22) == 14               # 22 字：約 4.8 秒的 3 倍
    src = open(os.path.join(ROOT, "local_xiaoyi_service.py"), encoding="utf-8").read()
    assert "_tts_pipeline.configs.max_sec = _orig_max_sec" in src   # 用完一定還原


def test_comma_only_long_sentence_is_split_too():
    import local_xiaoyi_service as lx
    t = "一邊玩Minecraft，一邊跑程式，旁邊還開着鋼琴影片跟自動點擊器，這是要多工初理到極限嗎？"
    segs = lx._split_for_tts(t, 22)
    assert "".join(segs) == t and all(len(s) <= 22 for s in segs) and len(segs) >= 2


def test_whole_sentence_first_then_segments_as_fallback(monkeypatch):
    """先整句（快、自然）；整句不合格才切段重來。短句不切段，整句重抽。"""
    import numpy as np
    import local_xiaoyi_service as lx
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
    import local_xiaoyi_service as lx

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
    src = open(os.path.join(ROOT, "local_xiaoyi_service.py"), encoding="utf-8").read()
    assert "_tts_pipeline = TTS(config)\n            _install_lang_repair()" in src
    assert "segs if (default_lang or not _LANG_REPAIR_ON) else _repair_lang_segments(segs)" in src


def test_tuning_knobs_are_constants_not_env():
    """.env 只放 API 金鑰（2026-10-25 老爸要求）：這些調整值寫在程式裡，不從環境變數讀。"""
    names = ["XIAOYI_TIGHT_REF", "XIAOYI_TOP_P", "XIAOYI_SEGMENT_CHARS", "XIAOYI_LANG_REPAIR", "NV_SUBAGENT_MODEL",
             "TTS_QUALITY_RETRIES", "FASTEMBED_CACHE_DIR", "OWNER_ACCOUNT_IDS", "CONSOLE_QUICKEDIT",
             "VISION_TIME_BUDGET_SEC", "VTS_PORT"]
    files = ["vts_7L_test.py", "local_xiaoyi_service.py", "services/tts_router.py", "services/embedder.py",
             "services/vts_client.py", "core/identity.py", "core/env_config.py"]
    for f in files:
        src = open(os.path.join(ROOT, f), encoding="utf-8").read()
        for n in names:
            assert f'getenv("{n}"' not in src and f'"key": "{n}"' not in src, (f, n)
