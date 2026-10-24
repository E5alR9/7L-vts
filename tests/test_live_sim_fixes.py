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
    monkeypatch.setenv("XIAOYI_TIGHT_REF", "0")
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
    src = _src("_gdi_capture_screen")
    assert 'ctypes.WinDLL("user32")' in src and 'ctypes.WinDLL("gdi32")' in src
    assert "restype = H" in src or ".restype = [H]" in src or "], H" in src
    calls = [ast.unparse(n.func) for n in ast.walk(_fn("_gdi_capture_screen")) if isinstance(n, ast.Call)]
    assert not [c for c in calls if c.startswith("ctypes.windll")]   # 不動其他套件共用的 windll
    assert "_DXCAM_LAST_FRAME" in _src("capture_screen_multi_view")


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
