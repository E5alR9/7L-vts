# -*- coding: utf-8 -*-
"""唱歌對嘴：包絡生產端（管線）與消費端（臉迴圈）必須是同一個命名空間。
2026-10-11 事故：vts 以 __main__ 執行，服務層 lazy `from vts_7L_test import ...`
觸發整檔重跑，全域一分為二——包絡進分身、臉讀本體，唱歌嘴永遠閉著（眼睛/表情正常）。
根治：開機別名。另加真實歌聲包絡實證（Mili RVC 成品必须能張嘴）。"""
import ast
import os


def _vts_src():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8") as f:
        return f.read()


def test_no_module_fork_alias_locked():
    """開機別名被人刪掉，分身立刻復活——鎖死這一行。"""
    src = _vts_src()
    assert '.modules.setdefault("vts_7L_test"' in src
    tree = ast.parse(src)
    mains = [n for n in tree.body
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "main"]
    assert len(mains) == 1
    body_src = ast.get_source_segment(src, mains[0]) or ""
    assert 'setdefault("vts_7L_test"' in body_src  # 必須在 main() 裡，不是在別處


def test_real_vocal_envelope_moves():
    """拿 cover_cache 裡最新的 RVC 成品跑包絡：最大值必須能張嘴（>0.1）。
    證偽『歌聲檔本身是靜音』的另一種死法。無成品時跳過。"""
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import glob
    import pygame
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = sorted(glob.glob(os.path.join(root, "songs_library", "cover_cache", "*_7l_vocal.wav")),
                   key=os.path.getmtime)
    if not cands:
        import pytest
        pytest.skip("cover_cache 無 RVC 成品")
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=44100)
    tree = ast.parse(_vts_src())
    ns = {"pygame": pygame}
    import numpy as _np
    ns["numpy"] = _np
    ns["np"] = _np
    funcs = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "extract_audio_mouth_envelope":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "x", "exec"), ns)
            funcs[n.name] = ns[n.name]
    snd = pygame.mixer.Sound(cands[-1])
    env = funcs["extract_audio_mouth_envelope"](snd, fps=25)
    assert len(env) > 100, f"包絡太短: {len(env)}"
    assert max(env) > 0.3, f"嘴張不開: max={max(env)}（檔：{os.path.basename(cands[-1])}）"
    quiet = sum(1 for v in env if v <= 0.01)
    assert quiet < len(env) * 0.9, "九成以上靜音，成品有問題"
