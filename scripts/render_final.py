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
        pending = {}
        notes = []
        for msg in track:
            abs_t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "note_on" and msg.velocity > 0:
                pending.setdefault(msg.note, []).append((abs_t, msg.velocity))
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                q = pending.get(msg.note) or []
                if q:
                    s, v = q.pop(0)
                    notes.append((s, msg.note, v, max(0.05, abs_t - s)))
        for s, midi, vel, dur in notes:
            dur = min(dur + 0.15, 3.0)  # 真實時值＋15% 自然延音（鼓類短音不糊）
            if name == "Drums":
                w = bank.render_note(bk, prog, midi, vel, dur, SR, attack_ms=1.0, release_ms=5.0)
            else:
                w = bank.render_note(bk, prog, midi, vel, dur, SR)
            idx = int(s * SR)
            end = min(len(master), idx + len(w))
            if idx < len(master):
                master[idx:end] += w[:end - idx] * (0.8 if name == "Drums" else 1.0)
    # 原音人聲疊頂
    voc, sr = sf.read(os.path.join(BASE, "data", "stem_pack", "x8jAY2CoOBg", "vocals.wav"),
                      dtype="float32", always_2d=True)
    if sr != SR:
        import librosa
        voc = np.stack([librosa.resample(voc[:, c], orig_sr=sr, target_sr=SR)
                        for c in range(voc.shape[1])], axis=1)
    # ── 混音台：立體聲＋EQ 配平＋殘響＋膠水（對標原曲 width 0.42／crest 3.2）──
    def Schroeder(x, sr=SR):
        from scipy import signal as _ss
        y = np.zeros_like(x)
        for d_ms, g in ((29.7, 0.75), (33.7, 0.74), (36.6, 0.73), (42.7, 0.72)):
            d = int(sr * d_ms / 1000)
            b = np.zeros(d + 1)
            b[0], b[d] = 1.0, g
            a = np.zeros(d + 1)
            a[0], a[d] = 1.0, g
            y = y + _ss.lfilter(b, a, x)
        y /= 4.0
        for d_ms, g in ((5.0, 0.6), (1.7, 0.6)):
            d = int(sr * d_ms / 1000)
            b = np.zeros(d + 1)
            b[0], b[d] = -g, 1.0
            a = np.zeros(d + 1)
            a[0], a[d] = 1.0, -g
            y = _ss.lfilter(b, a, y)
        return y

    def eq_match(x, sr=SR):
        import librosa
        S = librosa.stft(x, n_fft=4096)
        fr = librosa.fft_frequencies(sr=sr, n_fft=4096)
        # 目標＝原曲－渲染（dB，上限 ±6）：sub+5.4 high-1.8 air+1.5
        targets = [((20, 120), 5.0), ((120, 500), 0.0), ((500, 2000), 0.0),
                   ((2000, 8000), -1.8), ((8000, 20000), 1.5)]
        g = np.ones(S.shape[0])
        for (lo, hi), db in targets:
            g[(fr >= lo) & (fr < hi)] = 10.0 ** (db / 20.0)
        y = librosa.istft(S * g[:, None], length=len(x))
        return y

    def glue(x, sr=SR, thr_db=-18.0, ratio=4.0):
        thr = 10.0 ** (thr_db / 20.0)
        hop = 256
        fr = np.abs(x[::hop])
        a_a, a_r = np.exp(-hop / (sr * 0.005)), np.exp(-hop / (sr * 0.150))
        e = 0.0
        env = np.empty_like(fr)
        for i, a in enumerate(fr):
            e = a_a * e + (1 - a_a) * a if a > e else a_r * e + (1 - a_r) * a
            env[i] = e
        env = np.repeat(env, hop)[:len(x)]
        gain = np.where(env > thr, (thr + (env - thr) / ratio) / (env + 1e-9), 1.0)
        y = x * gain
        y /= max(1e-9, np.max(np.abs(y))) / (10.0 ** (-1.0 / 20.0))
        return y

    mono = master / max(1e-9, np.max(np.abs(master)))
    mono = eq_match(mono)
    wet = Schroeder(mono) * 0.10          # 空間殘響（再收斂）
    dry = mono * 0.95
    haas = int(SR * 0.005)                # 5ms Haas（對標 width ~0.42）
    L = np.concatenate([dry + wet, np.zeros(haas)])
    R = np.concatenate([np.zeros(haas), dry + wet])
    stereo = np.column_stack((L, R))
    stereo = np.stack([glue(stereo[:, c], thr_db=-22.0, ratio=5.0) for c in range(2)], axis=1)
    n = min(len(stereo), len(voc))
    mix = stereo[:n] * 0.8 + voc[:n] * 1.0
    # 寬度自動對標 0.42：只收人聲側邊（靜態增益，無 pumping）
    L0, R0 = mix[:, 0].copy(), mix[:, 1].copy()
    _m, _s = (L0 + R0) / 2, (L0 - R0) / 2
    _w = float(np.sqrt((_s ** 2).mean()) / (np.sqrt((_m ** 2).mean()) + 1e-9))
    if _w > 0.45:
        _k = 0.42 / _w
        mix[:, 0], mix[:, 1] = _m + _s * _k, _m - _s * _k
    mix = np.stack([glue(mix[:, c], thr_db=-22.0, ratio=5.0) for c in range(2)], axis=0).T
    mix = np.tanh(mix * 0.85)
    mix /= max(1e-6, np.max(np.abs(mix)))
    mix *= 10.0 ** (-1.0 / 20.0)  # 軟上限 -1dBFS（處方，不靠 peak normalize 撐）
    out = os.path.join(BASE, "songs_ai", "sun_burn_out_final.wav")
    sf.write(out, mix.astype(np.float32), SR)
    print("WAV:", out, f"({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
