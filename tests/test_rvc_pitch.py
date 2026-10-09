# -*- coding: utf-8 -*-
"""RVC 整首統一音域判決（2026-10-09：混合音域同首歌忽高忽低 → 整首統一）。"""
from conftest import ROOT  # noqa: F401
from services.rvc_pitch import (
    decide_song_key_shift, MALE_FEMALE_SPLIT_HZ, SONG_SHIFT_OCTAVE,
)


def test_all_low_goes_up():
    shift, ratio = decide_song_key_shift([(120.0, 10.0), (150.0, 8.0), (180.0, 5.0)])
    assert shift == SONG_SHIFT_OCTAVE == 12.0
    assert ratio == 1.0


def test_all_high_stays():
    shift, ratio = decide_song_key_shift([(220.0, 10.0), (260.0, 8.0), (300.0, 5.0)])
    assert shift == 0.0
    assert ratio == 0.0


def test_mixed_majority_low_goes_all_up():
    # 低 12 秒 vs 高 8 秒 → 整首 +12（含原本偏高的樂句，不跳變）
    shift, ratio = decide_song_key_shift([(130.0, 12.0), (260.0, 8.0)])
    assert shift == 12.0
    assert ratio == 0.6


def test_mixed_majority_high_stays_all_flat():
    # 低 5 秒 vs 高 15 秒 → 整首不動（含偏低的樂句，保持原調不跳變）
    shift, ratio = decide_song_key_shift([(130.0, 5.0), (260.0, 15.0)])
    assert shift == 0.0
    assert ratio == 0.25


def test_short_blip_cannot_flip_song():
    # 一句 0.5 秒低音唸白，翻不動 20 秒女聲主歌（按句數算會 1:1 誤判，按時長不會）
    shift, _ = decide_song_key_shift([(110.0, 0.5), (250.0, 20.0)])
    assert shift == 0.0


def test_exact_half_goes_up():
    shift, ratio = decide_song_key_shift([(100.0, 5.0), (300.0, 5.0)])
    assert ratio == 0.5
    assert shift == 12.0  # 平手時往上抬（模型甜美音域在高處）


def test_empty_and_garbage_safe():
    assert decide_song_key_shift([]) == (0.0, 0.0)
    assert decide_song_key_shift(None) == (0.0, 0.0)
    assert decide_song_key_shift([(130.0, 0.0), ("x", 5.0)]) == (0.0, 0.0)


def test_boundary_uses_same_threshold():
    # 分界與舊逐句邏輯同值：< 195 算低，>= 195 算高
    assert MALE_FEMALE_SPLIT_HZ == 195.0
    shift_low, _ = decide_song_key_shift([(194.9, 10.0)])
    shift_high, _ = decide_song_key_shift([(195.0, 10.0)])
    assert shift_low == 12.0
    assert shift_high == 0.0
