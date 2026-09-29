# -*- coding: utf-8 -*-
"""真譜演奏渲染：sun_burn_out_true.mid → WAV（分軌音色重塑：主奏驅動＋貝斯下潛＋總線膠水）。
用法：python scripts/render_true.py
"""
import os
import sys

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np

SR = 44100


def drive(x, amount=2.0):
    return np.tanh(x * amount)


def main():
    import pygame
    pygame.mixer.init(frequency=SR, size=-16, channels=2)
    from services.piano_engine import generate_piano_tone
    import pygame.sndarray
    import mido
    import soundfile as sf

    mid = mido.MidiFile(os.path.join(BASE, "midi_sheets", "sun_burn_out_true.mid"))
    total = float(mid.length) + 3.0
    master = np.zeros(int(SR * total), dtype=np.float64)

    def tone(note, vel, dur, bright=1.0, sub=0.0):
        snd = generate_piano_tone(note, duration=min(dur + 1.0, 3.0))
        arr = pygame.sndarray.array(snd).astype(np.float64).mean(axis=1)
        if sub > 0:  # 貝斯下潛：混入基頻正弦
            n = len(arr)
            t = np.linspace(0, n / SR, n, False)
            f0 = 440.0 * (2.0 ** ((note - 69) / 12.0))
            arr = arr * (1 - sub) + (np.sin(2 * np.pi * f0 * t) * sub)
        return arr * (vel / 90.0) * bright

    def drum(kind):
        if kind == 36:
            n = int(SR * 0.35)
            t = np.linspace(0, 0.35, n, False)
            f = 55 + 45 * np.exp(-t * 28)
            return (np.sin(np.cumsum(f) / SR * 2 * np.pi) * np.exp(-t * 11)).astype(np.float32)
        if kind == 38:
            n = int(SR * 0.3)
            t = np.linspace(0, 0.3, n, False)
            return ((np.sin(2 * np.pi * 195 * t) * np.exp(-t * 24) * 0.5
                     + (np.random.rand(n) * 2 - 1) * np.exp(-t * 28) * 0.45)).astype(np.float32)
        n = int(SR * 0.12)
        t = np.linspace(0, 0.12, n, False)
        return ((np.random.rand(n) * 2 - 1) * np.exp(-t * 85) * 0.3).astype(np.float32)

    for track in mid.tracks:
        abs_t = 0.0
        for msg in track:
            abs_t += mido.tick2second(msg.time, mid.ticks_per_beat,
                                      next((m.tempo for m in track if m.type == "set_tempo"), 500000))
            # 簡化：用首個 tempo（全曲統一 1000000）
            if msg.type == "note_on" and msg.velocity > 0:
                ch = getattr(msg, "channel", 0)
                idx = int(abs_t * SR)
                if ch == 0:
                    w = drive(tone(msg.note, msg.velocity, 0.6), 1.8) * 0.75
                elif ch == 1:
                    w = tone(max(21, msg.note), msg.velocity, 0.7, sub=0.55) * 0.7
                else:
                    w = drum(msg.note) * 0.85
                end = min(len(master), idx + len(w))
                if idx < len(master):
                    master[idx:end] += w[:end - idx]
    # 總線膠水：輕壓縮＋正規化
    master = np.tanh(master * 0.9)
    master /= max(1e-6, np.max(np.abs(master)))
    out = os.path.join(BASE, "songs_ai", "sun_burn_out_true.wav")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sf.write(out, np.column_stack((master, master)).astype(np.float32) * 0.88, SR)
    print("WAV:", out, f"({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
