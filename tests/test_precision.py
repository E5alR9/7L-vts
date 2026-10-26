# -*- coding: utf-8 -*-
"""精度開關（2026-10-11：fp16 換 fp32 拉滿，慢幾秒無所謂）。
RVC＋SoVITS 預設全精度，環境變數可切回半精度。"""
import os


def _src(name):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, name), encoding="utf-8") as f:
        return f.read()


def test_rvc_full_precision_default():
    src = _src("services/neural_voice_converter.py")
    assert 'os.getenv("RVC_HALF", "0")' in src
    assert "is_half=True" not in src  # 一處半精度預設都不留
    assert src.count("is_half=_USE_HALF") >= 3  # hubert＋合成器＋管線全跟開關走


def test_xiaoyi_full_precision_default():
    src = _src("services/local_xiaoyi_service.py")
    assert 'os.getenv("XIAOYI_HALF", "0")' in src
    assert "config.is_half = True" not in src
