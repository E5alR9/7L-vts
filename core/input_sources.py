# -*- coding: utf-8 -*-
"""輸入來源分類：一則輸入是老爸本人、直播觀眾、主持插話、還是背景動態（2026-10-25 收斂）。

以前「哪些 source 算老爸」這份清單在主程式抄了 6 次，還抄得不一樣
（有的漏 web_console，老爸在後台打字會被當成別人）。現在只在這裡定義一次，
主程式的對話分派器（chat_processor_worker）照 classify() 的結果分流。
"""
from dataclasses import dataclass
import time

OPERATOR_SOURCES = frozenset({"mic", "text_file", "console", "web_console"})   # 老爸本人（麥克風／打字）
OPERATOR_TYPED_SOURCES = frozenset({"text_file", "console", "web_console"})   # 老爸打字（刻意對她說話）
AUDIENCE_CHAT_SOURCES = frozenset({"tiktok", "tiktok_gift", "twitch", "youtube"})
VIEWER_SOURCES = AUDIENCE_CHAT_SOURCES | {"video_watch"}   # 外部文字：進看板前要中和，防偽造【老爸】或系統標籤
OWNER_INTERJECT = "owner_interject"   # 擁有者公開插話（/api/interject）：走觀眾軌道公開播出
AMBIENT = "tiktok_ambient"            # 點讚、進房、分享這類背景動態

WAKE_WORDS = ("起床", "醒醒", "醒來", "睜開眼", "早安", "早上好", "醒來吧", "別睡了", "/wake", "喚醒", "睜開眼睛", "別睡")


@dataclass
class InputItem:
    text: str
    source: str = "unknown"
    audio_b64: str = None
    timestamp: float = 0.0
    platform_uid: str = ""   # 監聽器給的平台唯一帳號（不在觀眾可控的文字裡）；認老爸只信這個
    user: str = ""


def parse_input_item(raw):
    """佇列裡的原始項目（dict 或字串）→ InputItem；沒有文字回 None。
    dict 沒標 source 時：有錄音算麥克風，否則 unknown。"""
    if not raw:
        return None
    if isinstance(raw, dict):
        text = str(raw.get("text") or "").strip()
        audio = raw.get("audio_base64")
        item = InputItem(text=text, source=raw.get("source") or ("mic" if audio else "unknown"), audio_b64=audio,
                         timestamp=raw.get("timestamp") or time.time(),
                         platform_uid=str(raw.get("platform_uid") or ""), user=str(raw.get("user") or ""))
    else:
        item = InputItem(text=str(raw).strip(), timestamp=time.time())
    return item if item.text else None


def is_operator(source: str, has_audio: bool = False) -> bool:
    """老爸本人的輸入（帶錄音的一律算麥克風）。"""
    return bool(has_audio) or source in OPERATOR_SOURCES


def is_operator_typed(source: str, has_audio: bool = False) -> bool:
    return not has_audio and source in OPERATOR_TYPED_SOURCES


def classify(item: InputItem) -> str:
    """分流：operator（老爸主腦）／audience（觀眾彈幕）／owner_interject／ambient／unknown。"""
    if is_operator(item.source, bool(item.audio_b64)):
        return "operator"
    if item.source in AUDIENCE_CHAT_SOURCES:
        return "audience"
    if item.source == OWNER_INTERJECT:
        return "owner_interject"
    if item.source == AMBIENT:
        return "ambient"
    return "unknown"


def sleep_wake_decision(item: InputItem, operator_enabled: bool) -> str:
    """休眠中收到輸入：wake_audience（觀眾留言或主持插話：睜眼，說不說話交給哨兵）、
    wake_operator（老爸喊喚醒詞，或打字——打字是刻意對她說話，不用喚醒詞；麥克風才要，免得雜音吵醒）、
    ignore（其他：繼續睡）。"""
    if item.source in AUDIENCE_CHAT_SOURCES or item.source == OWNER_INTERJECT:
        return "wake_audience"
    has_audio = bool(item.audio_b64)
    if is_operator(item.source, has_audio) and operator_enabled and (
            any(w in item.text for w in WAKE_WORDS) or is_operator_typed(item.source, has_audio)):
        return "wake_operator"
    return "ignore"
