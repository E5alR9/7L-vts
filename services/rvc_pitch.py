# -*- coding: utf-8 -*-
"""RVC 整首統一音域判決（僅依賴 numpy/librosa/soundfile，均為專案既有依賴）。

背景：以前逐樂句各自判決（中位數 < 195Hz 的樂句 +12、其餘不動），
混合音域的歌會在樂句邊界忽高忽低（2026-10-09 直播事故）。
現在：先掃完全部樂句，以「發聲時長加權的低音占比」做整首統一判決——
整體偏低就全曲 +12，否則全曲不動，同首歌內絕不跳變。
"""
import os
from typing import Iterable, Tuple

MALE_FEMALE_SPLIT_HZ = 195.0   # 男女聲音域分界（約 G3），與舊逐句邏輯同值
SONG_SHIFT_OCTAVE = 12.0       # 整體偏低時全曲升八度
LOW_DOMINANCE_RATIO = 0.5      # 低音發聲時長占比達此值即判定整體偏低

# （註：2026-10-10 曾有「高音三明治」（f0 降調＋post-DSP 拉回），盲聽證明
# post-DSP 本身就會花栗鼠，已整段移除，詳見 git 歷史。
# 本檔保留 analyze_vocal_range（找高音段落做重訓資料）＋ shift_octave_file
# （做訓練用移調＋增益管制）。）
ANALYZE_SR = 16000             # 分析用取樣率（跟 RVC 內部一致，夠判音高又快）


def decide_song_key_shift(
    phrase_stats: Iterable[Tuple[float, float]],
    *,
    threshold: float = MALE_FEMALE_SPLIT_HZ,
    low_dominance: float = LOW_DOMINANCE_RATIO,
    shift_semitones: float = SONG_SHIFT_OCTAVE,
) -> Tuple[float, float]:
    """整首統一判決。

    phrase_stats: [(樂句中位數Hz, 發聲秒數), ...]（短於 5 幀的碎句由呼叫方先濾掉）
    回傳 (全曲半音偏移, 低音時長占比)：12.0 或 0.0，絕不出現第三種值。
    用發聲時長加權而非句數——一句短唸白不該翻轉整首歌的判決。
    """
    total = 0.0
    low = 0.0
    for med, dur in phrase_stats or []:
        try:
            med_f = float(med)
            dur_f = float(dur)
        except (TypeError, ValueError):
            continue
        if dur_f <= 0:
            continue
        total += dur_f
        if med_f < threshold:
            low += dur_f
    if total <= 0:
        return 0.0, 0.0
    ratio = low / total
    if ratio >= low_dominance:
        return float(shift_semitones), ratio
    return 0.0, ratio


def _file_peak(path: str) -> float:
    """回傳 wav 峰值（0~1+），讀不到回 0.0。"""
    try:
        import soundfile as sf
        import numpy as np
        data, _ = sf.read(path, always_2d=True)
        if data is None or len(data) == 0:
            return 0.0
        return float(np.max(np.abs(data)))
    except Exception:
        return 0.0


def _scale_file_to_peak(path: str, target: float) -> bool:
    """等比壓到目標峰值（線性增益，不改變音色，只防削波）。"""
    try:
        import soundfile as sf
        import numpy as np
        data, sr = sf.read(path, always_2d=True)
        peak = float(np.max(np.abs(data)))
        if peak <= 0 or peak <= target:
            return True
        sf.write(path, (data * (target / peak)).astype(data.dtype), sr)
        return True
    except Exception:
        return False


# DSP 前先留 headroom（太熱的進 rubberband 會被相位效應頂到削波，
# 削掉的波形進 RVC 就是失真教材；實測：0.978 的母帶前降直接削 201 個點）
DSP_HEADROOM = 0.89
# 成品硬天花板（再熱也只壓到這裡，絕不出現 1.000 釘死）
DSP_CEILING = 0.95


def _shift_octave_librosa(work_in: str, out_path: str, semitones: float) -> bool:
    """librosa phase-vocoder 備援（慢但一定有；無共振峰保留）。
    成功就寫好 out_path；任何失敗直接拋給呼叫方轉 False。"""
    import numpy as np
    import librosa
    import soundfile as sf
    data, sr = sf.read(work_in, always_2d=True)
    if data is None or len(data) == 0:
        raise RuntimeError("empty input")
    shifted = np.stack([
        librosa.effects.pitch_shift(ch, sr=sr, n_steps=float(semitones))
        for ch in data.T
    ]).T
    if abs(len(shifted) - len(data)) / max(1, len(data)) > 0.01:
        raise RuntimeError("duration drift")
    sf.write(out_path, shifted, sr)
    print("🔧 [八度DSP] librosa 備援完成（無共振峰保留）。")
    if not (os.path.exists(out_path) and os.path.getsize(out_path) > 10000):
        raise RuntimeError("empty output")


def shift_octave_file(in_path: str, out_path: str, semitones: float) -> bool:
    """八度 DSP（保持時長＋聲道數）：ffmpeg rubberband 主力（快＋保共振峰），
    失敗退 librosa phase-vocoder。全失敗回 False。
    ⚠️ ffmpeg 這版 rubberband 的參數是單數 formant=preserved（不是 formants），
    寫錯會整句報錯退回 librosa＝高音花栗鼠（2026-10-09 實測抓到）。
    全程增益管制：進 DSP 前太熱先壓到 headroom，成品超過天花板就壓下來——
    削波一旦發生就不可逆，絕不能讓削掉的波形流進 RVC 或成品（2026-10-10 實測：
    0.978 母帶前降直接削 201 點、成品釘死 1.000）。"""
    if not semitones:
        return False
    ratio = float(2.0 ** (float(semitones) / 12.0))
    # 先留 headroom（太熱直接進 DSP 會被頂到削波；用 temp 拷貝，原檔不動）
    work_in = in_path
    _work_tmp = None
    try:
        if _file_peak(in_path) > DSP_HEADROOM:
            import shutil
            import uuid
            _work_tmp = in_path + f".headroom_{uuid.uuid4().hex[:8]}.wav"
            shutil.copyfile(in_path, _work_tmp)
            if _scale_file_to_peak(_work_tmp, DSP_HEADROOM):
                print(f"🔉 [八度DSP] 輸入偏熱，先壓到 {DSP_HEADROOM} 留 headroom。")
                work_in = _work_tmp
            else:
                _work_tmp = None
    except Exception:
        _work_tmp = None
        work_in = in_path
    try:
        # 1) ffmpeg rubberband（C 寫的，幾乎即時；formant=preserved 保住母音音色，
        #    window=long＋smoothing=on 專治 sustained 人聲，transients 保持 crisp 護子音）
        try:
            import subprocess
            from core.paths import ffmpeg_exe
            ffmpeg = ffmpeg_exe()
            cmd = [ffmpeg, "-y", "-v", "error", "-i", work_in,
                   "-af", f"rubberband=pitch={ratio}:formant=preserved:window=long:smoothing=on",
                   out_path]
            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                print(f"🔧 [八度DSP] rubberband {semitones:+.0f}半音完成（formant preserved）。")
            else:
                print(f"⚠️ [八度DSP] rubberband 失敗（rc={r.returncode}），改走 librosa 備援（無共振峰保留、高音可能偏亮）。")
                raise RuntimeError("rubberband failed")
        except Exception as e:
            print(f"⚠️ [八度DSP] rubberband 異常改走備援（{e}）。")
            try:
                _shift_octave_librosa(work_in, out_path, float(semitones))
            except Exception:
                return False
        # 成品硬天花板：再熱也壓下來，絕不出現釘死 1.000 的削波點
        if _file_peak(out_path) > DSP_CEILING:
            _scale_file_to_peak(out_path, DSP_CEILING)
            print(f"🔉 [八度DSP] 成品壓到天花板 {DSP_CEILING}（防削波）。")
        return os.path.exists(out_path) and os.path.getsize(out_path) > 10000
    finally:
        try:
            if _work_tmp and os.path.exists(_work_tmp):
                os.remove(_work_tmp)
        except Exception:
            pass
