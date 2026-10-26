# -*- coding: utf-8 -*-
"""麥克風音量表：持續讀麥克風音量給後台和狀態列看（不送任何地方）。

主程式的狀態經 host.<名稱> 即時讀寫（host＝主程式模組，主程式 import 本檔後 bind()）。
用到的名稱列在 HOST_ATTRS，tests/test_workers_host.py 核對主程式真的都有定義。
"""
import asyncio

import numpy as np

from core.utils import log_swallowed

HOST_ATTRS = (
    "CURRENT_MIC_VOL_PERCENT",
    "HAS_PYAUDIO",
    "IS_MIC_ENABLED",
    "current_mic_volume_str",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


async def mic_volume_worker():
    
    stream = None
    if host.HAS_PYAUDIO:
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        except Exception:
            log_swallowed() 

    while True:
        if not host.IS_MIC_ENABLED:
            host.current_mic_volume_str = "[ 麥克風已關閉]"
            host.CURRENT_MIC_VOL_PERCENT = 0
            await asyncio.sleep(0.3)
            continue

        # 🎙️ 全雙工真·不鎖麥：已有專屬聲紋辨識 (WeSpeaker/Voiceprint)，發話中依然保持全時收音監測與音量跳動
        if stream:
            try:
                frames_avail = stream.get_read_available()
                if frames_avail > 0:
                    data = stream.read(frames_avail, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    if len(audio_data) > 0:
                        rms = np.sqrt(np.mean(np.square(audio_data.astype(np.float32))))
                        vol_percent = min(100, int((rms / 2500) * 100))
                        host.CURRENT_MIC_VOL_PERCENT = vol_percent
                        bars = vol_percent // 10
                        bar_str = "█" * bars + "_" * (10 - bars)
                        host.current_mic_volume_str = f"[ 收音: {vol_percent:02d}% |{bar_str}|]"
                await asyncio.sleep(0.05) 
            except Exception:
                host.current_mic_volume_str = "[ 麥克風全時就緒]"
                host.CURRENT_MIC_VOL_PERCENT = 0
                await asyncio.sleep(0.5)
        else:
            host.current_mic_volume_str = "[ 麥克風全時就緒]"
            host.CURRENT_MIC_VOL_PERCENT = 0
            await asyncio.sleep(0.5)
