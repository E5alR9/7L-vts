# -*- coding: utf-8 -*-
"""
🎼 MIDI 編輯器（AI 能用的音樂編輯器）：讀譜 → 改音符 → 存檔 → 上台演奏。
PROVIDER: LOCAL（mido 純本地；見 docs/AI_SOURCES.md）。

設計：所有編輯皆為純函式（讀檔→改事件→寫新檔），AI 調工具鏈式調用：
  inspect → transpose/quantize/velocity/add_notes/set_program/merge → save → play_midi_band

檔案一律落在 midi_sheets/ 並自動進曲庫（save_midi_catalog_entry）。
"""
import os

import mido

from core.utils import log_print

SHEETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "midi_sheets")
os.makedirs(SHEETS_DIR, exist_ok=True)


def _resolve(path: str) -> str:
    """檔名或路徑 → 絕對路徑（不存在回空）。"""
    if not path:
        return ""
    if os.path.exists(path):
        return os.path.abspath(path)
    cand = os.path.join(SHEETS_DIR, os.path.basename(path))
    return cand if os.path.exists(cand) else ""


def _out_path(name: str) -> str:
    safe = "".join(c for c in (name or "edited") if c not in '\\/:*?"<>|').strip() or "edited"
    if not safe.lower().endswith((".mid", ".midi")):
        safe += ".mid"
    return os.path.join(SHEETS_DIR, safe)


def inspect_midi(path: str) -> dict:
    """純函式：讀譜面（軌數／音符數／時長／各軌 program＋音域）。"""
    p = _resolve(path)
    if not p:
        return {"ok": False, "error": "檔案不存在"}
    try:
        mid = mido.MidiFile(p, clip=True)
        tracks = []
        total_notes = 0
        for i, track in enumerate(mid.tracks):
            notes = sum(1 for m in track if m.type == "note_on" and m.velocity > 0)
            progs = sorted({m.program for m in track if m.type == "program_change"})
            pitches = [m.note for m in track if m.type in ("note_on", "note_off")]
            total_notes += notes
            tracks.append({
                "index": i, "name": getattr(track, "name", ""),
                "notes": notes, "programs": progs,
                "pitch_lo": min(pitches) if pitches else None,
                "pitch_hi": max(pitches) if pitches else None,
            })
        return {"ok": True, "file": p, "tracks": len(mid.tracks),
                "notes": total_notes, "duration": round(float(mid.length or 0), 1),
                "ticks_per_beat": mid.ticks_per_beat, "detail": tracks}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def _transform(path: str, out_name: str, fn) -> dict:
    """通用變換骨架：逐軌改事件 → 寫新檔 → 進曲庫。"""
    p = _resolve(path)
    if not p:
        return {"ok": False, "error": "檔案不存在"}
    try:
        mid = mido.MidiFile(p, clip=True)
        changed = 0
        for track in mid.tracks:
            for msg in track:
                if fn(msg):
                    changed += 1
        out = _out_path(out_name or (os.path.splitext(os.path.basename(p))[0] + "_edit"))
        mid.save(out)
        try:
            from services.piano_engine import save_midi_catalog_entry
            save_midi_catalog_entry(os.path.splitext(os.path.basename(out))[0], out)
        except Exception:
            pass
        return {"ok": True, "file": out, "changed": changed}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def transpose(path: str, semitones: int, out_name: str = "") -> dict:
    """整曲移調（±半音；自動夾 0-127）。"""
    st = int(semitones or 0)

    def _fn(msg):
        if msg.type in ("note_on", "note_off"):
            msg.note = max(0, min(127, msg.note + st))
            return True
        return False

    r = _transform(path, out_name or f"transpose_{st:+d}", _fn)
    if r.get("ok"):
        log_print(f"🎼 [MIDI 編輯] 移調 {st:+d} 半音 → {os.path.basename(r['file'])}")
    return r


def set_velocity(path: str, scale: float = 1.0, out_name: str = "") -> dict:
    """力度縮放（0.1-2.0；夾 1-127）。"""

    s = max(0.1, min(2.0, float(scale or 1.0)))

    def _fn(msg):
        if msg.type == "note_on" and msg.velocity > 0:
            msg.velocity = max(1, min(127, int(msg.velocity * s)))
            return True
        return False

    return _transform(path, out_name or f"vel_x{s}", _fn)


def quantize(path: str, grid: str = "16", out_name: str = "") -> dict:
    """時值量化到網格（grid: 4/8/16/32 音符；以首軌 tempo 計）。"""
    p = _resolve(path)
    if not p:
        return {"ok": False, "error": "檔案不存在"}
    div = {"4": 1.0, "8": 0.5, "16": 0.25, "32": 0.125}.get(str(grid), 0.25)
    try:
        mid = mido.MidiFile(p, clip=True)
        tpb = mid.ticks_per_beat or 480
        step = max(1, int(tpb * div))
        changed = 0
        for track in mid.tracks:
            abs_t = 0
            evs = []
            for msg in track:
                abs_t += msg.time
                evs.append((abs_t, msg))
            new_track = []
            last = 0
            for abs_t, msg in evs:
                if msg.type in ("note_on", "note_off"):
                    q = round(abs_t / step) * step
                    if q != abs_t:
                        changed += 1
                    msg.time = max(0, q - last)
                    last = q
                else:
                    msg.time = max(0, abs_t - last)
                    last = abs_t
                new_track.append(msg)
            track.clear()
            track.extend(new_track)
        out = _out_path(out_name or f"quant_{grid}")
        mid.save(out)
        try:
            from services.piano_engine import save_midi_catalog_entry
            save_midi_catalog_entry(os.path.splitext(os.path.basename(out))[0], out)
        except Exception:
            pass
        return {"ok": True, "file": out, "changed": changed}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def set_program(path: str, channel: int, program: int, out_name: str = "") -> dict:
    """改某通道音色（寫 program_change 到首事件；鼓 ch9 拒絕）。"""
    ch, prog = int(channel), int(program)
    if ch == 9:
        return {"ok": False, "error": "鼓組通道不配器"}
    if not (0 <= ch <= 15 and 0 <= prog <= 127):
        return {"ok": False, "error": "通道 0-15／音色 0-127"}
    p = _resolve(path)
    if not p:
        return {"ok": False, "error": "檔案不存在"}
    try:
        mid = mido.MidiFile(p, clip=True)
        done = False
        for track in mid.tracks:
            for msg in track:
                if msg.type == "program_change" and getattr(msg, "channel", 0) == ch:
                    msg.program = prog
                    done = True
        if not done and mid.tracks:
            mid.tracks[0].insert(0, mido.Message("program_change", program=prog, channel=ch, time=0))
        out = _out_path(out_name or f"prog_ch{ch}_{prog}")
        mid.save(out)
        try:
            from services.piano_engine import save_midi_catalog_entry
            save_midi_catalog_entry(os.path.splitext(os.path.basename(out))[0], out)
        except Exception:
            pass
        return {"ok": True, "file": out, "changed": 1}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def add_notes(path: str, notes: list, out_name: str = "") -> dict:
    """加音符：notes=[{pitch,start_beat,duration_beats,velocity,channel}] → 併入首軌。"""
    p = _resolve(path)
    if not p:
        return {"ok": False, "error": "檔案不存在"}
    try:
        mid = mido.MidiFile(p, clip=True)
        tpb = mid.ticks_per_beat or 480
        evs = []
        for n in (notes or []):
            try:
                pitch = max(0, min(127, int(n.get("pitch", 60))))
                sb = float(n.get("start_beat", 0.0))
                db = max(0.05, float(n.get("duration_beats", 0.5)))
                vel = max(1, min(127, int(n.get("velocity", 90))))
                ch = int(n.get("channel", 0))
                if ch == 9:
                    continue
                ch = max(0, min(15, ch))
                s = int(sb * tpb)
                evs.append((s, "note_on", pitch, vel, ch))
                evs.append((int((sb + db) * tpb), "note_off", pitch, 0, ch))
            except Exception:
                continue
        if not evs:
            return {"ok": False, "error": "無有效音符"}
        evs.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name="AI Edit", time=0))
        cur = 0
        for tick, typ, pitch, vel, ch in evs:
            track.append(mido.Message(typ, note=pitch, velocity=vel, channel=ch, time=max(0, tick - cur)))
            cur = tick
        mid.tracks.append(track)
        out = _out_path(out_name or "ai_edit")
        mid.save(out)
        try:
            from services.piano_engine import save_midi_catalog_entry
            save_midi_catalog_entry(os.path.splitext(os.path.basename(out))[0], out)
        except Exception:
            pass
        return {"ok": True, "file": out, "changed": len(evs)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def delete_pitch_range(path: str, lo: int = 0, hi: int = 127, out_name: str = "") -> dict:
    """刪某音高區間的音符（含對應 note_off；delta time 自動縫合）。"""
    p = _resolve(path)
    if not p:
        return {"ok": False, "error": "檔案不存在"}
    lo, hi = max(0, min(127, int(lo))), max(0, min(127, int(hi)))
    if lo > hi:
        lo, hi = hi, lo
    try:
        mid = mido.MidiFile(p, clip=True)
        changed = 0
        for track in mid.tracks:
            keep = []
            for msg in track:
                if msg.type in ("note_on", "note_off") and lo <= msg.note <= hi:
                    changed += 1
                    continue
                keep.append(msg)
            # 重建 delta time：被刪事件的時間併入下一事件
            track.clear()
            carry = 0
            for msg in keep:
                msg.time = msg.time + carry
                carry = 0
                track.append(msg)
        out = _out_path(out_name or f"del_{lo}_{hi}")
        mid.save(out)
        try:
            from services.piano_engine import save_midi_catalog_entry
            save_midi_catalog_entry(os.path.splitext(os.path.basename(out))[0], out)
        except Exception:
            pass
        return {"ok": True, "file": out, "changed": changed}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}
