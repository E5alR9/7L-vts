# -*- coding: utf-8 -*-
"""後台跟聲音同步（2026-10-26 老爸：網頁後台更新有一點不同步）。"""
import ast
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()


def test_speech_text_and_subtitle_wait_for_the_first_audio():
    """以前合成前就推「她說的話」、更新字幕，文字比聲音早約 2 秒；現在第一段聲音開始播才推。"""
    fn = next(n for n in ast.walk(ast.parse(MAIN)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "play_voice_complete")
    src = ast.get_source_segment(MAIN, fn)
    first = src.index("if first_chunk:")
    assert src.index('broadcast_event("ai_speech"') > first
    assert src.index("update_subtitle, text)") > first


def _stream(monkeypatch, sent):
    from services import local_xiaoyi_service as lx
    import services.web_dashboard as wd
    monkeypatch.setattr(wd, "broadcast_event", lambda t, d, **k: sent.append((t, d)))
    s = lx._WebLogStream()
    s._owner = threading.get_ident()
    s._real_out = sys.__stdout__
    return lx, s


def test_progress_bars_do_not_flood_the_dashboard(monkeypatch):
    """一句話以前推二十幾則進度、加上 tqdm 每一格都進日誌（實測每秒 8 則以上）。"""
    sent = []
    lx, s = _stream(monkeypatch, sent)
    for i in range(20):
        s.write(f" {i * 5}%|████      | {i}/20 [00:00<00:00, 40.00it/s]\n")
    assert [t for t, _ in sent if t == "tts_log"] == []                     # 進度條不進日誌
    assert len([t for t, _ in sent if t == "tts_progress"]) <= 2            # 同一階段 0.3 秒內只推一次
    s.write("前端处理后的文本 你好\n")
    assert sent[-1][0] == "tts_progress" and sent[-1][1]["stage"] == "音素音律對齊"   # 換階段照推


def test_missing_owner_does_not_raise(monkeypatch):
    """2026-10-26 子智能體執行時冒出只寫「_owner」的錯誤：屬性讀不到就經 __getattr__ 丟出。"""
    from services import local_xiaoyi_service as lx
    s = object.__new__(lx._WebLogStream)          # 還沒初始化完的那一下
    s.__dict__.update(_pending="")
    s.write("hello\n")
    s.flush()
