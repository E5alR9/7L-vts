# -*- coding: utf-8 -*-
"""翻唱的顯卡重活（人聲分離、RVC 變聲）先問筆電的顯卡小幫手（tools/gpu_worker.py）要不要接。

.env 設 REMOTE_GPU_URL（例：http://100.116.25.75:24820）才啟用。沒設、筆電沒開、忙、出錯一律回 False，
調用方照舊在桌機自己跑——這裡壞掉頂多回到原本的樣子。
（2026-10-28 老爸：7L 主要在桌機跑，筆電有開就分擔顯卡；順便少掉桌機分離時的負載尖峰。）
"""
import os
import time

import requests

from core.utils import log_print

_HEALTH_TTL = 20.0        # 問過一次在不在，20 秒內不再問
_CONNECT_TIMEOUT = 3
_READ_TIMEOUT = 900       # 筆電分一首長歌要好幾分鐘
_MIN_WAV = 10000

_health = (0.0, False)


def _url() -> str:
    return (os.getenv("REMOTE_GPU_URL") or "").strip().rstrip("/")


def _mark_down():
    global _health
    _health = (time.time(), False)


def available() -> bool:
    """筆電的小幫手在不在、閒不閒（結果快取 20 秒）。沒設 REMOTE_GPU_URL 直接 False、不連線。"""
    global _health
    url = _url()
    if not url:
        return False
    t, ok = _health
    if time.time() - t < _HEALTH_TTL:
        return ok
    try:
        r = requests.get(url + "/health", timeout=2)
        info = r.json()
        ok = bool(r.ok and info.get("ok") and not info.get("busy"))
    except Exception:
        ok = False
    _health = (time.time(), ok)
    return ok


def _post(path: str, wav: str, params: dict):
    with open(wav, "rb") as f:
        return requests.post(_url() + path, data=f, params=params,
                             timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))


def _write(path: str, data: bytes):
    """先寫 .part 再換名：傳一半斷掉不會留下半個檔被當成快取命中。"""
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def separate(input_wav: str, vocals_out: str, inst_out: str, song_name: str = "") -> bool:
    if not available():
        return False
    t0 = time.time()
    log_print(f"💻 [筆電分擔] 人聲分離交給筆電：《{song_name}》")
    try:
        r = _post("/separate", input_wav, {"song": song_name})
        if r.status_code != 200:
            log_print(f"⚠️ [筆電分擔] 筆電沒接人聲分離（HTTP {r.status_code}），桌機自己來")
            _mark_down()
            return False
        n = int(r.headers.get("X-Vocals-Bytes", "0"))
        body = r.content
        if n < _MIN_WAV or len(body) - n < _MIN_WAV:
            log_print(f"⚠️ [筆電分擔] 筆電傳回的分軌太小（{n}／{len(body) - n} bytes），桌機自己來")
            return False
        _write(vocals_out, body[:n])
        _write(inst_out, body[n:])
    except Exception as e:
        log_print(f"⚠️ [筆電分擔] 人聲分離傳送失敗，桌機自己來: {e}")
        _mark_down()
        return False
    log_print(f"✨ [筆電分擔] 筆電分好人聲與伴奏《{song_name}》，連傳輸 {time.time() - t0:.0f}s")
    return True


def convert_vocal(input_wav: str, output_wav: str, key: float = 0.0,
                  auto_pitch: bool = True, index_rate: float = 0.88) -> bool:
    if not available():
        return False
    t0 = time.time()
    log_print("💻 [筆電分擔] RVC 變聲交給筆電")
    try:
        r = _post("/rvc", input_wav, {"key": key, "auto_pitch": "1" if auto_pitch else "0",
                                      "index_rate": index_rate})
        if r.status_code != 200 or len(r.content) < _MIN_WAV:
            log_print(f"⚠️ [筆電分擔] 筆電沒做好 RVC（HTTP {r.status_code}），桌機自己來")
            _mark_down()
            return False
        _write(output_wav, r.content)
    except Exception as e:
        log_print(f"⚠️ [筆電分擔] RVC 傳送失敗，桌機自己來: {e}")
        _mark_down()
        return False
    log_print(f"✨ [筆電分擔] 筆電變聲完成，連傳輸 {time.time() - t0:.0f}s")
    return True
