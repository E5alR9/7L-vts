# -*- coding: utf-8 -*-
"""輸入來源分類只在 core.input_sources 定義一次（2026-10-25）：以前主程式抄了 6 份，
有的漏 web_console、有的用 "text"，老爸在後台打字會被當成別人。"""
import ast
import os

from conftest import ROOT
from core.input_sources import (InputItem, classify, is_operator, live_speech_wakes, parse_input_item,
                                sleep_wake_decision, VIEWER_SOURCES)


def test_parse_input_item():
    it = parse_input_item({"text": " 晴天 ", "source": "twitch", "platform_uid": 123, "timestamp": 5.0})
    assert (it.text, it.source, it.platform_uid, it.timestamp) == ("晴天", "twitch", "123", 5.0)
    assert parse_input_item({"text": "嗨", "audio_base64": "AAA"}).source == "mic"   # 有錄音沒標來源＝麥克風
    assert parse_input_item({"text": "嗨"}).source == "unknown"
    assert parse_input_item("純字串").text == "純字串"
    assert parse_input_item({"text": "   "}) is None and parse_input_item(None) is None and parse_input_item("") is None


def test_classify_routes():
    route = lambda src, audio=None: classify(InputItem(text="x", source=src, audio_b64=audio))
    for src in ("mic", "text_file", "console", "web_console"):
        assert route(src) == "operator"
    assert route("unknown", audio="AAA") == "operator"                       # 帶錄音一律算老爸麥克風
    for src in ("tiktok", "tiktok_gift", "twitch", "youtube"):
        assert route(src) == "audience"
    assert route("owner_interject") == "owner_interject"
    assert route("tiktok_ambient") == "ambient"
    assert route("discord") == "unknown"
    assert is_operator("web_console") and not is_operator("youtube")
    assert "video_watch" in VIEWER_SOURCES and "web_console" not in VIEWER_SOURCES


def test_sleep_wake_decision():
    d = lambda src, text="hi", audio=None, enabled=True: sleep_wake_decision(
        InputItem(text=text, source=src, audio_b64=audio), enabled)
    assert d("youtube") == "wake_audience" and d("owner_interject") == "wake_audience"
    assert d("web_console") == "wake_operator"                              # 老爸打字：不用喚醒詞
    assert d("mic", "嗯嗯", audio="A") == "ignore"                           # 麥克風雜音不吵醒
    assert d("mic", "7L 起床", audio="A") == "wake_operator"
    assert d("console", enabled=False) == "ignore"                          # 操作者通道關掉就不理
    assert d("tiktok_ambient") == "ignore"


def test_live_speech_wakes():
    """Live 連著時麥克風不經過輸入佇列：Live 轉出來的文字也要能用喚醒詞叫醒她（2026-10-26）。"""
    assert live_speech_wakes("7L 起床了", True) and live_speech_wakes("醒醒啦", True)
    assert not live_speech_wakes("嗯嗯 他應該說了很多吧", True)                  # 一般講話不吵醒
    assert not live_speech_wakes("7L 起床", False)                               # 操作者通道關掉就不理
    assert not live_speech_wakes("", True)


def test_live_brain_transcribes_and_wakes_on_mic():
    """Live 要開「老爸講的話轉文字」，收到轉文字就聽喚醒詞；她這輪沒開口也要把老爸的話記下來。"""
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(main)
    fn = lambda name: ast.get_source_segment(main, next(
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name))
    worker = fn("continuous_live_worker")
    assert "input_audio_transcription=types.AudioTranscriptionConfig()" in worker
    recv = fn("receive_from_live")
    assert "IS_SLEEPING and live_speech_wakes(to_tw(user_transcription_buffer), operator_input_enabled())" in recv
    assert "await set_sleep_mode(False)" in recv
    done = recv.index("if c.turn_complete or getattr(c, 'generation_complete', False):")
    assert recv.index("_flush_user_speech()", done) < recv.index("if chunk_buffer.strip():", done)
    flush = fn("_flush_user_speech")
    assert 'source="mic"' in flush and "touch_interaction()" in flush


def test_main_has_no_handwritten_source_lists():
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    for frag in ('["mic", "text_file"', "['mic', 'text_file'", '["tiktok", "tiktok_gift", "twitch", "youtube"]',
                 "_VIEWER_SOURCES = "):
        assert frag not in main, frag
    assert "route = classify(item)" in main and "sleep_wake_decision(item," in main
