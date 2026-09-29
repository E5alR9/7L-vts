# -*- coding: utf-8 -*-
"""冠軍聖歌風改編演奏 → 離線渲染 WAV＋出譜 .mid（SDL dummy 音訊驅動，無需音效卡）。
用法：python scripts/render_anthem.py
產物：songs_ai/anthem_sun_burn_out.wav ＋ midi_sheets/anthem_sun_burn_out.mid
聲明：致敬改編（E 小調史詩風），非原曲複刻；原曲 9/16 剛發，無現成鋼琴譜。
"""
import os
import sys

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np

SR = 44100
BPM = 100
BEAT = 60.0 / BPM

# E 自然小調：E F# G A B C D
CHORDS = {  # 名: (bass_root, 和弦音)
    "Em": (40, [52, 55, 59]),
    "C": (48, [48, 52, 55]),
    "G": (43, [55, 59, 62]),
    "D": (50, [54, 57, 62]),
}
VERSE = ["Em", "Em", "C", "C", "G", "G", "D", "D"]
CHORUS = ["Em", "C", "G", "D", "Em", "C", "D", "Em"]

VERSE_MEL = [  # (midi, 起拍, 時值拍, 力度)
    (76, 0, 2, 80), (79, 2, 2, 78),
    (81, 4, 2, 80), (79, 6, 2, 76),
    (76, 8, 2, 78), (74, 10, 2, 76),
    (72, 12, 2, 78), (74, 14, 2, 80),
    (76, 16, 4, 85), (79, 20, 2, 82),
    (81, 22, 2, 84), (83, 24, 4, 86),
    (81, 28, 2, 82), (79, 30, 2, 80),
]
CHORUS_MEL = [
    (76, 0, 1, 92), (79, 1, 1, 92), (81, 2, 1, 94), (83, 3, 1, 96),
    (84, 4, 2, 98), (83, 6, 1, 94), (81, 7, 1, 92),
    (83, 8, 2, 96), (81, 10, 1, 92), (79, 11, 1, 90),
    (81, 12, 2, 94), (83, 13, 1, 96), (86, 14, 1, 98), (88, 15, 1, 100),
    (88, 16, 2.5, 102), (86, 18.5, 0.5, 96), (84, 19, 1, 94),
    (83, 20, 2, 96), (81, 22, 1, 92), (79, 23, 1, 90),
    (81, 24, 1.5, 94), (83, 25.5, 0.5, 96), (86, 26, 1, 98), (88, 27, 1, 100),
    (88, 28, 4, 104),
]

KICK, SNARE, HAT = 36, 38, 42


def drum_hit(kind, dur=0.4):
    n = int(SR * dur)
    t = np.linspace(0, dur, n, False)
    if kind == KICK:
        f = 55 + 40 * np.exp(-t * 30)
        ph = np.cumsum(f) / SR * 2 * np.pi
        return (np.sin(ph) * np.exp(-t * 12) * 0.9).astype(np.float32)
    if kind == SNARE:
        tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25) * 0.5
        noise = (np.random.rand(n) * 2 - 1) * np.exp(-t * 30) * 0.4
        return (tone + noise).astype(np.float32)
    noise = (np.random.rand(n) * 2 - 1) * np.exp(-t * 90) * 0.25
    return noise.astype(np.float32)


def main():
    import pygame
    pygame.mixer.init(frequency=SR, size=-16, channels=2)
    from services.piano_engine import generate_piano_tone
    import pygame.sndarray

    events = []  # (sec, kind, payload)
    total_beats = 0

    def add_section(chords, mel, bar0, drums_full):
        for i, ch in enumerate(chords):
            root, tones = CHORDS[ch]
            b = bar0 + i * 4
            for beat in range(4):  # 鋼琴分解 8 分音符
                for half in range(2):
                    nn = tones[(beat * 2 + half) % len(tones)] + (12 if half else 0)
                    events.append(((b + beat + half * 0.5) * BEAT, "piano", (nn, 70)))
            for beat in range(4):  # 貝斯根音
                events.append(((b + beat) * BEAT, "bass", (root, 85)))
            for beat in range(4):  # 鼓
                events.append(((b + beat) * BEAT, "kick", ()))
                if drums_full and beat in (1, 3):
                    events.append(((b + beat) * BEAT, "snare", ()))
                for half in range(2):
                    events.append(((b + beat + half * 0.5) * BEAT, "hat", ()))
        for midi, sb, db, vel in mel:
            events.append(((bar0 + sb) * BEAT, "lead", (midi + 12 if midi < 76 else midi, vel)))

    add_section(VERSE, VERSE_MEL, 0, drums_full=False)
    add_section(CHORUS, CHORUS_MEL, 32, drums_full=True)
    total_sec = 64 * 4 * BEAT + 3.0
    master = np.zeros(int(SR * total_sec), dtype=np.float64)

    def tone(note, vel, dur):
        snd = generate_piano_tone(note, duration=min(dur + 1.2, 4.0))
        arr = pygame.sndarray.array(snd).astype(np.float64).mean(axis=1)
        return arr * (vel / 90.0)

    for sec, kind, pay in sorted(events):
        idx = int(sec * SR)
        if kind == "piano":
            w = tone(pay[0], pay[1], 0.5) * 0.5
        elif kind == "bass":
            w = tone(max(21, pay[0] - 12), pay[1], 0.8) * 0.65
        elif kind == "lead":
            w = tone(pay[0], pay[1], 1.2) * 0.8
        elif kind == "kick":
            w = drum_hit(KICK) * 0.9
        elif kind == "snare":
            w = drum_hit(SNARE) * 0.8
        else:
            w = drum_hit(HAT, 0.15) * 0.7
        end = min(len(master), idx + len(w))
        if idx < len(master):
            master[idx:end] += w[:end - idx]

    master /= max(1e-6, np.max(np.abs(master)))
    stereo = np.column_stack((master, master))
    out_dir = os.path.join(BASE, "songs_ai")
    os.makedirs(out_dir, exist_ok=True)
    wav_path = os.path.join(out_dir, "anthem_sun_burn_out.wav")
    import soundfile as sf
    sf.write(wav_path, (stereo * 0.88).astype(np.float32), SR)
    print(f"WAV: {wav_path} ({os.path.getsize(wav_path)//1024} KB, {total_sec:.0f}s)")

    # 同步出譜 .mid（旋律＋貝斯＋鼓三軌，進曲庫可直接樂隊演奏）
    import mido
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    for name, prog, ch in [("Lead", 0, 0), ("Bass", 33, 1), ("Drums", None, 9)]:
        mid.tracks.append(mido.MidiTrack())
        mid.tracks[-1].append(mido.MetaMessage("track_name", name=name, time=0))
        if prog is not None:
            mid.tracks[-1].append(mido.Message("program_change", program=prog, channel=ch, time=0))
    evs = []
    for sec, kind, pay in events:
        tick = int(sec / BEAT * 480)
        if kind == "lead":
            evs.append((tick, 0, pay[0], pay[1], 240))
        elif kind == "bass":
            evs.append((tick, 1, max(21, pay[0] - 12), pay[1], 380))
        elif kind in ("kick", "snare", "hat"):
            nn = {"kick": 36, "snare": 38, "hat": 42}[kind]
            evs.append((tick, 9, nn, 90, 60))
    for ch in (0, 1, 9):
        ce = sorted([e for e in evs if e[1] == ch])
        msgs = []
        for tick, _, nn, vel, dur in ce:
            msgs.append((tick, "note_on", nn, vel))
            msgs.append((tick + dur, "note_off", nn, 0))
        msgs.sort(key=lambda x: (x[0], 0 if x[1] == "note_off" else 1))
        cur = 0
        tr = mid.tracks[0] if ch == 0 else (mid.tracks[1] if ch == 1 else mid.tracks[2])
        for tick, typ, nn, vel in msgs:
            tr.append(mido.Message(typ, note=nn, velocity=vel, channel=ch, time=max(0, tick - cur)))
            cur = tick
    mid_path = os.path.join(BASE, "midi_sheets", "anthem_sun_burn_out.mid")
    mid.save(mid_path)
    try:
        from services.piano_engine import save_midi_catalog_entry
        save_midi_catalog_entry("anthem_sun_burn_out", mid_path)
    except Exception as e:
        print("catalog skip:", e)
    print(f"MID: {mid_path}")


if __name__ == "__main__":
    main()
