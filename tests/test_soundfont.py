# -*- coding: utf-8 -*-
"""SoundFont 渲染器測試（缺 .sf2 檔自動跳過）。"""
import os
import numpy as np
import pytest
from conftest import ROOT  # noqa: F401

SF2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "soundfonts", "FluidR3_GM_GS.sf2")
needs_sf = pytest.mark.skipif(not os.path.exists(SF2), reason="缺 soundfonts/FluidR3_GM_GS.sf2")


@needs_sf
def test_parse_and_render():
    from services.soundfont import SoundFontBank
    b = SoundFontBank(SF2)
    assert len(b.presets) > 100 and len(b.shdrs) > 100
    assert b.find_sample(0, 0, 60) is not None
    assert b.find_sample(128, 0, 36) is not None
    w = b.render_note(0, 0, 60, 90, 1.0)
    assert len(w) == 44100 and float(np.max(np.abs(w))) > 0.1
    assert b.render_note(0, 0, 200, 90, 0.1).sum() == 0  # 越界靜音不炸
    mix = b.render_track([(0.0, 60, 90, 0.5), (0.5, 64, 90, 0.5)])
    assert len(mix) > 44100 and float(np.max(np.abs(mix))) > 0.1
