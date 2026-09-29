# -*- coding: utf-8 -*-
"""真譜 SoundFont 渲染：sun_burn_out_true.mid → WAV（Yamaha 大鋼琴＋貝斯＋真鼓組）。
用法：python scripts/render_sf.py [mid檔] [wav檔]
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np

SR = 44100
SF2 = os.path.join(BASE, "soundfonts", "FluidR3_GM_GS.sf2")
VOICES = {0: (0, 0), 1: (0, 33), 9: (128, 0)}  # ch -> (bank, program)


def main(mid_path=None, wav_path=None):
    import mido
    import soundfile as sf
    from services.soundfont import SoundFontBank

    mid_path = mid_path or os.path.join(BASE, "midi_sheets", "sun_burn_out_true.mid")
    wav_path = wav_path or os.path.join(BASE, "songs_ai", "sun_burn_out_sf.wav")
    bank = SoundFontBank(SF2)
    mid = mido.MidiFile(mid_path)
    tempo = next((m.tempo for t in mid.tracks for m in t if m.type == "set_tempo"), 500000)
    total = float(mid.length) + 3.0
    master = np.zeros(int(SR * total) + 8, dtype=np.float64)
    for track in mid.tracks:
        abs_t = 0.0
        for msg in track:
            abs_t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "note_on" and msg.velocity > 0:
                ch = getattr(msg, "channel", 0)
                bk, prog = VOICES.get(ch, (0, 0))
                dur = 2.0
                w = bank.render_note(bk, prog, msg.note, msg.velocity, dur, SR)
                idx = int(abs_t * SR)
                end = min(len(master), idx + len(w))
                if idx < len(master):
                    master[idx:end] += w[:end - idx] * (0.8 if ch == 9 else 1.0)
    master = np.tanh(master * 0.85)
    master /= max(1e-6, np.max(np.abs(master)))
    os.makedirs(os.path.dirname(wav_path), exist_ok=True)
    sf.write(wav_path, np.column_stack((master, master)).astype(np.float32) * 0.9, SR)
    print("WAV:", wav_path, f"({os.path.getsize(wav_path)//1024} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:3] if len(sys.argv) > 2 else (None, None))
