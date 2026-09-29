# -*- coding: utf-8 -*-
"""
🎧 音檔逆向譜面（Audio → Score）：YT 下載 → 人聲分離 → 旋律轉 MIDI＋和弦辨識 → 進曲庫。
PROVIDER: LOCAL（yt-dlp＋librosa 必備；demucs／basic-pitch 選配，有則用、無則降級）。

管線（每段失敗自動降級，絕不整條炸）：
  download → separate（demucs，無則整軌混音續行）
           → melody（basic-pitch，無則 librosa piptrack 粗追蹤）
           → chords（librosa chroma 模板匹配，零額外依賴）
           → write MIDI（三軌：旋律 ch0／根音貝斯 ch1／鼓 ch9 簡配）→ 曲庫

依賴安裝（需要才裝）：
  python -m pip install demucs basic-pitch
"""
import os
import re
import subprocess
import sys
import time

import numpy as np

from core.utils import log_print

WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "score_in")
os.makedirs(WORK_DIR, exist_ok=True)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
CHORD_TPL = {
    "maj": [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
    "m": [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
}


def download_audio(url_or_id: str) -> str:
    """YT 下載音軌（m4a）。回傳路徑或空字串。"""
    from services.video_watch import normalize_video_url
    vid = normalize_video_url(url_or_id)
    if not vid:
        return ""
    out = os.path.join(WORK_DIR, vid)
    # YT 擋桌機爬蟲（403）→ 改走 android/ios 播放器客戶端
    cmd = [sys.executable, "-m", "yt_dlp", "--extractor-args", "youtube:player_client=android,ios",
           "-x", "--audio-format", "m4a",
           "--no-playlist", "-o", out, f"https://www.youtube.com/watch?v={vid}"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600)
        if p.returncode != 0:
            log_print(f"⚠️ [逆向譜面] 下載失敗: {(p.stderr or '')[-150:]}")
            return ""
    except Exception as e:
        log_print(f"⚠️ [逆向譜面] 下載異常: {e}")
        return ""
    for f in sorted(os.listdir(WORK_DIR)):
        if f.startswith(vid) and f.endswith((".m4a", ".mp3", ".opus", ".webm")):
            return os.path.join(WORK_DIR, f)
    return ""


def separate_vocals(audio_path: str) -> str:
    """demucs 人聲分離 → vocals.wav；無 demucs 回原檔（整軌續行）。"""
    try:
        import demucs  # noqa
    except ImportError:
        log_print("ℹ️ [逆向譜面] 無 demucs，用整軌混音續行（可 pip install demucs 升級）")
        return audio_path
    out_dir = os.path.join(WORK_DIR, "demucs_out")
    cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", out_dir, audio_path]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800)
        base = os.path.splitext(os.path.basename(audio_path))[0]
        cand = os.path.join(out_dir, "htdemucs", base, "vocals.wav")
        if p.returncode == 0 and os.path.exists(cand):
            return cand
    except Exception as e:
        log_print(f"⚠️ [逆向譜面] 分離異常: {e}")
    return audio_path


def _load_mono(path: str, sr: int = 22050):
    import librosa
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y, sr


def transcribe_melody(audio_path: str) -> list:
    """旋律轉音符 [(midi, 起秒, 時值秒, 力度)]。basic-pitch 優先，無則 piptrack 粗追蹤。"""
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
        _, _, note_events = predict(audio_path, ICASSP_2022_MODEL_PATH)
        notes = []
        for ev in (note_events or []):
            start, end, pitch = float(ev[0]), float(ev[1]), int(ev[2])
            vel = float(ev[3]) if len(ev) > 3 else 0.8
            if 21 <= pitch <= 108 and end - start >= 0.08:
                notes.append((pitch, round(start, 2),
                              round(end - start, 2), max(40, min(127, int(vel * 127)))))
        notes.sort(key=lambda n: n[1])
        log_print(f"🎼 [逆向譜面] basic-pitch 轉出 {len(notes)} 音符")
        log_print(f"🎼 [逆向譜面] basic-pitch 轉出 {len(notes)} 音符")
        return notes
    except ImportError:
        log_print("ℹ️ [逆向譜面] 無 basic-pitch，用 piptrack 粗追蹤（可 pip install basic-pitch 升級）")
    except Exception as e:
        log_print(f"⚠️ [逆向譜面] basic-pitch 異常，退 piptrack: {e}")
    try:
        import librosa
        y, sr = _load_mono(audio_path)
        S = np.abs(librosa.stft(y, n_fft=2048))
        fmin, fmax = librosa.midi_to_hz(40), librosa.midi_to_hz(84)
        pitches, mags = librosa.piptrack(S=S, sr=sr, fmin=fmin, fmax=fmax)
        times = librosa.times_like(S, sr=sr)
        notes, cur, cur_t0 = [], None, 0.0
        for i in range(0, pitches.shape[1], 4):
            col, mg = pitches[:, i], mags[:, i]
            idx = int(np.argmax(mg))
            if mg[idx] <= 0 or col[idx] <= 0:
                if cur:
                    notes.append((cur[0], round(cur_t0, 2), round(times[i] - cur_t0, 2), 80))
                    cur = None
                continue
            if mg[idx] < np.median(mg) * 3:
                if cur:
                    notes.append((cur[0], round(cur_t0, 2), round(times[i] - cur_t0, 2), 80))
                    cur = None
                continue
            midi = int(round(librosa.hz_to_midi(col[idx])))
            if cur and abs(midi - cur[0]) <= 1:
                continue
            if cur:
                notes.append((cur[0], round(cur_t0, 2), round(times[i] - cur_t0, 2), 80))
            cur, cur_t0 = (midi, mg[idx]), times[i]
        return [(m, s, max(0.1, d), v) for m, s, d, v in notes if 21 <= m <= 108]
    except Exception as e:
        log_print(f"⚠️ [逆向譜面] piptrack 異常: {e}")
        return []


def detect_chords(audio_path: str, seg_sec: float = 4.0) -> list:
    """chroma 模板匹配 → [(起秒, 和弦名)]（大三／小三＋貝斯根音加權，零額外依賴）。"""
    try:
        import librosa
        y, sr = _load_mono(audio_path)
        hop = 4096
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
        times = librosa.times_like(chroma, sr=sr, hop_length=hop)
        # 貝斯輪廓（C1–B2）：根音判定加權，對抗關係大小調誤判（如 Bm→D）
        bass = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, fmin=librosa.midi_to_hz(24),
                                          n_chroma=12, bins_per_octave=12)
        out, per = [], max(1, int(seg_sec / (times[1] - times[0]) if len(times) > 1 else 1))
        for i in range(0, chroma.shape[1], per):
            seg = chroma[:, i:i + per].mean(axis=1)
            if seg.max() <= 0:
                continue
            seg = seg / seg.max()
            bs = bass[:, i:i + per].mean(axis=1)
            bs = bs / (bs.max() + 1e-6)
            bass_root = int(np.argmax(bs))
            best, best_nm = -1, "N.C."
            for root in range(12):
                for kind, tpl in CHORD_TPL.items():
                    t = np.roll(tpl, root)
                    s = float(np.dot(seg, t) / (np.linalg.norm(seg) * np.linalg.norm(t) + 1e-6))
                    if root == bass_root:
                        s += 0.12  # 貝斯是根音的可信加成
                    if s > best:
                        best, best_nm = s, f"{NOTE_NAMES[root]}{'m' if kind == 'm' else ''}"
            out.append((round(float(times[i]), 1), best_nm))
        # 相鄰同名合併
        merged = []
        for t, n in out:
            if merged and merged[-1][1] == n:
                continue
            merged.append((t, n))
        return merged
    except Exception as e:
        log_print(f"⚠️ [逆向譜面] 和弦辨識異常: {e}")
        return []


def write_score_midi(title: str, melody: list, chords: list) -> str:
    """三軌出譜（旋律 ch0／和弦根音貝斯 ch1／簡配鼓 ch9）→ 進曲庫。回傳路徑或空。"""
    import mido
    safe = "".join(c for c in (title or "transcribed") if c not in '\\/:*?"<>|').strip() or "transcribed"
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    for name, prog, ch in [("Melody", 0, 0), ("BassRoots", 33, 1), ("Drums", None, 9)]:
        t = mido.MidiTrack()
        t.append(mido.MetaMessage("track_name", name=name, time=0))
        t.append(mido.MetaMessage("set_tempo", tempo=1000000, time=0))  # 480 ticks = 1 秒
        if prog is not None:
            t.append(mido.Message("program_change", program=prog, channel=ch, time=0))
        mid.tracks.append(t)
    evs = []
    for midi, s, d, v in (melody or []):
        t0 = int(s * 480)
        evs.append((t0, 0, midi, v, int(d * 480)))
    root_map = {n: i for i, n in enumerate(NOTE_NAMES)}
    bass_notes = []
    for i, (t, name) in enumerate(chords or []):
        m = re.match(r"([A-G]#?)(m?)", name)
        if not m:
            continue
        root = root_map[m.group(1)] + 12 * 2 + 12  # C3 附近
        nxt = chords[i + 1][0] if i + 1 < len(chords) else t + 4.0
        bass_notes.append((int(t * 480), 1, root, 85, int((nxt - t) * 480)))
    # 簡配鼓：每秒 kick＋2/4 拍 snare＋8 分 hat（按貝斯段長）
    span = max([t for t, _, _, _, _ in evs] + [t for t, _, _, _, _ in bass_notes] + [480 * 30], default=480 * 30)
    drum = []
    beat = 480
    b = 0
    while b < span:
        for k in range(4):
            drum.append((b + k * beat, 9, 36, 90, 60))
            if k in (1, 3):
                drum.append((b + k * beat, 9, 38, 85, 60))
            drum.append((b + k * beat, 9, 42, 60, 30))
            drum.append((b + k * beat + beat // 2, 9, 42, 55, 30))
        b += 4 * beat
    buckets = {0: [], 1: [], 9: []}  # ch -> [(abs_tick, msg)]
    for tick, ch, nn, vel, dur in evs + bass_notes + drum:
        buckets[ch].append((tick, mido.Message("note_on", note=nn, velocity=vel, channel=ch, time=0)))
        buckets[ch].append((tick + dur, mido.Message("note_off", note=nn, velocity=0, channel=ch, time=0)))
    for ch, items in buckets.items():
        tr = mid.tracks[0] if ch == 0 else (mid.tracks[1] if ch == 1 else mid.tracks[2])
        last = 0
        for tick, msg in sorted(items, key=lambda x: x[0]):
            msg.time = max(0, tick - last)
            last = tick
            tr.append(msg)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "midi_sheets", f"{safe}.mid")
    try:
        mid.save(out)
        try:
            from services.piano_engine import save_midi_catalog_entry
            save_midi_catalog_entry(safe, out)
        except Exception:
            pass
        return out
    except Exception as e:
        log_print(f"⚠️ [逆向譜面] 存檔異常: {e}")
        return ""


async def transcribe_song(url_or_id: str, title: str = "") -> dict:
    """一鍵逆向：下載→分離→旋律＋和弦→出譜。回 {ok, file, notes, chords}。"""
    from services.video_watch import normalize_video_url
    vid = normalize_video_url(url_or_id)
    if not vid:
        return {"ok": False, "error": "不是有效的 YouTube 網址/ID"}
    audio = await __import__("asyncio").to_thread(download_audio, vid)
    if not audio:
        return {"ok": False, "error": "下載失敗（地區限制／需登入／網路）"}
    stem = await __import__("asyncio").to_thread(separate_vocals, audio)
    melody = await __import__("asyncio").to_thread(transcribe_melody, stem)
    chords = await __import__("asyncio").to_thread(detect_chords, audio)
    name = (title or f"score_{vid}").strip()
    f = write_score_midi(name, melody, chords)
    if not f:
        return {"ok": False, "error": "出譜失敗"}
    log_print(f"🎧 [逆向譜面] 完成：{len(melody)} 音符＋{len(chords)} 和弦 → {os.path.basename(f)}")
    return {"ok": True, "file": f, "notes": len(melody),
            "chords": "→".join(n for _, n in chords[:16])}
