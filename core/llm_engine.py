import os
import re
import time
import random
import groq
from typing import List, Dict, Tuple
from google.genai import types

import core.websocket_patch  # 🔧 修復 Live API additional_headers 相容性
from core.utils import log_print

# --- LLM Engine Configuration & Standby Manager ---

# 🛡️ 解除全域安全審查限制：將所有危害類別門檻設為 BLOCK_NONE，確保不被惡意熔斷或過度審查
UNRESTRICTED_SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY", threshold="BLOCK_NONE"),
]

GEMINI_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip() and len(k.strip()) < 150]

KEYS_AUDIENCE_LIVE = GEMINI_KEYS[0:6] if len(GEMINI_KEYS) >= 6 else GEMINI_KEYS
KEYS_MIND_LIVE     = GEMINI_KEYS[24:30] if len(GEMINI_KEYS) >= 30 else (GEMINI_KEYS[18:24] if len(GEMINI_KEYS) >= 24 else GEMINI_KEYS)  # 🧠 心流 Live 串流專屬金鑰池（獨立通道，不搶觀眾哨兵資源）

class DualHotStandbyLiveManager:
    """
    🛡️ 【Live 潛意識哨兵雙軌熱備中樞 (Dual Hot-Standby Live Sentry Manager)】
    
    🎯 目的：
       為 100 句記憶與彈幕審查哨兵，時刻維持 2 把確定可用、隨時待命的 Live API 金鑰 (Primary 主通道 + Standby 備用通道)。
    
    ⚙️ 運作邏輯：
       1. 正常時由 Primary 主通道提供無限額度超低延遲潛意識發言二元決策。
       2. 當 Primary 發生 429、網路斷線或異常時，Standby 備用通道 0 秒無縫接管升為主通道。
       3. 同時自動從候選金鑰池中迅速補足新的 Standby 金鑰，確保系統永遠有 2 個在線通道熱備！
    """
    def __init__(self, key_pool: List[str]):
        self.key_pool = key_pool
        self.primary_key = key_pool[0] if len(key_pool) > 0 else ""
        self.standby_key = key_pool[1] if len(key_pool) > 1 else (key_pool[0] if key_pool else "")
        self.cooldown_keys: Dict[str, float] = {}

    def get_active_keys(self) -> Tuple[str, str]:
        """取得當前的主通道與備用通道金鑰字串"""
        return self.primary_key, self.standby_key

    def report_key_failure(self, failed_key: str):
        """報告金鑰連線失敗，將其加入冷卻並觸發雙軌熱備無縫切換"""
        now = time.time()
        self.cooldown_keys[failed_key] = now + 45.0
        if failed_key == self.primary_key:
            log_print(f"⚡ [Live 雙軌熱備] 主通道金鑰 (...{failed_key[-6:]}) 異常 ➔ 備用通道 (...{self.standby_key[-6:]}) 立即無縫接管升為主通道！")
            self.primary_key = self.standby_key
            self.standby_key = self._find_next_healthy_key(exclude=[self.primary_key])
        elif failed_key == self.standby_key:
            log_print(f"⚡ [Live 雙軌熱備] 備用通道金鑰 (...{failed_key[-6:]}) 異常 ➔ 立即從金鑰池替換新的熱備金鑰！")
            self.standby_key = self._find_next_healthy_key(exclude=[self.primary_key])

        p_label = f"...{self.primary_key[-6:]}" if self.primary_key else "無"
        s_label = f"...{self.standby_key[-6:]}" if self.standby_key else "無"
        log_print(f"🛡️ [Live 雙軌熱備更新完成] 🟢 主通道: {p_label} | 🟢 備用通道: {s_label}")

    def _find_next_healthy_key(self, exclude: List[str]) -> str:
        """尋找下一把未冷卻且健康的可用金鑰"""
        now = time.time()
        for k in self.key_pool + GEMINI_KEYS:
            if k not in exclude and self.cooldown_keys.get(k, 0) < now:
                return k
        for k in self.key_pool + GEMINI_KEYS:
            if k not in exclude:
                return k
        return self.primary_key

def get_dynamic_live_key_candidates(preferred_pool: List[str]) -> List[str]:
    """
    🔄 動態 Live API 金鑰故障轉移候選池
    
    🎯 目的：
       優先使用該通道專用金鑰，遇到 429/網路中斷時，自動跨池調用全量空閒金鑰繼續維持 Live 雙工對話。
    """
    candidates = []
    seen = set()
    for k in preferred_pool:
        if k and k not in seen:
            candidates.append(k)
            seen.add(k)
    for k in GEMINI_KEYS:
        if k and k not in seen:
            candidates.append(k)
            seen.add(k)
    return candidates

DEAD_GEMINI_MODELS = set()

STREAMER_MIND_MODELS = [
    # ⚡ 優先指定三大極速秒回模型
    "gemini-3-flash-preview",              # ⚡ 第 1 位：閃電推理預覽
    "gemini-3.1-flash-lite",               # ⚡ 第 2 位：超低延遲輕量秒回
    "gemini-3.5-flash-lite",               # ⚡ 第 3 位：超大額度輕量保底
    "gemini-3.6-flash",                    # 🥈 第 4 位：高智商極速主力
    
    # 🧠 第 5~8 位：主力保底與旗艦深度推理大腦
    "gemini-3.5-flash",                    # 🛡️ 第 5 位：高智商穩定主力保底
    "gemini-3.7-flash",                    # 👑 第 6 位：頂配旗艦大腦
    "gemini-3.8-flash",                    # 🚀 第 7 位：2026 全新頂配旗艦大腦
    "gemini-3.1-pro-preview",              # 🧠 第 8 位：超高智商 Pro 預覽
]

KEYS_VISION        = GEMINI_KEYS[12:18] if len(GEMINI_KEYS) >= 18 else GEMINI_KEYS

GROQ_CLIENTS = []

HIGH_IQ_GEMINI_MODELS = [ 
    "gemini-3.8-flash",                    # 🚀 第 1 位：2026 全新頂配旗艦大腦 (高智商思考推理極致)
    "gemini-3.6-flash",                    # 🥈 第 2 位：高智商極速主力 (理解力與執行力超群)
    "gemini-3.7-flash",                    # 👑 第 3 位：旗艦大腦深度推理
    "gemini-3.1-pro-preview",              # 🧠 第 4 位：Pro 深度推理預覽
    "gemini-3-flash-preview",              # ⚡ 第 5 位：閃電推理預覽
    "gemini-3.5-flash",                    # 🛡️ 第 6 位：穩定主力保底
    "gemini-3.1-flash-lite",               # 🥉 第 7 位：超低延遲保底
    "gemini-3.5-flash-lite",               # ⚡ 第 8 位：超大額度保底
]

PROACTIVE_EXCLUDED_MODELS = {
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview"
}