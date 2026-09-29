# -*- coding: utf-8 -*-
"""搖滾版重渲染：失真主音＋強力五和弦節奏吉他＋貝斯＋鼓（旋律八度折疊清理）。
用法：python scripts/render_rock.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np

SR = 44100
SF2 = os.path.join(BASE, "soundfonts", "FluidR3_GM_GS.sf2")


def fold(midi, lo=57, hi=81):
    while midi < lo:
        midi += 12
    while midi > hi:
        midi -= 12
    return midi


def main():
    import mido
    import soundfile as sf
    from services.soundfont import SoundFontBank
    from services import audio_to_score as ats

    bank = SoundFontBank(SF2)
    mid = mido.MidiFile(os.path.join(BASE, "midi_sheets", "sun_burn_out_true.mid"))
    tempo = next((m.tempo for t in mid.tracks for m in t if m.type == "set_tempo"), 500000)

    def to_sec(track):
        abs_t, out = 0.0, []
        for msg in track:
            abs_t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "note_on" and msg.velocity > 0:
                out.append((abs_t, msg.note, msg.velocity))
        return out

    tracks = {getattr(t, "name", ""): to_sec(t) for t in mid.tracks}
    mel = [(s, fold(n), v) for s, n, v in tracks.get("Melody", [])]
    bass = [(s, max(28, min(52, n)), v) for s, n, v in tracks.get("BassRoots", [])]

    cho = ats.detect_chords(os.path.join(BASE, "data", "score_in", "anthem.m4a"), seg_sec=4.0)
    names = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
             "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    import re
    segs = []
    for i, (t, n) in enumerate(cho):
        m = re.match(r"([A-G]#?)", n)
        if not m:
            continue
        nxt = cho[i + 1][0] if i + 1 < len(cho) else t + 8.0
        segs.append((t, min(nxt, t + 16.0), names[m.group(1)] + 12 + 24))  # E2 附近根音

    total = float(mid.length) + 3.0
    master = np.zeros(int(SR * total) + 8, dtype=np.float64)

    def put(sec, bank_no, prog, midi, vel, dur, gain=1.0):
        w = bank.render_note(bank_no, prog, midi, vel, dur, SR)
        idx = int(sec * SR)
        end = min(len(master), idx + len(w))
        if idx < len(master):
            master[idx:end] += w[:end - idx] * gain

    for s, n, v in mel:  # 失真主音
        put(s, 0, 30, n, min(127, v + 10), 1.2, 0.85)
    for t0, t1, root in segs:  # 強力五和弦 8 分音符悶音
        t = t0
        while t < t1:
            for nn in (root, root + 7):
                put(t, 0, 30, nn, 82, 0.4, 0.55)
            t += 0.25
    for s, n, v in bass:  # 指彈貝斯
        put(s, 0, 33, n, v, 1.5, 0.8)
    for t in mid.tracks:  # 原鼓組照搬
        if getattr(t, "name", "") != "Drums":
            continue
        abs_t = 0.0
        for msg in t:
            abs_t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "note_on" and msg.velocity > 0:
                put(abs_t, 128, 0, msg.note, msg.velocity, 0.5, 0.9)

    master = np.tanh(master * 0.8)
    master /= max(1e-6, np.max(np.abs(master)))
    out = os.path.join(BASE, "songs_ai", "sun_burn_out_rock.wav")
    sf.write(out, np.column_stack((master, master)).astype(np.float32) * 0.9, SR)
    print("WAV:", out, f"({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
