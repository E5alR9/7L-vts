# -*- coding: utf-8 -*-
"""
🎸 扒帶包（Stem Pack）：一鍵產出學歌全家桶。
PROVIDER: LOCAL（demucs htdemucs_6s＋librosa；見 docs/AI_SOURCES.md）。

產物（data/stem_pack/<vid>/）：
  vocals.wav / drums.wav / bass.wav / guitar.wav / piano.wav / other.wav
  karaoke.wav      去人聲伴奏（跟唱／跟彈用）
  slowed_075.wav   降速 75% 不變調（扒 solo 用）
  chords.txt       和弦進行（段落時間＋和弦名）
  melody.mid       主旋律 MIDI（既有逆向管線）

依賴：demucs（已裝）。模型首次自動下載。
"""
import os
import subprocess
import sys
import time

import numpy as np

from core.utils import log_print

PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stem_pack")
os.makedirs(PACK_DIR, exist_ok=True)

STEMS_6 = ["vocals", "drums", "bass", "guitar", "piano", "other"]


def pack_path(video_id: str) -> str:
    p = os.path.join(PACK_DIR, video_id)
    os.makedirs(p, exist_ok=True)
    return p


def separate_six(audio_path: str, video_id: str) -> dict:
    """6 軌分離 → {stem: wav 路徑}（失敗回空 dict）。"""
    out = pack_path(video_id)
    if all(os.path.exists(os.path.join(out, f"{s}.wav")) for s in STEMS_6):
        log_print("🎸 [扒帶包] 分軌已存在，跳過分離")
        return {s: os.path.join(out, f"{s}.wav") for s in STEMS_6}
    cmd = [sys.executable, "-m", "demucs", "-n", "htdemucs_6s", "-o", out, audio_path]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=2400)
        base = os.path.splitext(os.path.basename(audio_path))[0]
        got = {}
        for s in STEMS_6:
            cand = os.path.join(out, "htdemucs_6s", base, f"{s}.wav")
            if os.path.exists(cand):
                import shutil
                dst = os.path.join(out, f"{s}.wav")
                shutil.move(cand, dst)
                got[s] = dst
        if len(got) < 4:
            log_print(f"⚠️ [扒帶包] 只分出 {len(got)} 軌")
        return got
    except Exception as e:
        log_print(f"⚠️ [扒帶包] 分離異常: {e}")
        return {}


def mix_wavs(paths: list, out_path: str, weights: dict = None) -> str:
    """多軌混音（等長對齊＋防爆正規化）。"""
    import soundfile as sf
    import numpy as np
    waves, sr0 = [], None
    for p in paths:
        w, sr = sf.read(p, dtype="float32", always_2d=True)
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            continue
        name = os.path.splitext(os.path.basename(p))[0]
        g = (weights or {}).get(name, 1.0)
        waves.append(w * g)
    if not waves:
        return ""
    n = max(len(w) for w in waves)
    mix = np.zeros((n, waves[0].shape[1]))
    for w in waves:
        mix[:len(w)] += w
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix / peak * 0.89
    sf.write(out_path, mix, sr0)
    return out_path


def make_karaoke(stems: dict, video_id: str) -> str:
    """去人聲伴奏。"""
    picks = [stems[s] for s in ("drums", "bass", "guitar", "piano", "other") if s in stems]
    if not picks:
        return ""
    return mix_wavs(picks, os.path.join(pack_path(video_id), "karaoke.wav"))


def make_slowed(src_wav: str, video_id: str, rate: float = 0.75) -> str:
    """降速不變調（librosa phase-vocoder）。"""
    import librosa
    import soundfile as sf
    try:
        y, sr = sf.read(src_wav, dtype="float32", always_2d=True)
        out = np.stack([librosa.effects.time_stretch(y[:, c], rate=rate) for c in range(y.shape[1])], axis=1)
        p = os.path.join(pack_path(video_id), f"slowed_{int(rate*100):03d}.wav")
        sf.write(p, out, sr)
        return p
    except Exception as e:
        log_print(f"⚠️ [扒帶包] 降速異常: {e}")
        return ""


def write_chords_txt(video_id: str, chords: list) -> str:
    """和弦進行存檔（去重＋分段）。"""
    p = os.path.join(pack_path(video_id), "chords.txt")
    try:
        merged = []
        for t, n in (chords or []):
            if not merged or merged[-1][1] != n:
                merged.append((t, n))
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# 和弦進行（{len(merged)} 段，機器辨識僅供扒帶參考）\n")
            for t, n in merged:
                f.write(f"{int(t//60):02d}:{int(t%60):02d}  {n}\n")
        return p
    except Exception:
        return ""


async def build_pack(url_or_id: str) -> dict:
    """一鍵扒帶包：下載→分離→卡拉→降速→和弦→旋律MIDI。"""
    import asyncio
    from services.video_watch import normalize_video_url
    from services import audio_to_score as ats
    vid = normalize_video_url(url_or_id)
    if not vid:
        return {"ok": False, "error": "不是有效的 YouTube 網址/ID"}
    audio = await asyncio.to_thread(ats.download_audio, vid)
    if not audio:
        return {"ok": False, "error": "下載失敗"}
    stems = await asyncio.to_thread(separate_six, audio, vid)
    if not stems:
        return {"ok": False, "error": "分離失敗"}
    karaoke = await asyncio.to_thread(make_karaoke, stems, vid)
    slowed = ""
    if "vocals" in stems:
        slowed = await asyncio.to_thread(make_slowed, stems["vocals"], vid, 0.75)
    chords = await asyncio.to_thread(ats.detect_chords, audio, 4.0)
    chord_txt = write_chords_txt(vid, chords)
    melody = await asyncio.to_thread(ats.transcribe_melody, stems.get("vocals", audio))
    midi = ats.write_score_midi(f"{vid}_melody", melody, [])
    log_print(f"🎸 [扒帶包] 完成：{len(stems)} 軌＋卡拉＋降速＋{len(chords)} 和弦＋{len(melody)} 旋律音")
    return {"ok": True, "dir": pack_path(vid), "stems": sorted(stems),
            "karaoke": karaoke, "slowed": slowed, "chords_txt": chord_txt,
            "midi": midi, "melody_notes": len(melody)}
