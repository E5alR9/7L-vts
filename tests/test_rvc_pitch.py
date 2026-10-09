# -*- coding: utf-8 -*-
"""RVC 整首統一音域判決（2026-10-09：混合音域同首歌忽高忽低 → 整首統一）。"""
from conftest import ROOT  # noqa: F401
import pytest
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


def _sine_wav(path, freq, seconds=4.0, sr=16000, stereo=True):
    import numpy as np
    import soundfile as sf
    t = np.arange(int(sr * seconds)) / sr
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    data = np.stack([mono, mono * 0.9]) .T if stereo else mono
    sf.write(str(path), data, sr)


def _peak_hz(path):
    import numpy as np
    import soundfile as sf
    data, sr = sf.read(str(path), always_2d=True)
    spec = np.abs(np.fft.rfft(data[:, 0] * np.hanning(len(data))))
    freqs = np.fft.rfftfreq(len(data), 1.0 / sr)
    return float(freqs[int(np.argmax(spec[1:])) + 1]), data.shape, sr


def test_analyze_vocal_range_on_tones(tmp_path):
    from services.rvc_pitch import analyze_vocal_range
    p = tmp_path / "hi.wav"
    _sine_wav(p, 440.0)
    med, p90, vs = analyze_vocal_range(str(p))
    assert med == pytest.approx(440.0, abs=8.0)
    assert p90 == pytest.approx(440.0, abs=8.0)
    assert vs > 3.0
    p2 = tmp_path / "lo.wav"
    _sine_wav(p2, 150.0)
    med2, _, _ = analyze_vocal_range(str(p2))
    assert med2 == pytest.approx(150.0, abs=8.0)
    # 空檔／不存在 → 保守 None
    assert analyze_vocal_range(str(tmp_path / "nope.wav")) == (None, None, 0.0)


def test_shift_octave_direction_and_shape(tmp_path):
    from services.rvc_pitch import shift_octave_file
    src = tmp_path / "src.wav"
    _sine_wav(src, 440.0)
    down = tmp_path / "down.wav"
    assert shift_octave_file(str(src), str(down), -12.0) is True
    f_down, shape_down, _ = _peak_hz(down)
    assert f_down == pytest.approx(220.0, rel=0.03)
    assert shape_down[1] == 2  # 立體聲 preserved
    up = tmp_path / "up.wav"
    assert shift_octave_file(str(src), str(up), 12.0) is True
    f_up, _, _ = _peak_hz(up)
    assert f_up == pytest.approx(880.0, rel=0.03)


def test_shift_roundtrip_preserves_pitch_and_duration(tmp_path):
    # -12 再 +12：回到原調、時長不漂移（±1%）、聲道不變
    import soundfile as sf
    from services.rvc_pitch import shift_octave_file
    src = tmp_path / "src.wav"
    _sine_wav(src, 440.0, seconds=5.0)
    mid = tmp_path / "mid.wav"
    back = tmp_path / "back.wav"
    assert shift_octave_file(str(src), str(mid), -12.0) is True
    assert shift_octave_file(str(mid), str(back), 12.0) is True
    f_back, shape_back, _ = _peak_hz(back)
    assert f_back == pytest.approx(440.0, rel=0.03)
    d0, _ = sf.read(str(src), always_2d=True)
    d1, _ = sf.read(str(back), always_2d=True)
    assert abs(len(d1) - len(d0)) / len(d0) <= 0.01
    assert d1.shape[1] == d0.shape[1] == 2


def _hot_sine(path, peak=0.98, freq=440.0, seconds=3.0, sr=16000):
    import numpy as np
    import soundfile as sf
    t = np.arange(int(sr * seconds)) / sr
    mono = (peak * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), np.stack([mono, mono * 0.9]).T, sr)


def test_gain_staging_never_clips(tmp_path):
    # 熱母帶（peak 0.98）進出都不許削波：成品硬天花板 0.95
    import numpy as np
    import soundfile as sf
    from services.rvc_pitch import shift_octave_file, DSP_CEILING
    src = tmp_path / "hot.wav"
    _hot_sine(src)
    out = tmp_path / "out.wav"
    assert shift_octave_file(str(src), str(out), 12.0) is True
    data, _ = sf.read(str(out), always_2d=True)
    peak = float(np.max(np.abs(data)))
    # int16 量化步進 3e-5：天花板 0.95 存檔後約 0.95001，重點是絕不出現滿幅削波點
    assert peak <= DSP_CEILING + 5e-5
    assert int(np.sum(np.abs(data) >= 0.999)) == 0
    # 原檔沒被動到（headroom 用的是拷貝）
    d0, _ = sf.read(str(src), always_2d=True)
    assert float(np.max(np.abs(d0))) > 0.97


def test_librosa_fallback_path(monkeypatch, tmp_path):
    # ffmpeg 指到空包 → 強制走 librosa 備援：照樣保調保時長，增益管制照樣生效
    import numpy as np
    import soundfile as sf
    from services.rvc_pitch import shift_octave_file, DSP_CEILING
    monkeypatch.setenv("FFMPEG_EXE", "nonexistent-ffmpeg-xyz")
    src = tmp_path / "hot2.wav"
    _hot_sine(src)
    out = tmp_path / "out2.wav"
    assert shift_octave_file(str(src), str(out), -12.0) is True
    data, sr = sf.read(str(out), always_2d=True)
    assert float(np.max(np.abs(data))) <= DSP_CEILING + 5e-5
    assert int(np.sum(np.abs(data) >= 0.999)) == 0
    spec = np.abs(np.fft.rfft(data[:, 0] * np.hanning(len(data))))
    freqs = np.fft.rfftfreq(len(data), 1.0 / sr)
    peak_f = float(freqs[int(np.argmax(spec[1:])) + 1])
    assert peak_f == pytest.approx(220.0, rel=0.03)
