# -*- coding: utf-8 -*-
"""RVC 整首統一音域判決（純函式、零第三方依賴、可單元測試）。

背景：以前逐樂句各自判決（中位數 < 195Hz 的樂句 +12、其餘不動），
混合音域的歌會在樂句邊界忽高忽低（2026-10-09 直播事故）。
現在：先掃完全部樂句，以「發聲時長加權的低音占比」做整首統一判決——
整體偏低就全曲 +12，否則全曲不動，同首歌內絕不跳變。
"""
from typing import Iterable, Tuple

MALE_FEMALE_SPLIT_HZ = 195.0   # 男女聲音域分界（約 G3），與舊逐句邏輯同值
SONG_SHIFT_OCTAVE = 12.0       # 整體偏低時全曲升八度
LOW_DOMINANCE_RATIO = 0.5      # 低音發聲時長占比達此值即判定整體偏低


def decide_song_key_shift(
    phrase_stats: Iterable[Tuple[float, float]],
    *,
    threshold: float = MALE_FEMALE_SPLIT_HZ,
    low_dominance: float = LOW_DOMINANCE_RATIO,
    shift_semitones: float = SONG_SHIFT_OCTAVE,
) -> Tuple[float, float]:
    """整首統一判決。

    phrase_stats: [(樂句中位數Hz, 發聲秒數), ...]（短於 5 幀的碎句由呼叫方先濾掉）
    回傳 (全曲半音偏移, 低音時長占比)：12.0 或 0.0，絕不出現第三種值。
    用發聲時長加權而非句數——一句短唸白不該翻轉整首歌的判決。
    """
    total = 0.0
    low = 0.0
    for med, dur in phrase_stats or []:
        try:
            med_f = float(med)
            dur_f = float(dur)
        except (TypeError, ValueError):
            continue
        if dur_f <= 0:
            continue
        total += dur_f
        if med_f < threshold:
            low += dur_f
    if total <= 0:
        return 0.0, 0.0
    ratio = low / total
    if ratio >= low_dominance:
        return float(shift_semitones), ratio
    return 0.0, ratio
