# -*- coding: utf-8 -*-
"""她講話時聽老爸插話（core/barge_in.py，2026-10-26）：聲紋連續兩次像老爸才算，她自己的回音不算。"""
import asyncio

import numpy as np

from core import barge_in
from core.barge_in import BargeInDetector

SR = 16000


def _pcm(sec, amp=3000):
    return (np.sin(np.arange(int(SR * sec)) * 0.05) * amp).astype(np.int16).tobytes()


def _run(det, chunks, start=1000.0):
    out, t = [], start
    for c in chunks:
        det.feed(c)
        out.append(asyncio.run(det.check(now=t)))
        t += 0.5
    return out


def test_needs_two_dad_like_checks_in_a_row():
    det = BargeInDetector(score_fn=lambda wav: (0.65, 0.40))
    assert _run(det, [_pcm(0.5)] * 4) == [False, False, False, True]    # 滿 1.5 秒才開始比；連兩次像老爸
    assert len(det.buffered()) == int(SR * barge_in.WINDOW_SEC) * 2       # 剛才那段要一起送給 Live


def test_her_own_voice_never_counts():
    for scores in ((0.40, 0.77), (0.16, 0.37), (0.55, 0.58)):            # 她原音、她的回音、分不清
        det = BargeInDetector(score_fn=lambda wav, s=scores: s)
        assert not any(_run(det, [_pcm(0.5)] * 8))


def test_quiet_audio_is_not_checked():
    calls = []
    det = BargeInDetector(score_fn=lambda wav: calls.append(1) or (0.9, 0.1))
    assert not any(_run(det, [_pcm(0.5, amp=100)] * 6))
    assert calls == []


def test_a_miss_resets_the_count():
    seq = iter([(0.65, 0.4), (0.3, 0.6), (0.65, 0.4), (0.65, 0.4)])
    det = BargeInDetector(score_fn=lambda wav: next(seq))
    assert _run(det, [_pcm(0.5)] * 6) == [False, False, False, False, False, True]


def test_live_mic_loop_uses_the_detector():
    import ast
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "vts_7L_test.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "send_mic_audio")
    body = ast.get_source_segment(src, fn)
    assert "barge.feed(data)" in body and "interrupt_current_speech(" in body and "barge.buffered()" in body
