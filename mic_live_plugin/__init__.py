# -*- coding: utf-8 -*-
"""
7L 麥克風插件：聲紋（認老爸、認她自己的聲音）、桌面視窗感測。
"""

from .voiceprint_verifier import VoiceprintVerifier, voiceprint_verifier
from .os_desktop_sensor import OSDesktopSensor, os_desktop_sensor

__all__ = [
    "VoiceprintVerifier", "voiceprint_verifier",
    "OSDesktopSensor", "os_desktop_sensor"
]
