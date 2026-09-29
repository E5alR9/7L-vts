# -*- coding: utf-8 -*-
"""分軌轉譜＋原音重組：每軌獨立轉 MIDI（吉他/鋼琴 multi-pitch、貝斯單音、鼓 onset 分類），
人聲用原本的。用法見 transcribe_stems()。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np


def transcribe_stem_notes(path: str, lo=21, hi=108, min_dur=0.06):
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH
    _, _, evs = predict(path, ICASSP_2022_MODEL_PATH)
    out = []
    for ev in (evs or []):
        s, e, p = float(ev[0]), float(ev[1]), int(ev[2])
        v = float(ev[3]) if len(ev) > 3 else 0.8
        if lo <= p <= hi and e - s >= min_dur:
            out.append((round(s, 2), p, round(e - s, 2), max(40, min(127, int(v * 127)))))
    out.sort()
    return out


def transcribe_drums(path: str, mix_path: str = ""):
    """onset＋頻譜分類 → [(sec, 鼓件, vel)]。36 kick／38 snare／42 hat／49 crash。
    大鼓從整軌低頻抓（分離鼓組常丟失大鼓低頻）。"""
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    onset = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    S = np.abs(librosa.stft(y, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    times = librosa.times_like(S, sr=sr)
    out = []
    cent = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    for t in onset:
        i = int(np.argmin(np.abs(times - t)))
        j = min(i + 3, len(cent) - 1)
        c = float(cent[j])
        if c > 5500:
            col = S[:, j] + 1e-9
            mid_e = col[(freqs > 300) & (freqs <= 3000)].sum() / col.sum()
            out.append((round(float(t), 2), 49 if mid_e > 0.35 else 42, 70))
        else:
            out.append((round(float(t), 2), 38, 88))
    if mix_path and os.path.exists(mix_path):
        try:
            import scipy.signal as _ss
            ym, _ = librosa.load(mix_path, sr=22050, mono=True)
            b, a = _ss.butter(4, 120 / (22050 / 2), btype="low")
            low = _ss.filtfilt(b, a, ym)
            k_on = librosa.onset.onset_detect(y=low, sr=22050, units="time",
                                              backtrack=True, delta=0.08, wait=5)
            snare_t = {s for s, n, _ in out if n == 38}
            for t in k_on:
                t = round(float(t), 2)
                if all(abs(t - s) > 0.06 for s in snare_t):
                    out.append((t, 36, 95))
        except Exception:
            pass
    out.sort()
    return out


def main():
    from services import audio_to_score as ats
    import mido

    d = r"C:\Users\CPXru\Desktop\thumb\大拇哥實驗室\ai_vtuber\data\stem_pack\x8jAY2CoOBg"
    stems = {}
    for s, lo, hi in [("guitar", 28, 96), ("piano", 21, 108), ("bass", 21, 70), ("other", 21, 108)]:
        p = os.path.join(d, f"{s}.wav")
        if os.path.exists(p):
            stems[s] = transcribe_stem_notes(p, lo, hi)
            print(s, len(stems[s]))
    drums = transcribe_drums(os.path.join(d, "drums.wav"),
                             r"C:\Users\CPXru\Desktop\thumb\大拇哥實驗室\ai_vtuber\data\score_in\anthem.m4a")
    print("drums", len(drums), drums[:8])

    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    chmap = {"guitar": (0, 30), "piano": (2, 0), "bass": (1, 33), "other": (3, 48)}
    for name, (ch, prog) in chmap.items():
        t = mido.MidiTrack()
        t.append(mido.MetaMessage("track_name", name=name.capitalize(), time=0))
        t.append(mido.MetaMessage("set_tempo", tempo=1000000, time=0))
        t.append(mido.Message("program_change", program=prog, channel=ch, time=0))
        mid.tracks.append(t)
    dt = mido.MidiTrack()
    dt.append(mido.MetaMessage("track_name", name="Drums", time=0))
    mid.tracks.append(dt)

    def fill(track, notes, ch, dur_scale=1.0):
        evs = []
        for s, n, dd, v in notes:
            t0 = int(s * 480)
            evs.append((t0, "note_on", n, v, ch))
            evs.append((t0 + max(30, int(dd * 480 * dur_scale)), "note_off", n, 0, ch))
        evs.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
        last = 0
        for tick, typ, nn, vv, ch in evs:
            track.append(mido.Message(typ, note=nn, velocity=vv, channel=ch, time=max(0, tick - last)))
            last = tick

    idx = {"guitar": 0, "piano": 1, "bass": 2, "other": 3}
    for name, notes in stems.items():
        fill(mid.tracks[idx[name]], notes, chmap[name][0])
    devs = []
    for s, nn, v in drums:
        t0 = int(s * 480)
        devs.append((t0, "note_on", nn, v, 9))
        devs.append((t0 + 40, "note_off", nn, 0, 9))
    devs.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    last = 0
    for tick, typ, nn, vv, ch in devs:
        dt.append(mido.Message(typ, note=nn, velocity=vv, channel=ch, time=max(0, tick - last)))
        last = tick
    out = os.path.join(r"C:\Users\CPXru\Desktop\thumb\大拇哥實驗室\ai_vtuber", "midi_sheets",
                       "sun_burn_out_band.mid")
    mid.save(out)
    print("BAND MID:", out, "len:", round(mid.length, 1))


if __name__ == "__main__":
    main()
