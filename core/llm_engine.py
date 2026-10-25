import asyncio
import os
import re
import time
import random
import contextlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import groq
from typing import List, Dict, Tuple, AsyncIterator
from google import genai
from google.genai import types

import core.websocket_patch  # 🔧 修復 Live API additional_headers 相容性
from core.utils import log_print

# --- LLM Engine Configuration & Standby Manager ---
# PROVIDER: GEMINI（google-genai；視覺＋Live 全雙工；見 docs/AI_SOURCES.md）

# 🛡️ 解除全域安全審查限制：將所有危害類別門檻設為 BLOCK_NONE，確保不被惡意熔斷或過度審查
UNRESTRICTED_SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY", threshold="BLOCK_NONE"),
]

GEMINI_KEYS = [k.strip() for k in re.split(r'[\s,;]+', os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "") if k.strip() and len(k.strip()) < 150]

# ⚠️ 非死碼：vts_7L_test.py 會 from core.llm_engine import GROQ_CLIENTS，
#    並在啟動時自行 append AsyncGroq 客戶端（vts L2016），其後 L698 的搜尋提煉
#    第二防線會遍歷它。刪掉這個空 list 會讓 vts 直接 ImportError 起不來。
GROQ_CLIENTS: List = []

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
        cool_key(failed_key, 45.0)  # 同步進全程式共用冷卻表，其他呼叫點也會避開
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
            if k not in exclude and self.cooldown_keys.get(k, 0) < now and not key_cooling_any(k):
                return k
        for k in self.key_pool + GEMINI_KEYS:
            if k not in exclude:
                return k
        return self.primary_key

# ── 全程式共用的金鑰冷卻表（2026-10-22）──
# 以前 429 只有 fetch_ai_response 會封印通道，其他 11 個 Gemini 呼叫點拿候選 key 時看不到，
# 被限流的 key 會被一直重打。現在所有呼叫點遇到限流都寫進這裡，候選池據此排序。
# 鍵：(key, model)；model 為 "" 代表整把 key 冷卻。
_KEY_COOLDOWN: Dict[Tuple[str, str], float] = {}


def cool_key(key: str, seconds: float, model: str = "") -> None:
    """把 (key, model) 冷卻 seconds 秒；已有更長的冷卻就保留較長的。"""
    if not key:
        return
    k = (key, model or "")
    _KEY_COOLDOWN[k] = max(_KEY_COOLDOWN.get(k, 0.0), time.time() + max(0.0, float(seconds)))


def key_cooling(key: str, model: str = "") -> bool:
    """這把 key（整把，或指定 model）是否冷卻中。過期的順手清掉。"""
    now = time.time()
    for k in {(key, ""), (key, model or "")}:
        until = _KEY_COOLDOWN.get(k)
        if until is None:
            continue
        if until > now:
            return True
        _KEY_COOLDOWN.pop(k, None)
    return False


def key_cooling_any(key: str) -> bool:
    """這把 key 在任何模型上冷卻中（候選池排序用：曾被限流的 key 往後排）。"""
    now = time.time()
    return any(until > now for (k, _m), until in list(_KEY_COOLDOWN.items()) if k == key)


def get_dynamic_live_key_candidates(preferred_pool: List[str]) -> List[str]:
    """
    🔄 動態 Live API 金鑰故障轉移候選池

    🎯 目的：
       優先使用該通道專用金鑰，遇到 429/網路中斷時，自動跨池調用全量空閒金鑰繼續維持 Live 雙工對話。
       冷卻中的 key 排到最後（只排序不剔除：全部冷卻時照樣有 key 可試，不餓死）。
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
    candidates.sort(key=key_cooling_any)  # 穩定排序：健康的保持原順序在前
    return candidates


# ── 限流／配額錯誤 → 冷卻多久（2026-10-25 從主程式搬來：所有 Gemini 呼叫點共用）──
def get_seconds_until_pt_midnight() -> float:
    """計算從現在到美國太平洋時間 (PT) 下一個午夜 00:00 還剩多少秒（用於每日配額 RPD 刷新）"""
    try:
        pt_zone = ZoneInfo("America/Los_Angeles")
        now_pt = datetime.now(pt_zone)
        tomorrow_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        diff = (tomorrow_pt - now_pt).total_seconds()
        return max(60.0, diff)
    except Exception:
        return 3600.0


def parse_cooldown_seconds(error_text: str, headers=None) -> float:
    if headers:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try: return max(15.0, float(retry_after) + 5.0)
            except ValueError: pass

    total_seconds = 60.0 
    if not error_text: return total_seconds
        
    error_lower = error_text.lower()

    # 1. 優先精準捕獲 Google GenAI / Groq API 返回的重試秒數或時間字串 (如 "retry in 53.5s", "retryDelay: '53s'")
    match_retry_in = re.search(r'retry (?:in|after|delay)[:\s\']*([0-9.]+)\s*s', error_lower)
    if match_retry_in:
        try: return max(10.0, float(match_retry_in.group(1)) + 5.0)
        except ValueError: pass

    match_hms = re.search(r'(?:try again in|retry in|wait)\s+(?:(\d+)h)?(?:(\d+)m)?([0-9.]+)s', error_lower)
    if match_hms:
        hours = int(match_hms.group(1)) if match_hms.group(1) else 0
        minutes = int(match_hms.group(2)) if match_hms.group(2) else 0
        seconds = float(match_hms.group(3)) if match_hms.group(3) else 0.0
        return max(10.0, hours * 3600 + minutes * 60 + seconds + 5.0) 
        
    match_sec = re.search(r'(?:retry-after|wait|in|please wait)\s+([0-9.]+)\s*(?:s|sec|second|seconds)?', error_lower)
    if match_sec:
        try: return max(10.0, float(match_sec.group(1)) + 5.0)
        except ValueError: pass

    # 2. 404 或未開通 / 下架模型，鎖定至 PT 午夜 (並永久記錄至 DEAD_GEMINI_MODELS)
    if "404" in error_lower or "not_found" in error_lower or "no longer available" in error_lower:
        return get_seconds_until_pt_midnight()

    # 3. 每日總配額耗盡 (Per Day / Daily / RequestsPerDay / RPD / Quota Exceeded) 封印至 PT 午夜 (隔天重置)
    is_daily_exhausted = any(k in error_lower for k in ["per day", "requests per day", "daily requests", "rpd", "tokens per day", "tpd", "exceeded your current quota", "quota exceeded"]) and not any(k in error_lower for k in ["per minute", "minute", "rpm", "tpm"])
    if is_daily_exhausted:
        return get_seconds_until_pt_midnight()

    # 4. 503 暫時性伺服器超載 (鎖定 3 分鐘 / 180 秒)
    if "503" in error_lower or "unavailable" in error_lower or "high demand" in error_lower:
        return 180.0

    # 5. 429 瞬間速率超速 / 頻率限制 (預設短暫冷卻 60 秒)
    if "429" in error_lower or "rate limit" in error_lower or "resource" in error_lower or "quota" in error_lower:
        return 60.0  

    return max(30.0, total_seconds)


_KEY_LIMIT_MARKERS = ("429", "resource_exhausted", "resource exhausted", "rate limit", "quota",
                      "per day", "503", "unavailable", "high demand")


def report_gemini_key_error(key: str, err, model: str = "") -> bool:
    """fetch_ai_response 以外的 Gemini 呼叫點遇錯時呼叫：限流／配額／過載就把 (key, model) 冷卻，
    之後候選池會把這把 key 排到最後，其他呼叫點不會再先撞它。回傳是否有冷卻。"""
    err_low = str(err).lower()
    if not key or not any(m in err_low for m in _KEY_LIMIT_MARKERS):
        return False
    secs = parse_cooldown_seconds(err_low)
    cool_key(key, secs, model)
    log_print(f"🔒 [金鑰冷卻] ...{key[-6:]} {model or '(整把)'} 冷卻 {int(secs)}s：{err_low[:80]}")
    return True


# ── Live API 問一句拿一句（2026-10-25）──
# 哨兵類二元判斷（畫面有沒有大變化、該不該開口）走 Live：不吃 REST 額度。
# 以前畫面哨兵、發言哨兵各抄一份「挑 key → 連線 → 送 → 收轉寫 → 限流記冷卻」。
LIVE_ONE_SHOT_MODEL = "gemini-3.8-live"


async def live_one_shot(system_text: str, prompt: str, pool: List[str], image_jpeg: bytes = b"",
                        timeout: float = 3.8, max_keys: int = 4, accept=None) -> str:
    """依序試 pool（不夠從全部 key 補，冷卻中的排後面）前 max_keys 把沒冷卻的 key，每把限時 timeout 秒。
    有圖先送圖再送 prompt；回這一回合的轉寫文字。accept 不認的回覆（答非所問）換下一把再問；
    限流的 key 記冷卻。全部失敗回 ""。"""
    for g_key in get_dynamic_live_key_candidates(pool)[:max_keys]:
        if key_cooling(g_key, LIVE_ONE_SHOT_MODEL):
            continue
        try:
            client = genai.Client(api_key=g_key)
            cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=types.Content(parts=[types.Part(text=system_text)]),
            )
            text = ""
            async with asyncio.timeout(timeout):
                async with client.aio.live.connect(model=LIVE_ONE_SHOT_MODEL, config=cfg) as session:
                    if image_jpeg:
                        await session.send_realtime_input(video={"data": image_jpeg, "mime_type": "image/jpeg"})
                    await session.send_realtime_input(text=prompt)
                    async for resp in session.receive():
                        c = resp.server_content
                        if c:
                            if c.output_transcription and c.output_transcription.text:
                                text += c.output_transcription.text
                            if c.turn_complete or getattr(c, "generation_complete", False):
                                break
            text = text.strip()
            if text and (accept is None or accept(text)):
                return text
        except Exception as e:
            report_gemini_key_error(g_key, e, LIVE_ONE_SHOT_MODEL)
    return ""


DEAD_GEMINI_MODELS = set()

# ── REST 金鑰同斥追蹤（2026-10-11：同一把 key 不被多個工具同時打，分散流量）──
# 單 event loop 內 dict 操作原子性足夠；Live 長持會話不納入（只管 REST 一次性呼叫）。
_KEY_INFLIGHT: Dict[str, int] = {}


def key_load(key: str) -> int:
    """該 key 當前正在跑的 REST 呼叫數。"""
    return _KEY_INFLIGHT.get(key or "", 0)


@contextlib.asynccontextmanager
async def track_key(key: str) -> AsyncIterator[None]:
    """包住一次 REST generate_content：計數＋1，結束（成功/失敗/取消）必 -1。"""
    k = key or ""
    _KEY_INFLIGHT[k] = _KEY_INFLIGHT.get(k, 0) + 1
    try:
        yield
    finally:
        left = _KEY_INFLIGHT.get(k, 1) - 1
        if left <= 0:
            _KEY_INFLIGHT.pop(k, None)
        else:
            _KEY_INFLIGHT[k] = left


def sort_keys_by_load(keys: List[str]) -> List[str]:
    """按負載排序（空閒優先，穩定排序保持原 ping-pong 順序語義）。
    只排序、不阻擋：全忙時照樣打，不餓死。"""
    return sorted(keys, key=lambda k: _KEY_INFLIGHT.get(k or "", 0))

STREAMER_MIND_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash"
]

KEYS_VISION        = GEMINI_KEYS[12:18] if len(GEMINI_KEYS) >= 18 else GEMINI_KEYS

HIGH_IQ_GEMINI_MODELS = [ 
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite"
]

PROACTIVE_EXCLUDED_MODELS = {
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
}