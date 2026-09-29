# -*- coding: utf-8 -*-
"""真譜重建＋驗證（anthem vocals → sun_burn_out_true.mid）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from services import audio_to_score as ats

mel = ats.transcribe_melody("data/score_in/demucs_out/htdemucs/anthem/vocals.wav")
cho = ats.detect_chords("data/score_in/anthem.m4a", seg_sec=8.0)
f = ats.write_score_midi("sun_burn_out_true", mel, cho)

import mido
mid = mido.MidiFile(f)
for t in mid.tracks:
    n = sum(1 for m in t if m.type == "note_on" and m.velocity > 0)
    print("track", getattr(t, "name", ""), "notes:", n)
print("length:", round(mid.length, 1))
print("file:", f)
