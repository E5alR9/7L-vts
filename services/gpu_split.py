# -*- coding: utf-8 -*-
"""翻唱人聲分離的兩台分工：桌機和筆電（tools/gpu_worker.py）一起分同一首，或兩首各分各的。

一首歌切兩段：桌機分前段、筆電分後段，同時跑再接起來。切點照兩台實測速度（data/gpu_rates.json，每做一段更新）
算到兩邊差不多同時做完；有一台正在忙，就把它什麼時候空也算進去，算出來切了反而慢就整首給先空的那台——
所以排隊時常常變成一台一首（_plan）。筆電沒設、沒開、出錯，就是桌機整首自己分，跟以前一模一樣。
RVC 不切（一首才幾秒，而且音高要整首一起判決），桌機在分別首時才丟筆電（convert_vocal）。

接縫（2026-10-28 實測，潮汐，整首 vs 切段逐 0.5 秒比對）：
- Roformer 一窗 8 秒、一步 2 秒（模型 yaml：chunk 352800、num_overlap 4）。段頭段尾一窗之內跟整首分的不一樣，
  離邊超過一窗就一模一樣 → 接縫要離兩段的邊都超過一窗，後段要從整數步切下去，窗才跟整首對齊。
- audio-separator 會把輸入、輸出各自壓到峰值 0.9：兩段峰值不同就各壓各的，整段都差 → 先照整首的峰值壓好再切
  （輸入就不會再被壓），輸出在重疊區比對音量，把後段對齊前段，最後整首照原本的規矩壓一次。
（2026-10-28 老爸：照「切段合力＋排隊各做一首」做，先驗證接縫聽不出來再上線。）
"""
import json
import os
import threading
import time

import numpy as np
import soundfile as sf

from core.paths import ROOT_DIR
from core.utils import log_print
from services import remote_gpu

SR = 44100
CHUNK = 352800            # Roformer 一窗（樣本）
STEP = 88200              # 一步＝一窗 / num_overlap
VALID = 3 * SR            # 接縫兩邊各留 3 秒兩段都準的重疊，拿來對音量
FADE = SR                 # 交叉淡化 1 秒
PEAK = 0.9                # audio-separator 的 normalization_threshold
MIN_PART_SEC = 25.0       # 分到不到這麼長就不切（多分的一窗＋傳檔不划算）
_EXTRA_SEC = (CHUNK + VALID) / SR

_RATES_FILE = os.path.join(ROOT_DIR, "data", "gpu_rates.json")


class _Machine:
    def __init__(self, name: str, rate: float, overhead: float):
        self.name = name
        self.rate = rate            # 每秒實際時間分得完幾秒音訊（筆電含傳檔）
        self.overhead = overhead    # 每段固定開銷（秒）
        self.lock = threading.Lock()
        self.reserved = {}          # 排在這台的段 → 預計做完的時間

    def free_at(self, now: float) -> float:
        return max([now] + list(self.reserved.values()))


DESK = _Machine("桌機", 1.8, 2.0)
LAP = _Machine("筆電", 0.75, 10.0)
_PLAN_LOCK = threading.Lock()


def _load_rates():
    try:
        with open(_RATES_FILE, encoding="utf-8") as f:
            r = json.load(f)
        DESK.rate = float(r.get("desk", DESK.rate))
        LAP.rate = float(r.get("lap", LAP.rate))
    except Exception:
        pass


def _save_rates():
    try:
        os.makedirs(os.path.dirname(_RATES_FILE), exist_ok=True)
        with open(_RATES_FILE, "w", encoding="utf-8") as f:
            json.dump({"desk": round(DESK.rate, 3), "lap": round(LAP.rate, 3)}, f)
    except Exception:
        pass


_load_rates()


def _learn(m: _Machine, audio_sec: float, wall: float):
    if audio_sec < 10 or wall <= m.overhead:
        return
    m.rate = 0.7 * m.rate + 0.3 * (audio_sec / (wall - m.overhead))
    _save_rates()


def _plan(n: int, sr: int, lap_ok: bool):
    """回 (段落清單 [(機器, 開始樣本, 結束樣本, 接縫樣本)], 預計做完時間)。接縫樣本只有切兩段時有意義。"""
    now = time.time()
    dur = n / sr
    td = DESK.free_at(now)
    whole_d = ([(DESK, 0, n, n)], td + DESK.overhead + dur / DESK.rate)
    if not lap_ok:
        return whole_d
    tl = LAP.free_at(now)
    options = [whole_d, ([(LAP, 0, n, n)], tl + LAP.overhead + dur / LAP.rate)]
    if sr == SR:
        rd, rl, e = DESK.rate, LAP.rate, _EXTRA_SEC
        # 桌機分前 x 秒＋多一窗，筆電分後面＋多一窗，兩邊同時做完
        x = (tl + LAP.overhead - td - DESK.overhead + (dur + e) / rl - e / rd) / (1 / rd + 1 / rl)
        if MIN_PART_SEC <= x <= dur - MIN_PART_SEC:
            cut = int(x * sr)
            d_end = min(n, cut + VALID + CHUNK)
            l_start = max(0, (cut - VALID - CHUNK) // STEP * STEP)
            options.append(([(DESK, 0, d_end, cut), (LAP, l_start, n, cut)],
                            td + DESK.overhead + (x + e) / rd))
    return min(options, key=lambda o: o[1])


def _run(m: _Machine, src: str, voc: str, ins: str, song: str, progress_cb=None) -> bool:
    with m.lock:
        t0 = time.time()
        if m is DESK:
            from services.roformer_sep import separate_roformer
            ok = separate_roformer(src, voc, ins, song_name=song, progress_cb=progress_cb)
        else:
            ok = remote_gpu.separate(src, voc, ins, song)
        if ok:
            _learn(m, sf.info(src).duration, time.time() - t0)
        return ok


def _merge(parts, cut: int, n: int, out: str, stem: str):
    """兩段某個分軌接成一首：重疊區對齊音量 → 接縫 1 秒交叉淡化 → 整首超過 0.9 就壓。"""
    (d_start, _d_end, d_path), (l_start, _l_end, l_path) = parts
    a, _ = sf.read(d_path, always_2d=True, dtype="float64")
    b, _ = sf.read(l_path, always_2d=True, dtype="float64")
    lo, hi = cut - VALID, cut + VALID
    ra, rb = a[lo:hi], b[lo - l_start:hi - l_start]
    g = float(np.sum(ra * rb) / np.sum(rb * rb)) if np.sum(rb * rb) > 1e-6 else 1.0
    if not 0.7 < g < 1.4:
        log_print(f"⚠️ [兩台合力分離] {stem} 重疊區音量比 {g:.3f} 不合理，不調")
        g = 1.0
    b *= g
    f0, f1 = cut - FADE // 2, cut + FADE // 2
    w = np.linspace(0.0, 1.0, f1 - f0)[:, None]
    y = np.concatenate([a[:f0],
                        a[f0:f1] * (1 - w) + b[f0 - l_start:f1 - l_start] * w,
                        b[f1 - l_start:]])[:n]
    if len(y) < n:
        y = np.concatenate([y, np.zeros((n - len(y), y.shape[1]))])
    peak = float(np.max(np.abs(y)))
    if peak > PEAK:
        y *= PEAK / peak
    tmp = out + ".part.wav"
    sf.write(tmp, y, SR, subtype="PCM_16")   # 跟整首分出來的一樣；pygame 放不了浮點 wav
    os.replace(tmp, out)
    return g


def separate(input_wav: str, vocals_out: str, inst_out: str, song_name: str = "", progress_cb=None) -> bool:
    """分一首歌的人聲／伴奏到 vocals_out／inst_out。整首給一台、或兩台各分一段接起來；失敗回 False。"""
    info = sf.info(input_wav)
    n, sr = info.frames, info.samplerate
    lap_ok = remote_gpu.available()
    with _PLAN_LOCK:
        plan, eta = _plan(n, sr, lap_ok)
        token = object()
        now = time.time()
        for m, s, e, _c in plan:
            m.reserved[token] = m.free_at(now) + m.overhead + (e - s) / sr / m.rate
    try:
        if len(plan) == 1:
            m = plan[0][0]
            if m is LAP:
                log_print(f"💻 [兩台分工] 《{song_name}》整首給筆電（桌機在忙）")
                if _run(LAP, input_wav, vocals_out, inst_out, song_name):
                    return True
                log_print(f"🔄 [兩台分工] 筆電沒分成《{song_name}》，桌機自己來")
                return _run(DESK, input_wav, vocals_out, inst_out, song_name, progress_cb)
            return _whole(input_wav, vocals_out, inst_out, song_name, progress_cb)
        return _separate_split(input_wav, vocals_out, inst_out, song_name, progress_cb, plan, n, eta)
    finally:
        for m, *_ in plan:
            m.reserved.pop(token, None)


def _whole(input_wav, vocals_out, inst_out, song_name, progress_cb) -> bool:
    """桌機整首分；桌機分失敗（2026-10-28 實測：桌機顯卡掉了是 CUDA unknown error）就整首丟筆電。"""
    if _run(DESK, input_wav, vocals_out, inst_out, song_name, progress_cb):
        return True
    if remote_gpu.available():
        log_print(f"🔄 [兩台分工] 桌機沒分成《{song_name}》，整首改給筆電")
        return _run(LAP, input_wav, vocals_out, inst_out, song_name)
    return False


def _separate_split(input_wav, vocals_out, inst_out, song_name, progress_cb, plan, n, eta) -> bool:
    cut = plan[0][3]
    log_print(f"💻 [兩台合力分離] 《{song_name}》桌機分前 {cut / SR:.0f} 秒、筆電分後 {(n - cut) / SR:.0f} 秒，"
              f"預計 {eta - time.time():.0f} 秒")
    t0 = time.time()
    a, _ = sf.read(input_wav, always_2d=True, dtype="float32")
    peak = float(np.max(np.abs(a)))
    if peak > PEAK:
        a *= PEAK / peak     # 照整首壓好，兩段進 audio-separator 就不會各自再壓
    base = os.path.join(os.path.dirname(os.path.abspath(vocals_out)), f"split_{int(t0 * 1000)}")
    files, results, threads = [], {}, []
    try:
        for i, (m, s, e, _c) in enumerate(plan):
            src, voc, ins = (f"{base}_{i}{suf}" for suf in (".wav", "_vocals.wav", "_inst.wav"))
            files += [src, voc, ins]
            sf.write(src, a[s:e], SR, subtype="FLOAT")

            def work(i=i, m=m, src=src, voc=voc, ins=ins):
                ok = _run(m, src, voc, ins, song_name, progress_cb if m is DESK else None)
                if not ok:
                    other = DESK if m is LAP else LAP
                    if other is DESK or remote_gpu.available():
                        log_print(f"🔄 [兩台合力分離] {m.name}那段沒分成，{other.name}補做")
                        ok = _run(other, src, voc, ins, song_name)
                results[i] = ok
            threads.append(threading.Thread(target=work, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if not all(results.get(i) for i in range(len(plan))):
            log_print(f"🔄 [兩台合力分離] 《{song_name}》有一段兩台都沒分成，整首重分")
            return _whole(input_wav, vocals_out, inst_out, song_name, progress_cb)
        g = []
        for stem, out, k in (("人聲", vocals_out, 1), ("伴奏", inst_out, 2)):
            parts = [(s, e, files[3 * i + k]) for i, (_m, s, e, _c) in enumerate(plan)]
            g.append(_merge(parts, cut, n, out, stem))
        log_print(f"✨ [兩台合力分離] 《{song_name}》分好接好，{time.time() - t0:.0f} 秒"
                  f"（接縫音量比 人聲 {g[0]:.3f}／伴奏 {g[1]:.3f}）")
        return True
    except Exception as e:
        log_print(f"⚠️ [兩台合力分離] 《{song_name}》異常，整首重分: {e}")
        return _whole(input_wav, vocals_out, inst_out, song_name, progress_cb)
    finally:
        rf = os.path.join(os.path.dirname(base), "roformer_out")
        stale = [os.path.join(rf, f) for f in os.listdir(rf)] if os.path.isdir(rf) else []
        for p in files + [p for p in stale if os.path.basename(p).startswith(os.path.basename(base))]:
            try:
                os.remove(p)
            except OSError:
                pass


def convert_vocal(local_fn, input_wav: str, output_wav: str, key: float = 0.0,
                  auto_pitch: bool = True, index_rate: float = 0.88) -> bool:
    """RVC 變聲：平常桌機做（幾秒的事）；桌機正在分別首、筆電又空著，才丟筆電。local_fn() 是桌機自己做。"""
    if DESK.lock.locked() and remote_gpu.available() and LAP.lock.acquire(blocking=False):
        try:
            if remote_gpu.convert_vocal(input_wav, output_wav, key=key, auto_pitch=auto_pitch,
                                        index_rate=index_rate):
                return True
        finally:
            LAP.lock.release()
    with DESK.lock:
        return local_fn()
