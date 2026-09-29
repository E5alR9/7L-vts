# -*- coding: utf-8 -*-
"""
🎹 純 Python SoundFont 渲染器（零額外軟體：只讀 .sf2 數據檔＋numpy 重採樣混音）。

支援 SF2 v2.01 子集（夠播 GM 樂器＋鼓組）：
  解析：RIFF/sdta.smpl（16-bit  PCM）＋pdta（phdr/preset bag→gen→inst／iheaders bag→gen→shdr）
  發聲：keyRange 對位＋sampleID 取樣＋coarse/fine tune＋initialAttenuation 音量
       ＋sampleModes 循環（loop 無縫）＋pan 簡混＋one-shot 打擊樂
  不支援：modulator/LFO/濾波（文檔註明；GM 檔預設值下可聽性不受影響）

介面：
    bank = SoundFontBank("GeneralUser.sf2")  # 掃全檔 preset
    bank.program_name(bank_no, program)      # GM 名
    pcm = bank.render_note(bank_no, program, midi, velocity, duration, sr=44100)
    bank.render_track(events, sr)            # [(sec, midi, vel, dur)] → mono float32
"""
import os
import struct

import numpy as np

SF2_GEN_KEYRANGE = 43
SF2_GEN_INSTRUMENT = 41
SF2_GEN_SAMPLEID = 53
SF2_GEN_OVERRIDINGROOTKEY = 58
SF2_GEN_COARSETUNE = 51
SF2_GEN_FINETUNE = 52
SF2_GEN_ATTENUATION = 48
SF2_GEN_PAN = 17
SF2_GEN_SAMPLEMODES = 54


def _read_chunk(f):
    head = f.read(8)
    if len(head) < 8:
        return None, b""
    cid, size = struct.unpack("<4sI", head)
    data = f.read(size + (size & 1))
    return cid.decode("ascii", "replace"), data[:size]


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _i16(b, o):
    return struct.unpack_from("<h", b, o)[0]


def _s8(b, o):
    v = b[o]
    return v - 256 if v > 127 else v


class SoundFontBank:
    def __init__(self, path: str):
        self.path = path
        self.samples = b""
        self.shdrs = []     # (name, start, end, loop_start, loop_end, rate, orig_key, correction, link, type)
        self.insts = []     # (name, bag_idx)
        self.ibags = []     # [(gen_start, gen_end)]
        self.igens = []     # [(oper, amount_u16, amount_i16)]
        self.presets = []   # (name, program, bank, bag_idx)
        self.pbags = []
        self.pgens = []
        self._parse()

    # ── 解析 ──
    def _parse(self):
        with open(self.path, "rb") as f:
            cid, data = _read_chunk(f)
            assert cid == "RIFF" and data[:4] == b"sfbk", "不是 SF2 檔"
            import io
            sub = io.BytesIO(data[4:])
            while True:
                r = _read_chunk(sub)
                if r[0] is None:
                    break
                lid, ldata = r
                if lid != "LIST":
                    continue
                ltype = ldata[:4].decode("ascii", "replace")
                inner = io.BytesIO(ldata[4:])
                while True:
                    rr = _read_chunk(inner)
                    if rr[0] is None:
                        break
                    sid, sdata = rr
                    if ltype == "sdta" and sid == "smpl":
                        self.samples = sdata
                    elif ltype == "pdta":
                        self._pdta(sid, sdata)

    def _pdta(self, sid, d):
        if sid == "phdr":
            for i in range(0, len(d) - 38, 38):
                name = d[i:i + 20].split(b"\x00")[0].decode("ascii", "replace")
                prog, bank, bag = _u16(d, i + 20), _u16(d, i + 22), _u16(d, i + 24)
                self.presets.append((name, prog, bank, bag))
        elif sid == "pbag":
            for i in range(0, len(d), 4):
                self.pbags.append((_u16(d, i), _u16(d, i + 2)))
        elif sid == "pgen":
            for i in range(0, len(d) - 4, 4):
                self.pgens.append((d[i], _u16(d, i + 2), _i16(d, i + 2)))
        elif sid == "inst":
            for i in range(0, len(d) - 22, 22):
                name = d[i:i + 20].split(b"\x00")[0].decode("ascii", "replace")
                self.insts.append((name, _u16(d, i + 20)))
        elif sid == "ibag":
            for i in range(0, len(d), 4):
                self.ibags.append((_u16(d, i), _u16(d, i + 2)))
        elif sid == "igen":
            for i in range(0, len(d) - 4, 4):
                self.igens.append((d[i], _u16(d, i + 2), _i16(d, i + 2)))
        elif sid == "shdr":
            for i in range(0, len(d) - 46, 46):
                name = d[i:i + 20].split(b"\x00")[0].decode("ascii", "replace")
                start, end = struct.unpack_from("<II", d, i + 20)
                loop_s, loop_e = struct.unpack_from("<II", d, i + 28)
                rate = struct.unpack_from("<I", d, i + 36)[0]
                orig = d[i + 40]
                corr = _s8(d, i + 41)
                link = _u16(d, i + 42)
                stype = _u16(d, i + 44)
                self.shdrs.append((name, start, end, loop_s, loop_e, rate, orig, corr, link, stype))
        # imod/pmod 忽略（不支援 modulator）

    # ── 查表 ──
    def _preset_zones(self, bank_no, program):
        for idx, (name, prog, bank, bag) in enumerate(self.presets):
            if prog == program and bank == bank_no:
                nxt = self.presets[idx + 1][3] if idx + 1 < len(self.presets) else len(self.pbags) - 1
                for b in range(bag, nxt):
                    gs = self.pbags[b][0]
                    ge = self.pbags[b + 1][0] if b + 1 < len(self.pbags) else len(self.pgens)
                    gens = {op: (u, s) for op, u, s in self.pgens[gs:ge]}
                    if SF2_GEN_INSTRUMENT not in gens:
                        continue
                    inst_id = gens[SF2_GEN_INSTRUMENT][0]
                    iname, ibag = self.insts[inst_id]
                    inxt = self.insts[inst_id + 1][1] if inst_id + 1 < len(self.insts) else len(self.ibags) - 1
                    for ib in range(ibag, inxt):
                        gs2 = self.ibags[ib][0]
                        ge2 = self.ibags[ib + 1][0] if ib + 1 < len(self.ibags) else len(self.igens)
                        ig = {op: (u, s) for op, u, s in self.igens[gs2:ge2]}
                        if SF2_GEN_SAMPLEID not in ig:
                            continue
                        yield gens, ig
                return
        return
        yield  # pragma: no cover

    def find_sample(self, bank_no, program, midi):
        """回傳 (shdr, coarse, fine, atten_cb, pan, loop_mode)，找不到回 None。"""
        for pgens, igens in self._preset_zones(bank_no, program):
            kr = igens.get(SF2_GEN_KEYRANGE, pgens.get(SF2_GEN_KEYRANGE))
            if kr:
                lo, hi = kr[0] & 0xFF, (kr[0] >> 8) & 0xFF
                if not (lo <= midi <= hi):
                    continue
            sid = igens[SF2_GEN_SAMPLEID][0]
            sh = self.shdrs[sid]
            coarse = igens.get(SF2_GEN_COARSETUNE, pgens.get(SF2_GEN_COARSETUNE, (0, 0)))[1] \
                if isinstance(igens.get(SF2_GEN_COARSETUNE, pgens.get(SF2_GEN_COARSETUNE, (0, 0))), tuple) else 0
            fine = igens.get(SF2_GEN_FINETUNE, pgens.get(SF2_GEN_FINETUNE, (0, 0)))
            fine = fine[1] if isinstance(fine, tuple) else 0
            atten = igens.get(SF2_GEN_ATTENUATION, pgens.get(SF2_GEN_ATTENUATION, (0, 0)))
            atten = atten[1] / 10.0 if isinstance(atten, tuple) else 0.0
            pan = igens.get(SF2_GEN_PAN, pgens.get(SF2_GEN_PAN, (0, 0)))
            pan = pan[1] / 500.0 if isinstance(pan, tuple) else 0.0
            loopm = igens.get(SF2_GEN_SAMPLEMODES, pgens.get(SF2_GEN_SAMPLEMODES, (0, 1)))
            loopm = loopm[0] & 3 if isinstance(loopm, tuple) else 1
            root = igens.get(SF2_GEN_OVERRIDINGROOTKEY, pgens.get(SF2_GEN_OVERRIDINGROOTKEY))
            if isinstance(root, tuple) and 0 <= root[0] <= 127:
                sh = (sh[0], sh[1], sh[2], sh[3], sh[4], sh[5], root[0], sh[7], sh[8], sh[9])
            return sh, coarse, fine, atten, pan, loopm
        return None

    # ── 渲染 ──
    def _sample_pcm(self, sh):
        _, start, end, *_ = sh
        raw = np.frombuffer(self.samples, dtype="<i2", count=max(0, end - start),
                            offset=start * 2).astype(np.float32) / 32768.0
        return raw

    def render_note(self, bank_no, program, midi, velocity=90, duration=2.0, sr=44100):
        """單音渲染 → mono float32（無聲回 zeros，絕不拋錯）。"""
        n = int(sr * max(0.05, duration))
        try:
            found = self.find_sample(bank_no, program, midi)
            if not found:
                return np.zeros(n, dtype=np.float32)
            sh, coarse, fine, atten_db, pan, loopm = found
            name, start, end, loop_s, loop_e, rate, orig, corr, link, stype = sh
            raw = self._sample_pcm(sh)
            if len(raw) < 8:
                return np.zeros(n, dtype=np.float32)
            semis = (midi - orig) + coarse + (corr + fine) / 100.0
            ratio = (2.0 ** (semis / 12.0)) * (rate / sr)
            need = int(n * ratio) + 8
            if loopm in (1, 3) and loop_e > loop_s + 8 and need > len(raw):
                # 循環延展：head＋loop 段重複
                head = raw[:loop_s]
                loop = raw[loop_s:loop_e]
                reps = (need - len(head)) // len(loop) + 2
                raw = np.concatenate([head] + [loop] * reps)[:need]
            elif need > len(raw):
                raw = np.pad(raw, (0, need - len(raw)))
            else:
                raw = raw[:need]
            idx = np.arange(n) * ratio
            i0 = np.floor(idx).astype(int)
            frac = idx - i0
            i1 = np.minimum(i0 + 1, len(raw) - 1)
            out = raw[i0] * (1 - frac) + raw[i1] * frac
            # 簡包絡：10ms attack＋尾部 80ms release（打擊樂 one-shot 不衰）
            a = min(len(out), int(sr * 0.01))
            out[:a] *= np.linspace(0, 1, a)
            if not (bank_no == 128 and loopm == 0):
                r = min(len(out), int(sr * 0.08))
                out[-r:] *= np.linspace(1, 0, r)
            gain = (10.0 ** (-atten_db / 20.0)) * (velocity / 100.0)
            return (out * gain).astype(np.float32)
        except Exception:
            return np.zeros(n, dtype=np.float32)

    def render_track(self, events, bank_no=0, program=0, sr=44100):
        """[(sec, midi, vel, dur)] → mono mix。"""
        if not events:
            return np.zeros(0, dtype=np.float32)
        total = max(s + d for s, _, _, d in events) + 0.5
        mix = np.zeros(int(sr * total) + 8, dtype=np.float64)
        for s, midi, vel, dur in events:
            w = self.render_note(bank_no, program, midi, vel, dur, sr)
            i = int(s * sr)
            end = min(len(mix), i + len(w))
            if i < len(mix):
                mix[i:end] += w[:end - i]
        peak = np.max(np.abs(mix))
        if peak > 0:
            mix /= peak
        return mix.astype(np.float32)

    def program_name(self, bank_no, program):
        for name, prog, bank, _ in self.presets:
            if prog == program and bank == bank_no:
                return name
        return f"#{program}"
