"""說話、唱歌的音量（0～200，100 是原本的大小）；後台滑桿調，存在 data/volume_settings.json。
鋼琴有自己的音量（piano_engine.set_piano_volume），不在這裡。
pygame 的聲道音量最多 1.0，超過 100 的部分直接把聲音放大（快爆音的地方柔和地壓住，不硬削）。
（老爸 2026-11-01：後台加滑動桿 0 到 200 音量控制，說話、唱歌、鋼琴各一條）"""
import json
import os
import threading

import core.paths as paths
from core.utils import log_print, log_swallowed

KINDS = ("speech", "sing")
_cache: dict = {}
_lock = threading.Lock()   # 開唱時在背景執行緒讀、後台在主迴圈寫：第一次讀檔不能蓋掉剛設的值（Fable）
# 正在唱的那首：聲道號碼 → (原本的音量, 聲音已經放大幾倍, 那個 Sound)。滑桿中途拉動時照這個重算聲道音量
_SING_LIVE: dict = {}


def _file() -> str:
    return os.path.join(paths.DATA_DIR, "volume_settings.json")   # 執行時才算：測試包裝會把 DATA_DIR 換到副本


def _clamp(v) -> int:
    try:
        return max(0, min(200, int(round(float(v)))))
    except (TypeError, ValueError):
        return 100


def load() -> dict:
    out = {k: 100 for k in KINDS}
    try:
        with open(_file(), "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        if isinstance(d, dict):
            out.update({k: _clamp(d[k]) for k in KINDS if k in d})
    except FileNotFoundError:
        pass
    except Exception:
        log_swallowed()
    return out


def _ensure_loaded() -> None:
    with _lock:
        if not _cache:
            _cache.update(load())


def get(kind: str) -> int:
    _ensure_loaded()
    return _cache.get(kind, 100)


def set_volume(kind: str, value) -> int:
    if kind not in KINDS:
        raise ValueError(kind)
    _ensure_loaded()
    with _lock:
        _cache[kind] = _clamp(value)
    try:
        path = _file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(_cache), f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        log_swallowed()
    if kind == "sing":
        _apply_sing_live()
    log_print(f"🔊 [音量] {'說話' if kind == 'speech' else '唱歌'}音量調成 {_cache[kind]}%")
    return _cache[kind]


def split(base: float, kind: str) -> tuple:
    """原本的聲道音量 base 乘上滑桿 → (聲道音量 ≤1, 聲音要放大幾倍 ≥1)。"""
    v = base * get(kind) / 100.0
    return min(v, 1.0), max(v, 1.0)


def boost(snd, gain: float):
    """把 pygame 的 Sound 放大 gain 倍；接近最大值的地方柔和壓住。gain ≤1 原樣回傳。"""
    if gain <= 1.001 or snd is None:
        return snd
    import numpy as np
    import pygame
    try:
        a = pygame.sndarray.array(snd)
        if a.dtype.kind != "i":   # 只處理有正負號的整數格式（混音器都開 16 位元有號；無號的中心不在 0）
            return snd
        top = float(np.iinfo(a.dtype).max)
        x = a.astype(np.float32) * (gain / top)
        knee = 0.85
        over = np.abs(x) > knee
        x[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((np.abs(x[over]) - knee) / (1 - knee)))
        return pygame.sndarray.make_sound((x * top).astype(a.dtype))
    except Exception:
        log_swallowed()
        return snd


def prepare(snd, base: float, kind: str):
    """播之前用：回 (放大過的 Sound, 聲道音量, 放大倍數)。"""
    ch_vol, gain = split(base, kind)
    return boost(snd, gain), ch_vol, gain


def sing_started(channels: dict) -> None:
    """唱歌開播時登記：{聲道號碼: (原本的音量, 已放大倍數, Sound)}。"""
    _SING_LIVE.clear()
    _SING_LIVE.update(channels)


def sing_ended(vocal) -> None:
    """唱完放掉那首的聲音（整首放大過的檔幾十 MB，不要留到下一首）；下一首已經開始就不動。"""
    entry = _SING_LIVE.get(6)
    if entry and entry[2] is vocal:
        _SING_LIVE.clear()


def _apply_sing_live() -> None:
    """唱到一半拉滑桿：馬上照新的音量調聲道（超過的部分要下一首才放得更大）。"""
    if not _SING_LIVE:
        return
    try:
        import pygame
        if not pygame.mixer.get_init():
            return
        for idx, (base, gain, snd) in _SING_LIVE.items():
            ch = pygame.mixer.Channel(idx)
            if ch.get_busy() and ch.get_sound() is snd:   # 歌唱完後聲道可能被說話借走：只調還在播這首的
                ch.set_volume(min(1.0, base * get("sing") / 100.0 / gain))
    except Exception:
        log_swallowed()
