# -*- coding: utf-8 -*-
"""她講話時聽老爸插話（2026-10-26，docs/REDESIGN.md 的 M，老爸決定：要能插話，但不能把她自己的回音當成老爸）。

以前她講話時麥克風一律送靜音給 Live（怕喇叭回音觸發 Live 的語音偵測、她自己打斷自己），
結果老爸在她講話中說的話整句消失。現在她講話時麥克風照聽、先不送：
- 最近 WINDOW 秒有聲音，就用聲紋比「像老爸」和「像她」（mic_live_plugin 的聲紋模型，一次約 64 毫秒）；
- 像老爸 ≥ DAD_MIN、而且比像她高 MARGIN 以上，記一次；連續 NEEDED 次才算老爸插話；
- 算插話：呼叫端停掉她講的話，把剛才那段聲音和之後的都送給 Live，Live 就聽得到老爸。

2026-10-26 離線量（老爸 154 段、她的語音 59 段，各 1.5 秒；她的「回音」是語音快取加衰減、電話頻寬、殘響、底噪）：
她的聲音（回音或原音大聲）被當成老爸 0 次；老爸自己講 99%、跟她一樣大聲 85%、比她大聲 93%、比她小聲 58% 聽得出來。
"""
import asyncio
import io
import time
import wave
from typing import Callable, Optional, Tuple

import numpy as np

WINDOW_SEC = 1.5
CHECK_EVERY_SEC = 0.5
MIN_RMS = 400            # int16；底噪、很小的回音不比
DAD_MIN = 0.50
MARGIN = 0.05
NEEDED = 2


def _wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def voiceprint_scores(wav_bytes: bytes) -> Tuple[float, float]:
    """(像老爸, 像她)：mic_live_plugin 的聲紋模型。"""
    from mic_live_plugin.voiceprint_verifier import voiceprint_verifier as vp
    _, dad = vp.verify_is_dad(wav_bytes)
    _, her = vp.verify_is_7l(wav_bytes)
    return float(dad), float(her)


class BargeInDetector:
    def __init__(self, score_fn: Callable[[bytes], Tuple[float, float]] = voiceprint_scores, sr: int = 16000):
        self.score_fn = score_fn
        self.sr = sr
        self.max_bytes = int(WINDOW_SEC * sr) * 2
        self.reset()

    def reset(self) -> None:
        self.buf = b""
        self.hits = 0
        self.last_check = 0.0
        self.last_scores = (0.0, 0.0)

    def feed(self, pcm: bytes) -> None:
        """她講話時收到的麥克風聲音（16 kHz int16 單聲道）。"""
        self.buf = (self.buf + pcm)[-self.max_bytes:]

    def buffered(self) -> bytes:
        return self.buf

    async def check(self, now: Optional[float] = None) -> bool:
        """該比的時候比一次；連續 NEEDED 次像老爸回 True（呼叫端停掉她、把聲音送給 Live）。"""
        now = time.time() if now is None else now
        if len(self.buf) < self.max_bytes or now - self.last_check < CHECK_EVERY_SEC:
            return False
        self.last_check = now
        x = np.frombuffer(self.buf, dtype=np.int16).astype(np.float32)
        if float(np.sqrt(np.mean(x * x))) < MIN_RMS:
            self.hits = 0
            return False
        dad, her = await asyncio.to_thread(self.score_fn, _wav(self.buf, self.sr))
        self.last_scores = (dad, her)
        self.hits = self.hits + 1 if (dad >= DAD_MIN and dad - her >= MARGIN) else 0
        return self.hits >= NEEDED
