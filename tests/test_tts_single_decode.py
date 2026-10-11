# -*- coding: utf-8 -*-
"""播音單次解碼：同一個 Sound 同時拿時長＋包絡＋播音（不 decode 兩次）。
主檔太重不直接 import，用 AST 抽出來跑，pygame 用樁。"""
import ast
import os
import sys
import types


def _load():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    tree = ast.parse(src)

    calls = {"n": 0}

    class _FakeSound:
        def get_length(self):
            return 2.0

    class _FakeMixer:
        def Sound(self, path):
            calls["n"] += 1
            return _FakeSound()

        def get_init(self):
            return (44100, -16, 2)

    class _FakeSndarray:
        @staticmethod
        def array(snd):
            import numpy as np
            return np.zeros(44100 * 2, dtype=np.int16)

    fake_pg = types.ModuleType("pygame")
    fake_pg.mixer = _FakeMixer()
    fake_pg.sndarray = _FakeSndarray()
    fake_sndarray_mod = types.ModuleType("pygame.sndarray")
    fake_sndarray_mod.array = _FakeSndarray.array

    ns = {}
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in (
                "extract_audio_mouth_envelope", "_load_sound_with_envelope"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    ns["pygame"] = fake_pg  # helper 用模組全域 pygame（本體由檔頭 import 提供）
    return funcs, fake_pg, fake_sndarray_mod, calls


def test_single_decode_success(monkeypatch):
    funcs, fake_pg, fake_sndarray_mod, calls = _load()
    monkeypatch.setitem(sys.modules, "pygame", fake_pg)
    monkeypatch.setitem(sys.modules, "pygame.sndarray", fake_sndarray_mod)
    snd, dur, env = funcs["_load_sound_with_envelope"]("whatever.wav", "你好呀")
    assert calls["n"] == 1  # 只 decode 一次（舊碼兩次）
    assert dur == 2.0
    assert len(env) > 0 and all(v == 0.0 for v in env)  # 全靜音→全閉嘴


def test_single_decode_failure_falls_back(monkeypatch):
    funcs, fake_pg, fake_sndarray_mod, calls = _load()

    class _BoomMixer:
        def Sound(self, path):
            calls["n"] += 1
            raise RuntimeError("no decoder")

    fake_pg.mixer = _BoomMixer()
    monkeypatch.setitem(sys.modules, "pygame", fake_pg)
    snd, dur, env = funcs["_load_sound_with_envelope"]("ghost.wav", "1234567890")
    assert snd is None and env == []
    assert dur == max(0.5, 10 * 0.22)  # 字數估算兜底
    snd2, dur2, env2 = funcs["_load_sound_with_envelope"]("ghost.wav", "")
    assert dur2 == 0.5  # 空字串下限
