import asyncio
import os
import re
import time
import contextlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Tuple, AsyncIterator
from google import genai
from google.genai import types

import core.websocket_patch  # 🔧 修復 Live API additional_headers 相容性
from core.utils import log_print
from core.env_config import load_project_env
from core.paths import ROOT_DIR

load_project_env()   # 下面就要讀金鑰：不管誰先 import 本模組，都先把 .env 讀進來

# --- LLM Engine Configuration & Standby Manager ---
# PROVIDER: GEMINI（google-genai；視覺＋Live 全雙工；見 docs/AI_SOURCES.md）

# ── 模型名稱唯一出處（2026-10-25）：Google 下架或改名時只改這一段 ──
# 以前散在主程式、鋼琴、伴看、麥克風分析各自寫死；作曲一直打已下架的 gemini-2.5-flash，每次 404 都沒人發現
LIVE_MODEL = "gemini-3.8-live"                    # Live 常駐：哨兵、本能、神態導演、YT 伴看、麥克風情緒
LIVE_MAIN_MODELS = ["gemini-3.1-flash-live-preview", LIVE_MODEL]   # Live 主腦輪替順序
FAST_TEXT_MODEL = "gemini-3.5-flash-lite"         # 純文字快速回覆
FAST_MULTIMODAL_MODEL = "gemini-3.6-flash"        # 帶圖／音的快速回覆
AUDIO_MODEL = "gemini-3.1-flash-lite"             # 系統音、聲音片段辨識
GEMINI_MODELS = [                                 # REST 主梯隊：前鋒輕量 → 主力
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",                           # 3.5/3.7 已棄用自動導向 3.6/3.8，直接打目標省一跳
    "gemini-3.8-flash",
]
# REST 大腦（沒有 Live 主腦時）要不要叫子智能體由模型決定：2026-10-26 實測查資料／計時／點歌 3 句，
# 3.6-flash 3/3 有叫、聊天不亂叫；3.5-flash-lite 0/3（嘴上說「我去查」卻沒叫）。輕量版只當最後備援
REST_BRAIN_MODELS = ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
HIGH_IQ_GEMINI_MODELS = [                         # 鋼琴意圖／作曲：聰明的先試
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
STREAMER_MIND_MODELS = GEMINI_MODELS              # 記憶腦袋 REST 備援：跟主梯隊同一份
# 會思考的模型預設想很久：3.6-flash 帶工具一次 11～22 秒，調到 minimal 約 3.5 秒、該不該叫工具照樣 4/4 對
#（2026-10-27 實測，老爸指定調低）。沒列的模型照預設。
THINKING_LEVELS = {"gemini-3.6-flash": "minimal"}


def thinking_config(model: str, deep: bool = False):
    """這個模型要帶的思考設定；沒列的回 None（照模型預設）。deep＝子代理深度思考，至少 low。"""
    level = THINKING_LEVELS.get(model)
    if level is None:
        return None
    if deep and level == "minimal":
        level = "low"
    return types.ThinkingConfig(thinking_level=level)


IMAGE_GEN_MODELS = ["gemini-3.1-flash-lite-image", "gemini-3.1-flash-image", "gemini-3-pro-image"]   # 生圖（Nano Banana）
EMBED_MODEL = "gemini-embedding-001"              # RAG 向量的 Gemini 備援

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

# ── 專屬金鑰池劃分（背景／Live 通道各有偏好的一段，不夠時 get_dynamic_live_key_candidates 從全池補）──
#    - KEYS_AUDIENCE_LIVE：100 句記憶與彈幕潛意識發言審查 Live 專用（6 把）
#    - KEYS_MIC_LIVE：麥克風語音／情緒即時 Live 分析（6 把）
#    - KEYS_VISION：電腦螢幕截圖與眼角餘光視覺（6 把，定義在模型清單旁）
#    - KEYS_PROACTIVE：鋼琴電台與主播自主巡邏（全量）
#    - KEYS_DAD_MAIN：老爸主腦（全量）
KEYS_MIC_LIVE      = GEMINI_KEYS[6:12] if len(GEMINI_KEYS) >= 12 else GEMINI_KEYS
KEYS_PROACTIVE     = GEMINI_KEYS
KEYS_DAD_MAIN      = GEMINI_KEYS #  老爸旗艦主腦享有全部金鑰全量矩陣！


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


def cooldown_left(key: str, model: str = "") -> float:
    """這把 key（整把，或指定 model）還要冷卻幾秒；沒在冷卻回 0。金鑰健康面板用。"""
    until = max(_KEY_COOLDOWN.get((key, ""), 0.0), _KEY_COOLDOWN.get((key, model or ""), 0.0))
    return max(0.0, until - time.time())


def model_cooling(model: str, keys) -> bool:
    """這些 key 在這個模型上全都冷卻中：整個模型先跳過，換下一個（鋼琴挑模型用）。"""
    keys = list(keys)
    return bool(keys) and all(key_cooling(k, model) for k in keys)


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

    # 2. 404 或未開通 / 下架模型，鎖定至 PT 午夜 
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
    """所有 Gemini 呼叫點遇錯時呼叫：限流／配額／過載就把 (key, model) 冷卻，
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
LIVE_ONE_SHOT_MODEL = LIVE_MODEL
# 說完又想到（深度思考副腦）：Live 版長思考，要帶 thinking_level 才連得上；low 實測 6～10 秒想完，high 46 秒還空的
DEEP_THINK_LIVE_MODEL = "gemini-3.8-live-extended-thinking"


async def live_one_shot(system_text: str, prompt: str, pool: List[str], image_jpeg: bytes = b"",
                        timeout: float = 3.8, max_keys: int = 4, accept=None,
                        model: str = LIVE_ONE_SHOT_MODEL, thinking_level: str = "") -> str:
    """依序試 pool（不夠從全部 key 補，冷卻中的排後面）前 max_keys 把沒冷卻的 key，每把限時 timeout 秒。
    有圖先送圖再送 prompt；回這一回合的轉寫文字。accept 不認的回覆（答非所問）換下一把再問；
    限流的 key 記冷卻。全部失敗回 ""。"""
    from core import usage
    for g_key in get_dynamic_live_key_candidates(pool)[:max_keys]:
        if key_cooling(g_key, model):
            continue
        t0 = time.perf_counter()
        try:
            client = genai.Client(api_key=g_key)
            cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=types.Content(parts=[types.Part(text=system_text)]),
            )
            if thinking_level:
                cfg.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)
            text = ""
            async with asyncio.timeout(timeout):
                async with client.aio.live.connect(model=model, config=cfg) as session:
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
            good = bool(text) and (accept is None or accept(text))
            usage.note(model, good, default_role="Live 單次", ms=(time.perf_counter() - t0) * 1000)
            if good:
                return text
        except Exception as e:
            usage.note(model, False, default_role="Live 單次", rate_limited=usage.is_rate_limited(e),
                       ms=(time.perf_counter() - t0) * 1000)
            report_gemini_key_error(g_key, e, model)
    return ""



# ── 輪播選 key（2026-10-25 從主程式搬來：鋼琴模組也要用）──
def get_pingpong_alternating_index(total_keys: int, step: int) -> int:
    """交替序輪演算法 (頭尾交替向內輪播: 這次 1 -> 下次 29 -> 下次 2 -> 下次 28 -> 下次 3 -> 下次 27 ...)"""
    if total_keys <= 0:
        return 0
    cycle_step = step % total_keys
    if cycle_step % 2 == 0:
        idx = cycle_step // 2
    else:
        idx = total_keys - 1 - (cycle_step // 2)
    return max(0, min(total_keys - 1, idx))


def get_pingpong_ring_indices(total_keys: int, start_step: int) -> list:
    """從當前交替序輪步數開始，產生完整的交替序輪檢查序列 (每個 key 恰好出現一次)"""
    if total_keys <= 0:
        return []
    indices = []
    for i in range(total_keys):
        idx = get_pingpong_alternating_index(total_keys, start_step + i)
        if idx not in indices:
            indices.append(idx)
    for i in range(total_keys):
        if i not in indices:
            indices.append(i)
    return indices



# 通道／模型熔斷鎖（API_LOCKS、lock_target、record_model_failure…）2026-10-27 刪掉：寫入端 10-26 跟著
# fetch_ai_response 一起刪了，只剩鋼琴和金鑰面板在讀，永遠判成沒鎖。冷卻一律看上面的 _KEY_COOLDOWN。



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

KEYS_VISION        = GEMINI_KEYS[12:18] if len(GEMINI_KEYS) >= 18 else GEMINI_KEYS

