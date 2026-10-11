# -*- coding: utf-8 -*-
"""桌面查料投遞（2026-10-11 v3）：唱歌中 TTS 短版插播，否則紙條讓主腦用自己口吻說。
主檔太重不直接 import，用 AST 抽出來跑，外部名字全用樁。"""
import ast
import asyncio
import os


class _Q:
    def __init__(self):
        self.items = []

    async def put(self, item):
        self.items.append(item)

    def put_nowait(self, item):
        self.items.append(item)


class _PaperBox:
    def __init__(self):
        self.items = []

    def put_nowait(self, item):
        self.items.append(item)


def _load(execute=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)

    async def _fake_execute(vts, sentence, input_queue, caller_target="", caller_user=""):
        if execute == "boom":
            raise RuntimeError("x")
        return "收到：" + sentence

    ns = {"execute_actions": _fake_execute,
          "speech_queue": _Q(),
          "LIVE_API_SYSTEM_PROMPT_QUEUE": _PaperBox()}
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_deliver_desktop_findings":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs["_deliver_desktop_findings"], ns


def test_idle_goes_paper(monkeypatch):
    import services.auto_cover_pipeline as acp
    monkeypatch.setattr(acp, "singing_audio_active", lambda: False)
    f, ns = _load()
    asyncio.run(f(None, None, "今天會下雨嗎", "明天下午有雨", "dad", "老爸"))
    assert ns["speech_queue"].items == []
    assert len(ns["LIVE_API_SYSTEM_PROMPT_QUEUE"].items) == 1
    paper = ns["LIVE_API_SYSTEM_PROMPT_QUEUE"].items[0]
    assert "明天下午有雨" in paper and "自己的口吻" in paper


def test_singing_goes_tts_banter(monkeypatch):
    import services.auto_cover_pipeline as acp
    monkeypatch.setattr(acp, "singing_audio_active", lambda: True)
    f, ns = _load()
    asyncio.run(f("VTS", "Q", "今天會下雨嗎", "明天下午有雨", "dad", "老爸"))
    assert ns["LIVE_API_SYSTEM_PROMPT_QUEUE"].items == []
    assert len(ns["speech_queue"].items) == 1
    said = ns["speech_queue"].items[0]["text"]
    assert "明天下午有雨" in ns["speech_queue"].items[0]["raw_text"]
    assert len(said) <= 130  # 短版，不長篇大論壓歌


def test_empty_findings_noop(monkeypatch):
    import services.auto_cover_pipeline as acp
    monkeypatch.setattr(acp, "singing_audio_active", lambda: False)
    f, ns = _load()
    asyncio.run(f(None, None, "hi", "   ", "dad", "老爸"))
    assert ns["speech_queue"].items == [] and ns["LIVE_API_SYSTEM_PROMPT_QUEUE"].items == []
