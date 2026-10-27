# -*- coding: utf-8 -*-
"""Tier-1 人聲分離：Mel-Roformer（audio-separator 0.47，CUDA 常駐）。

實測（RTX 3080Ti 12GB，2026-10-10，scratch/try_roformer.py）：
- 模型載入 5.8s（639MB ckpt，只載一次常駐 VRAM，後續歌曲省掉）
- 162s 歌曲分離 110.7s（約 0.68x 即時）；與直播棧（SoVITS 等，常駐 5.9GB）共存無 OOM
- 輸出命名：<base>_(Vocals)_model_bs_roformer_ep_317_sdr_12.wav / _(Instrumental)_...
- 能量驗證：Vocals 檔靜音窗 24/163 vs Instrumental 8/163（scratch/check_stems.py），命名可信

進度可見性：audio-separator 內部用 tqdm 走 stderr，這裡 redirect_stderr 接住解析；
萬一沒解析到，monitor 每 20s 照樣打 elapsed 心跳——保證看起來永遠在跑，不空轉。
"""
import contextlib
import io
import os
import re
import shutil
import threading
import time
from core.utils import log_print, log_swallowed
from core.paths import ROOT_DIR

MODEL_FILENAME = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
_REPO_ROOT = ROOT_DIR
MODEL_DIR = os.path.join(_REPO_ROOT, "models", "roformer")

_PCT_RE = re.compile(r"(\d{1,3})\s*%")
_FRAC_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _parse_percent(text: str):
    """從 tqdm 殘段抓最後一個百分比；沒有 % 就用 a/b 估算；都沒有回 None。"""
    if not text:
        return None
    m = _PCT_RE.findall(text)
    if m:
        try:
            return max(0, min(100, int(m[-1])))
        except ValueError:
            pass
    m2 = _FRAC_RE.findall(text)
    if m2:
        try:
            a, b = int(m2[-1][0]), int(m2[-1][1])
            if b > 0:
                return max(0, min(100, round(100.0 * a / b)))
        except ValueError:
            pass
    return None


def _pick_stems(outs, out_dir):
    """從 separate() 回傳名單挑 (vocals, instrumental)；outs 可能是裸檔名，out_dir 補全。"""
    voc, ins = None, None
    for o in outs or []:
        p = o if os.path.isabs(o) and os.path.exists(o) else os.path.join(out_dir, os.path.basename(o or ""))
        if not os.path.exists(p):
            continue
        low = os.path.basename(p).lower()
        if "(vocals)" in low or "vocals" in low and "no_vocals" not in low and "no-vocals" not in low:
            voc = voc or p
        elif "(instrumental)" in low or "no_vocals" in low or "no-vocals" in low or "(other)" in low:
            ins = ins or p
    return voc, ins


class _TqdmCapture(io.StringIO):
    """線程安全的 stderr 承接桶（給 tqdm 寫進度條用）。"""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def write(self, s):
        with self._lock:
            return super().write(s)

    def snapshot(self):
        with self._lock:
            return self.getvalue()

    def isatty(self):
        return False


_SEPS = {}
_SEPS_LOCK = threading.Lock()


def _get_separator(work_dir: str):
    """模型單例（按 work_dir 快取；實務上永遠是同一個 cover_cache/roformer_out）。"""
    with _SEPS_LOCK:
        sep = _SEPS.get(work_dir)
        if sep is None:
            from audio_separator.separator import Separator
            sep = Separator(
                output_dir=work_dir,
                output_format="WAV",
                model_file_dir=MODEL_DIR,
                log_level=30,
            )
            sep.load_model(MODEL_FILENAME)
            _SEPS[work_dir] = sep
        return sep


def _monitor(buf: _TqdmCapture, stop: threading.Event, song_name: str,
             progress_cb, t0: float, beat: float = 20.0):
    last_pct = -1
    last_beat = 0.0
    while not stop.wait(2.0):
        el = time.time() - t0
        pct = _parse_percent(buf.snapshot())
        if pct is not None and pct >= last_pct + 3:
            last_pct = pct
            if progress_cb:
                try:
                    progress_cb(pct)
                except Exception:
                    log_swallowed()
        if el - last_beat >= beat:
            last_beat = el
            tag = f" {pct}%" if pct is not None else ""
            log_print(f"🎤 [Roformer 分離中] 《{song_name}》{tag}（已跑 {el:.0f}s，未空轉）")
    pct = _parse_percent(buf.snapshot())
    if pct is not None and progress_cb and pct > last_pct:
        try:
            progress_cb(pct)
        except Exception:
            log_swallowed()


def preload_roformer(work_dir: str) -> bool:
    """開機預載（2026-10-11）：639MB 模型上卡 burst 會把同時的 SoVITS 推理拖到 50~80 秒。
    開機排在 SoVITS 預熱後面先付掉，首歌分離只剩純計算、不再撞 TTS。失敗回 False（首歌再載，不擋開機）。"""
    try:
        os.makedirs(work_dir, exist_ok=True)
        t0 = time.time()
        _get_separator(work_dir)
        log_print(f"✅ [Roformer 預載完成] 常駐 VRAM（{time.time() - t0:.1f}s），首歌不撞 TTS。")
        return True
    except Exception as e:
        log_print(f"⚠️ [Roformer 預載失敗（首歌再載）]: {e}")
        return False


def separate_roformer(input_wav: str, vocals_out: str, inst_out: str,                      song_name: str = "", progress_cb=None) -> bool:
    """Roformer 分離一首歌。成功回 True（雙 stems 已拷到目標）；任何異常回 False（調用方降級）。
    progress_cb(pct 0~100)：tqdm 解析＋節流（≥3% 才回調），調用方拿去刷 dashboard。"""
    if not input_wav or not os.path.exists(input_wav):
        return False
    t0 = time.time()
    label = song_name or os.path.basename(input_wav)
    work_dir = os.path.join(os.path.dirname(os.path.abspath(vocals_out)), "roformer_out")
    os.makedirs(work_dir, exist_ok=True)
    try:
        sep = _get_separator(work_dir)
    except Exception as e:
        log_print(f"⚠️ [Roformer 載入失敗，降級]: {e}")
        return False
    buf = _TqdmCapture()
    stop = threading.Event()
    mon = threading.Thread(target=_monitor, args=(buf, stop, label, progress_cb, t0), daemon=True)
    mon.start()
    try:
        with contextlib.redirect_stderr(buf):
            outs = sep.separate(input_wav)
    except Exception as e:
        log_print(f"⚠️ [Roformer 分離異常，降級]: {e}")
        return False
    finally:
        stop.set()
        mon.join(timeout=5)
    voc, ins = _pick_stems(outs or [], work_dir)
    if not voc or not ins:
        log_print(f"⚠️ [Roformer 未產出雙 stems（outs={outs}），降級]")
        return False
    try:
        shutil.copy2(voc, vocals_out)
        shutil.copy2(ins, inst_out)
    except Exception as e:
        log_print(f"⚠️ [Roformer 拷檔失敗，降級]: {e}")
        return False
    log_print(f"✨ [Roformer 分離成功] 《{label}》耗時 {time.time() - t0:.0f}s")
    return True
