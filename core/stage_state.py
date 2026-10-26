# -*- coding: utf-8 -*-
"""舞台狀態：她現在在幹嘛（AI 狀態）、聲音有沒有在出來、在講還是在唱。全程式只有這一份。

- 播放：現在有沒有在播一段有嘴型的音訊（TTS、翻唱），嘴型包絡跟播放起點。以前這四個變數放在主程式，
  翻唱流程用 setattr 從外面改主程式的全域變數，「全部歸零」的四行還在三個地方各寫一次。
- AI 狀態（2026-10-26 從主程式搬來）：IDLE／THINKING／TALKING／PIANO／SINGING／SLEEP，只能經 set_ai_state 改。
  以前主程式一份、鋼琴模組又自己留一份（開琴設 PIANO、收琴設 IDLE，跟主程式那份不相通），
  鋼琴開彈前「等她說完開場白」看的是自己那份，永遠看不到 TALKING，從來沒等過。
- 「她在講話嗎」以前在麥克風、臉部追蹤、看板各寫一套條件，現在是 voice_out／talking。
"""
import time

from core.utils import log_swallowed

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


# ── AI 狀態 ─────────────────────────────────────────────────────────────
AI_STATE = "IDLE"
_STATE_LISTENERS = []   # 狀態改變時通知（主程式登記：記日誌、廣播給後台）
_SINGING_PROBE = None   # 翻唱管線登記：現在有沒有在唱


def ai_state() -> str:
    return AI_STATE


def on_ai_state_change(fn) -> None:
    """登記 fn(舊, 新, 原因)，每次真的換狀態就呼叫。"""
    _STATE_LISTENERS.append(fn)


def set_ai_state(new: str, reason: str = "", only_from=None) -> bool:
    """AI 狀態唯一轉換點。only_from：給了就只在目前狀態屬於它（字串或序列）時才轉，
    取代各處「if 狀態 == X: 狀態 = Y」。回 True＝真的換了（同狀態重設不算，不通知）。"""
    global AI_STATE
    old = AI_STATE
    if only_from is not None:
        allowed = (only_from,) if isinstance(only_from, str) else tuple(only_from)
        if old not in allowed:
            return False
    if new == old:
        return False
    AI_STATE = new
    for fn in list(_STATE_LISTENERS):
        try:
            fn(old, new, reason)
        except Exception:
            log_swallowed()
    return True


def register_singing_probe(fn) -> None:
    global _SINGING_PROBE
    _SINGING_PROBE = fn


def singing() -> bool:
    """在唱歌：翻唱管線的唱歌旗，或狀態是 SINGING。"""
    try:
        if _SINGING_PROBE is not None and _SINGING_PROBE():
            return True
    except Exception:
        log_swallowed()
    return AI_STATE == "SINGING"


def voice_out() -> bool:
    """她的聲音正在出來：TTS／翻唱在播、在唱，或喇叭的音樂通道、翻唱人聲通道在響。"""
    if IS_MP3_PLAYING or singing():
        return True
    try:
        import pygame
        if pygame.mixer.get_init() and (pygame.mixer.music.get_busy() or pygame.mixer.Channel(6).get_busy()):
            return True
    except Exception:
        pass   # 沒有 pygame 或混音器還沒開：當作沒聲音
    return False


def talking() -> bool:
    """在講或在唱：聲音在出來，或狀態已經是 TALKING／SINGING（狀態先切、第一段聲音還在合成的那一下也算）。"""
    return voice_out() or AI_STATE in ("TALKING", "SINGING")
