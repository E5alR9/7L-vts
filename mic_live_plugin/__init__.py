# -*- coding: utf-8 -*-
"""
7L 麥克風 Live 語音感知插件 (Mic Live Audio Perception Plugin)
專屬原生音訊多模態解構大腦：聽懂真實發音、辨識微情緒、抓取隱含意圖，同步注入主腦與雲端記憶。
"""

from .audio_analyzer import MicLiveAudioAnalyzer, mic_live_analyzer
from .voiceprint_verifier import VoiceprintVerifier, voiceprint_verifier
from .os_desktop_sensor import OSDesktopSensor, os_desktop_sensor

__all__ = [
    "MicLiveAudioAnalyzer", "mic_live_analyzer",
    "VoiceprintVerifier", "voiceprint_verifier",
    "OSDesktopSensor", "os_desktop_sensor"
]
