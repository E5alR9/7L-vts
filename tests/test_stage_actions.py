# -*- coding: utf-8 -*-
"""舞台動作 2026-10-25 從主程式搬到 services/stage_actions.py：時間軸照字數比例排、主檔不留副本。"""
import os

from conftest import ROOT
from services.stage_actions import parse_action_timeline


def test_timeline_fires_by_text_position():
    tl = parse_action_timeline("[EXPRESSION: 生氣]你怎麼現在才來[EXPRESSION: 臉紅]不過我好想你", 4.0)
    assert tl[0] == (0.0, "EXPRESSION", "生氣")
    assert tl[1] == (2.15, "EXPRESSION", "臉紅")                           # 第 7 字後：7/13 × 4 秒
    assert parse_action_timeline("[WINK]嗨[SHOCK]", 1.0) == [(0.0, "WINK", ""), (1.0, "EXPRESSION", "震驚")]
    assert parse_action_timeline("", 3.0) == []


def test_stage_actions_not_left_in_main():
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    for name in ("parse_action_timeline", "execute_action_timeline", "execute_speech_visual_actions",
                 "expression_keeper_worker", "move_spatial_position"):
        assert f"def {name}(" not in main


def test_audio_helpers_moved_out_of_main():
    """音訊分析 2026-10-25 搬到 services/audio_analysis.py；翻唱對嘴直接 import，不再從主程式模組撈。"""
    main = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
    for name in ("extract_audio_mouth_envelope", "_load_sound_with_envelope", "normalize_text_for_echo",
                 "check_is_echo_by_waveform"):
        assert f"def {name}(" not in main
    cover = open(os.path.join(ROOT, "services", "auto_cover_pipeline.py"), encoding="utf-8").read()
    assert 'getattr(core_vts, "extract_audio_mouth_envelope"' not in cover
    from services.audio_analysis import normalize_text_for_echo
    assert normalize_text_for_echo("ＡＢＣ，你好！") == normalize_text_for_echo("abc你好")
