# -*- coding: utf-8 -*-
"""唱歌中說話收尾：只關自己的發話通道（2026-10-11 誤殺麥克風事件）。
acp.singing_audio_active 直測；vts._stop_own_channels 用 AST 抽出來跑（主檔太重不 import）。"""
import ast
import os
import sys
import types
from types import SimpleNamespace

from conftest import ROOT  # noqa: F401
import services.auto_cover_pipeline as acp


def test_singing_audio_active_idle(monkeypatch):
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", False)
    monkeypatch.setattr(acp, "_NOW_PLAYING_TITLE", "")
    monkeypatch.setattr(acp, "_PLAY_TASK", None)
    assert acp.singing_audio_active() is False


def test_singing_audio_active_sources(monkeypatch):
    monkeypatch.setattr(acp, "_NOW_PLAYING_TITLE", "")
    monkeypatch.setattr(acp, "_PLAY_TASK", None)
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", True)
    assert acp.singing_audio_active() is True
    monkeypatch.setattr(acp, "IS_SINGING_ACTIVE", False)
    monkeypatch.setattr(acp, "_NOW_PLAYING_TITLE", "晴天")
    assert acp.singing_audio_active() is True
    monkeypatch.setattr(acp, "_NOW_PLAYING_TITLE", "")
    monkeypatch.setattr(acp, "_PLAY_TASK", SimpleNamespace(done=lambda: False))
    assert acp.singing_audio_active() is True
    monkeypatch.setattr(acp, "_PLAY_TASK", SimpleNamespace(done=lambda: True))
    assert acp.singing_audio_active() is False


def _load_stop_helper():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    calls = {"music_stop": 0, "music_unload": 0}

    class _FakeMusic:
        def stop(self):
            calls["music_stop"] += 1

        def unload(self):
            calls["music_unload"] += 1

    class _BoomMixer:
        """沒有 stop ——誰敢 mixer.stop() 地毯轟炸就 AttributeError 炸出來。"""
        music = _FakeMusic()

    fake_pg = types.ModuleType("pygame")
    fake_pg.mixer = _BoomMixer()
    ns = {"pygame": fake_pg}
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_stop_own_channels":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    return funcs["_stop_own_channels"], calls


def test_stop_own_channels_only():
    f, calls = _load_stop_helper()

    class _Ch:
        def __init__(self):
            self.stopped = 0

        def stop(self):
            self.stopped += 1

    class _BoomCh:
        def stop(self):
            raise RuntimeError("dead channel")

    a, b = _Ch(), _Ch()
    assert f([a, b, _BoomCh()], False) == 2  # 壞通道跳過不炸
    assert (a.stopped, b.stopped) == (1, 1)
    assert calls == {"music_stop": 0, "music_unload": 0}  # 沒用 fallback 就不碰 music
    assert f([], False) == 0
    assert f(None, False) == 0


def test_stop_own_channels_music_fallback():
    f, calls = _load_stop_helper()
    assert f([], True) == 1
    assert calls == {"music_stop": 1, "music_unload": 1}
