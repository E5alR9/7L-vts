# -*- coding: utf-8 -*-
"""逆向譜面純函式測試（合成和弦辨識＋出譜回讀）"""
import numpy as np
from conftest import ROOT  # noqa: F401
from services import audio_to_score as ats


def _chord_wav(path, freqs_list, sr=22050, each=4.0):
    import soundfile as sf
    y = np.zeros(int(sr * each * len(freqs_list)), dtype=np.float32)
    for i, freqs in enumerate(freqs_list):
        t = np.linspace(0, each, int(sr * each), False)
        seg = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
        seg = seg * np.exp(-t * 0.1)
        y[i * len(seg):(i + 1) * len(seg)] = seg.astype(np.float32)
    sf.write(path, y, sr)


def test_detect_chords_synthetic(tmp_path):
    # C 大三 (261.63/329.63/392.00) → G 大三 (392/493.88/587.33)
    p = str(tmp_path / "chords.wav")
    _chord_wav(p, [[261.63, 329.63, 392.00], [392.00, 493.88, 587.33]])
    out = ats.detect_chords(p, seg_sec=4.0)
    names = [n for _, n in out]
    assert names[0] == "C", names
    assert "G" in names, names


def test_write_score_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = ats.write_score_midi("t_trans", [(60, 0.0, 0.5, 90), (64, 0.5, 0.5, 90)],
                             [(0.0, "C"), (4.0, "G")])
    assert f and f.endswith(".mid")
    import mido
    import os
    mid = mido.MidiFile(f)
    assert len(mid.tracks) == 3
    chs = {m.channel for t in mid.tracks for m in t if m.type == "note_on"}
    assert chs == {0, 1, 9}
    os.remove(f)  # 測試產物不留曲庫
