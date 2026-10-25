# -*- coding: utf-8 -*-
"""舞台播放狀態：現在有沒有在播一段有嘴型的音訊（TTS、翻唱），嘴型包絡跟播放起點。

主程式（對嘴、播放、回音判斷）和翻唱流程（auto_cover_pipeline）共用。以前這四個變數放在主程式，
翻唱流程用 setattr 從外面改主程式的全域變數，「全部歸零」的四行還在三個地方各寫一次。
"""
import time

IS_MP3_PLAYING = False          # 正在播放音訊（TTS 或翻唱）
CURRENT_MOUTH_ENVELOPE = []     # 這段音訊的嘴型包絡（25 格／秒）
CURRENT_SMOOTH_MOUTH = 0.0      # 平滑後的目前嘴型開合
CURRENT_SPEECH_START_TIME = 0.0  # 這段音訊開始播的時間（對嘴用）


def clear_mouth() -> None:
    """嘴型歸零（音訊還可能在播，只是不再對嘴）。"""
    global CURRENT_MOUTH_ENVELOPE, CURRENT_SMOOTH_MOUTH
    CURRENT_MOUTH_ENVELOPE = []
    CURRENT_SMOOTH_MOUTH = 0.0


def stop_playback() -> None:
    """播放結束或被打斷：停播旗標、嘴型、起點全部歸零。"""
    global IS_MP3_PLAYING, CURRENT_SPEECH_START_TIME
    IS_MP3_PLAYING = False
    clear_mouth()
    CURRENT_SPEECH_START_TIME = 0.0


def start_playback(envelope=None, start_time=None) -> None:
    """開始播一段音訊；有嘴型包絡就一起設，起點預設現在。"""
    global IS_MP3_PLAYING, CURRENT_MOUTH_ENVELOPE, CURRENT_SMOOTH_MOUTH, CURRENT_SPEECH_START_TIME
    IS_MP3_PLAYING = True
    if envelope is not None:
        CURRENT_MOUTH_ENVELOPE = envelope
        CURRENT_SMOOTH_MOUTH = 0.0
    CURRENT_SPEECH_START_TIME = time.time() if start_time is None else start_time
