# -*- coding: utf-8 -*-
"""終極還原混音：SoundFont 樂隊（分軌轉譜 MIDI）＋原音人聲。
用法：python scripts/render_final.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np

SR = 44100
SF2 = os.path.join(BASE, "soundfonts", "FluidR3_GM_GS.sf2")
VOICES = {"Guitar": (0, 30), "Piano": None, "BassRoots": (0, 33),
          "Other": (0, 48), "Drums": (128, 0)}  # Piano=None：原曲無鋼琴（分離桶誤判，直接靜音）


def main():
    import mido
    import soundfile as sf
    from services.soundfont import SoundFontBank

    bank = SoundFontBank(SF2)
    mid = mido.MidiFile(os.path.join(BASE, "midi_sheets", "sun_burn_out_band.mid"))
    tempo = next((m.tempo for t in mid.tracks for m in t if m.type == "set_tempo"), 500000)
    total = float(mid.length) + 3.0
    master = np.zeros(int(SR * total) + 8, dtype=np.float64)
    for track in mid.tracks:
        name = getattr(track, "name", "")
        if name not in VOICES or VOICES[name] is None:
            continue  # 未列名或靜音軌跳過
        bk, prog = VOICES[name]
        abs_t = 0.0
        for msg in track:
            abs_t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "note_on" and msg.velocity > 0:
                w = bank.render_note(bk, prog, msg.note, msg.velocity, 1.5, SR)
                idx = int(abs_t * SR)
                end = min(len(master), idx + len(w))
                if idx < len(master):
                    master[idx:end] += w[:end - idx] * 0.7
    # 原音人聲疊頂
    voc, sr = sf.read(os.path.join(BASE, "data", "stem_pack", "x8jAY2CoOBg", "vocals.wav"),
                      dtype="float32", always_2d=True)
    if sr != SR:
        import librosa
        voc = np.stack([librosa.resample(voc[:, c], orig_sr=sr, target_sr=SR)
                        for c in range(voc.shape[1])], axis=1)
    n = min(len(master), len(voc))
    mix = np.column_stack((master, master))[:n] * 0.8 + voc[:n] * 1.0
    mix = np.tanh(mix * 0.85)
    mix /= max(1e-6, np.max(np.abs(mix)))
    out = os.path.join(BASE, "songs_ai", "sun_burn_out_final.wav")
    sf.write(out, (mix * 0.9).astype(np.float32), SR)
    print("WAV:", out, f"({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
