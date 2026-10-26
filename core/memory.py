import os
import json
import re
import copy
from datetime import datetime
from zoneinfo import ZoneInfo
import time
import asyncio
import threading
from collections import deque
from typing import List, Dict, Any, Optional

# Project imports
from core.utils import log_print, log_swallowed
from core.identity import get_mode, get_owner_name, get_character_name, claims_owner_identity
import core.db as db_module
import services.rag_memory_service as rag_service
from core import eventlog

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# ── 模式隔離（MODE=companion|vtuber）：記憶檔案按模式後綴，兩邊永不互通 ──
MODE = get_mode()


def mode_path(filename: str) -> str:
    """data/ 下檔案按模式後綴（如 unified_memory_vtuber.json）。"""
    base, dot, ext = filename.rpartition(".")
    return os.path.join(DATA_DIR, f"{base}_{MODE}.{ext}" if dot else f"{filename}_{MODE}")


UNIFIED_MEMORY_FILE = mode_path("unified_memory.json")
DIALOGUE_MEMORY_FILE = mode_path("dialogue_memory.json")
THOUGHT_MEMORY_FILE = mode_path("thought_memory.json")
VIEWER_PROFILES_FILE = mode_path("viewer_profiles_local.json")
CLOUD_KNOWLEDGE_FILE = mode_path("cloud_knowledge_local.json")
USER_PROFILE_FILE = mode_path("user_profile_local.json")
MEMORY_CONFIG_FILE = os.path.join(DATA_DIR, "memory_config.json")  # 容量設定兩模式共用

# ── 全域狀態變數（須在所有函式之前宣告）──────────────────────────────────────
CLOUD_KNOWLEDGE_CACHE = None
CLOUD_KNOWLEDGE_CACHE_TIME = 0.0

UNIFIED_MEMORY_FILE = mode_path("unified_memory.json")
DIALOGUE_MEMORY_FILE = mode_path("dialogue_memory.json")
THOUGHT_MEMORY_FILE = mode_path("thought_memory.json")
VIEWER_PROFILES_FILE = mode_path("viewer_profiles_local.json")
CLOUD_KNOWLEDGE_FILE = mode_path("cloud_knowledge_local.json")
USER_PROFILE_FILE = mode_path("user_profile_local.json")
MEMORY_CONFIG_FILE = os.path.join(DATA_DIR, "memory_config.json")  # 容量設定兩模式共用
# 舊無後綴檔（unified_memory.json 等）已廢棄：重建不相容，不再讀寫，留置磁碟僅供人工查閱。

def load_memory_capacity_setting() -> int:
    """載入記憶池容量設定（0 = 無上限，預設 500 句）"""
    try:
        if os.path.exists(MEMORY_CONFIG_FILE):
            with open(MEMORY_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return int(cfg.get("dialogue_capacity", 500))
    except Exception:
        pass
    return 500

DIALOGUE_MEMORY_CAPACITY: int = load_memory_capacity_setting()

# 💬 對話記憶專屬隊列（老爸發話、觀眾彈幕、7L 回應、系統事件）：支援無上限或自訂容量
UNIFIED_DIALOGUE_MEMORY: deque = deque(maxlen=None if DIALOGUE_MEMORY_CAPACITY <= 0 else DIALOGUE_MEMORY_CAPACITY)

# 💭 心流思緒專屬隊列（背景心流、腦內連續推導）：保留最近 150 筆，提取時依字數嚴格截取（約 1000 字）
UNIFIED_THOUGHT_MEMORY: deque = deque(maxlen=150)

# 🌐 全景時序綜合隊列（向後相容、Web 儀表板全景檢視與修改）：支援無上限或對話+心流
UNIFIED_LIVE_MEMORY: deque = deque(maxlen=None if DIALOGUE_MEMORY_CAPACITY <= 0 else (DIALOGUE_MEMORY_CAPACITY + 200))
_LAST_UNIFIED_SAVE_TIME = 0.0
# 記憶推雲端（Firestore 只當備份）：以前每存一次檔（最快 2 秒一次）就推一次最新 150 句，改成最多 60 秒一次
_CLOUD_PUSH_INTERVAL = 60.0
_LAST_CLOUD_PUSH_TIME = 0.0

STREAMER_MIND_BOARD: deque = deque(maxlen=200)

DEFAULT_CHANNEL_ID = f"vts_{MODE}_user"

RECENT_BOT_MESSAGES: List[str] = []
CURRENT_TTS_ID: int = 0


def _load_viewer_profiles() -> dict:
    if not os.path.exists(VIEWER_PROFILES_FILE):
        return {}
    try:
        with open(VIEWER_PROFILES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        log_swallowed()
        return {}


def _store_viewer_profile_local(tiktok_name: str, profile: dict) -> None:
    try:
        all_profiles = _load_viewer_profiles()
        all_profiles[tiktok_name] = profile
        with open(VIEWER_PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(all_profiles, f, ensure_ascii=False, indent=2)
    except Exception:
        log_swallowed()


_CLOUD_PROFILE_MISSES = set()   # 這次開機問過雲端、雲端也沒有的觀眾（新觀眾每則留言不再各問一次）


async def get_viewer_profile(tiktok_name: str) -> dict:
    """取得觀眾資料：本機 viewer_profiles_local_<模式>.json 優先（2026-10-26：Firestore 只當備份）。
    本機沒有這個人才問一次雲端，問到就存回本機。以前每則留言都先等一次 Firestore，本機的再蓋過去。"""
    default = {"tiktok_name": tiktok_name, "call": None, "relationship": None, "impression": None}
    local = _load_viewer_profiles()
    if tiktok_name in local:
        prof = {**default, **local[tiktok_name]}
    else:
        prof = dict(default)
        if db_module.db is not None and tiktok_name not in _CLOUD_PROFILE_MISSES:
            try:
                doc = await db_module.db.collection("viewer_profiles").document(tiktok_name).get()
                if doc.exists:
                    prof = {**default, **doc.to_dict()}
                    _store_viewer_profile_local(tiktok_name, prof)
                else:
                    _CLOUD_PROFILE_MISSES.add(tiktok_name)
            except Exception:
                log_swallowed()
    # 🛡️ 清理佔位符防護 (避免將「稱呼」、「關係」等字詞當作真名)
    if prof.get("call") in ["稱呼", "名字", "暱稱", "CALL", "none", "null", "None", "Null", ""]:
        prof["call"] = tiktok_name
    return prof

async def save_viewer_profile(tiktok_name: str, call: str = None, relationship: str = None, impression: str = None):
    """儲存 TikTok 觀眾資料到 Firebase viewer_profiles + 本地 viewer_profiles_local.json"""
    profile = await get_viewer_profile(tiktok_name)
    if call:
        clean_c = str(call).strip().strip('"\'')
        if clean_c and clean_c not in ["稱呼", "名字", "暱稱", "CALL", "none", "null", "None", "Null"]:
            if claims_owner_identity(clean_c):
                # 觀眾稱呼不能寫成老爸：之後的大腦會照這個稱呼叫他，等於讓觀眾冒充擁有者
                log_print(f"🛑 [認人] 拒絕把觀眾 {tiktok_name} 的稱呼記成「{clean_c}」（冒充擁有者）")
            else:
                profile["call"] = clean_c
    if relationship:
        clean_r = str(relationship).strip().strip('"\'')
        if clean_r and clean_r not in ["關係", "REL", "none", "null", "None", "Null"]:
            if claims_owner_identity(clean_r):
                log_print(f"🛑 [認人] 拒絕把觀眾 {tiktok_name} 的關係記成「{clean_r}」（冒充擁有者）")
            else:
                profile["relationship"] = clean_r
    if impression:
        clean_i = str(impression).strip().strip('"\'')
        if clean_i and clean_i not in ["印象", "IMP", "none", "null", "None", "Null"]:
            profile["impression"] = clean_i
    profile["last_seen"] = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")
    _store_viewer_profile_local(tiktok_name, profile)
    if db_module.db is not None:
        try:
            await db_module.db.collection("viewer_profiles").document(tiktok_name).set(profile, merge=True)
        except Exception:
            log_swallowed()

def _read_local_knowledge() -> Optional[dict]:
    if not os.path.exists(CLOUD_KNOWLEDGE_FILE):
        return None
    try:
        with open(CLOUD_KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data else None
    except Exception:
        log_swallowed()
        return None


def _write_local_knowledge(knowledge: dict) -> None:
    try:
        with open(CLOUD_KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(knowledge, f, ensure_ascii=False, indent=2)
    except Exception:
        log_swallowed()


async def _fetch_cloud_knowledge() -> Optional[dict]:
    try:
        doc = await db_module.db.collection("cloud_mind_knowledge").document("core_knowledge").get()
        return doc.to_dict() if doc.exists else None
    except Exception:
        log_swallowed()
        return None


_KNOWLEDGE_CLOUD_CHECK = {"task": None}


async def _refresh_knowledge_from_cloud() -> None:
    """背景去雲端看一眼：雲端比本機新（另一個模式或另一台改過）才更新本機。只看 last_updated，雲端不會蓋掉本機較新的。"""
    global CLOUD_KNOWLEDGE_CACHE, CLOUD_KNOWLEDGE_CACHE_TIME
    cloud = await _fetch_cloud_knowledge()
    local = _read_local_knowledge() or {}
    if cloud and str(cloud.get("last_updated", "")) > str(local.get("last_updated", "")):
        _write_local_knowledge(cloud)
        CLOUD_KNOWLEDGE_CACHE, CLOUD_KNOWLEDGE_CACHE_TIME = cloud, time.time()
        log_print(f"📥 [知識庫] 雲端那份比較新（{cloud.get('last_updated')}，本機 {local.get('last_updated') or '沒有'}），已更新本機")


async def get_cloud_knowledge() -> dict:
    """7L 的知識庫（人設、規則、梗、系統開關）：本機 cloud_knowledge_local_<模式>.json 優先（2026-10-26：Firestore 只當備份）。
    開機不等雲端：本機有就直接用，程式啟動後第一次讀時背景去雲端看一眼，雲端比較新才更新本機；本機沒有才等雲端一次。
    以前一律先等 Firestore，雲端慢開機就慢。"""
    global CLOUD_KNOWLEDGE_CACHE, CLOUD_KNOWLEDGE_CACHE_TIME
    now = time.time()
    if CLOUD_KNOWLEDGE_CACHE is not None and now - CLOUD_KNOWLEDGE_CACHE_TIME < 60.0:
        return CLOUD_KNOWLEDGE_CACHE

    knowledge = _read_local_knowledge()
    if db_module.db is not None:
        if not knowledge:
            knowledge = await _fetch_cloud_knowledge()
            if knowledge:
                _write_local_knowledge(knowledge)
        elif _KNOWLEDGE_CLOUD_CHECK["task"] is None:
            try:
                _KNOWLEDGE_CLOUD_CHECK["task"] = asyncio.get_running_loop().create_task(_refresh_knowledge_from_cloud())
            except RuntimeError:
                pass

    if not knowledge:
        knowledge = copy.deepcopy(DEFAULT_CLOUD_KNOWLEDGE)

    CLOUD_KNOWLEDGE_CACHE = knowledge
    CLOUD_KNOWLEDGE_CACHE_TIME = now
    return knowledge

async def update_cloud_prompt_field(field_name: str, content: str, action: str = "set"):
    """7L 自主修改或更新雲端提示詞欄位（persona_core, conversation_style, streamer_bio, proactive_guide 等）"""
    clean_field = str(field_name).strip()
    clean_val = str(content).strip().strip('"\'')
    if not clean_field or not clean_val: return
    kn = await get_cloud_knowledge()
    
    if clean_field in ["persona", "persona_core", "worldview", "人設"]:
        kn["persona_core"] = clean_val
        log_print(f"🧠 [7L 雲端世界觀演進] 7L 自主更新核心自我認知：『{clean_val}』")
    elif clean_field in ["style", "conversation_style", "tone", "對話風格"]:
        kn["conversation_style"] = clean_val
        log_print(f"🧠 [7L 雲端語調演進] 7L 自主更新講話風格：『{clean_val}』")
    elif clean_field in ["streamer", "streamer_bio", "tiktok", "直播人設"]:
        kn["streamer_bio"] = clean_val
        log_print(f"🧠 [7L 雲端主播心智演進] 7L 自主更新直播人設：『{clean_val}』")
    elif clean_field in ["proactive", "proactive_guide", "主動發話"]:
        kn["proactive_guide"] = clean_val
        log_print(f"🧠 [7L 雲端靈感演進] 7L 自主更新主動發話引導：『{clean_val}』")
    elif clean_field in ["memes", "memes_and_slang", "梗"]:
        memes = kn.get("memes_and_slang", [])
        if clean_val not in memes:
            memes.append(clean_val)
            del memes[:-50]  # 上限 50，超了丟最舊（讀時只取前 10，存時不清會無限長大）
            kn["memes_and_slang"] = memes
            log_print(f"🧠 [7L 雲端認知演進] 7L 自主學會新梗：『{clean_val}』")
    elif clean_field in ["facts", "learned_facts", "知識", "事實"]:
        facts = kn.get("learned_facts", [])
        if clean_val not in facts:
            facts.append(clean_val)
            del facts[:-100]
            kn["learned_facts"] = facts
            log_print(f"🧠 [7L 雲端認知演進] 7L 自主學會新事實：『{clean_val}』")
    elif clean_field in ["rules", "custom_rules", "規範", "原則"]:
        rules = kn.get("custom_rules", [])
        if clean_val not in rules:
            rules.append(clean_val)
            del rules[:-20]
            kn["custom_rules"] = rules
            log_print(f"🧠 [7L 雲端心智更新] 7L 自主寫入新規範：『{clean_val}』")
    elif clean_field in ["banned", "banned_phrases", "禁用語"]:
        banned = kn.get("banned_phrases", [])
        if clean_val not in banned:
            banned.append(clean_val)
            del banned[:-50]
            kn["banned_phrases"] = banned
            log_print(f"🧠 [7L 雲端禁用語更新] 7L 自主加入禁忌詞：『{clean_val}』")
    else:
        kn[clean_field] = clean_val
        log_print(f"🧠 [7L 雲端自定義更新] 7L 自主更新欄位 {clean_field}：『{clean_val}』")
        
    await save_cloud_knowledge(kn)

async def fetch_from_long_term_memory(channel_id, current_user_msg="", limit: int = 150):
    """讀取對話記憶：從專屬對話記憶庫 UNIFIED_DIALOGUE_MEMORY 提取純對話（絕不被背景心流擠佔，最高支援數百句）"""
    global UNIFIED_DIALOGUE_MEMORY
    if str(channel_id) in [str(DEFAULT_CHANNEL_ID), "tiktok_live_stream", "stream"]:
        history = []
        # 保留最近 limit 句真實對話，確保長上下文記憶完整（支援上百句）
        target_limit = max(1, min(500, int(limit)))
        for it in list(UNIFIED_DIALOGUE_MEMORY)[-target_limit:]:
            r = it.get("role", "user")
            spk = it.get("speaker", "")
            cnt = it.get("content", "")
            if r in ["system", "thought"] or it.get("target") == "內心流動" or it.get("source") == "thought":
                continue
            if r == "assistant" or spk == "7L":
                history.append({"role": "assistant", "content": cnt})
            else:
                prefix = f"【{spk}】" if not cnt.startswith("【") else ""
                history.append({"role": "user", "content": f"{prefix}{cnt}"})
        return history

    # 對於其他通道 (如 Discord 機器人子頻道) 維持相容
    history = []
    if db_module.db is not None:
        try:
            doc_ref = db_module.db.collection("channel_history").document(str(channel_id))
            doc = await doc_ref.get()
            if doc.exists:
                history.extend(doc.to_dict().get("history", []))
        except Exception: pass
    if not history:
        file_path = os.path.join(DATA_DIR, f"memory_{channel_id}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f: history = json.load(f)
            except Exception: pass
    return history

async def save_to_long_term_memory(channel_id, history):
    # 若為老爸主通道或 TikTok 直播通道，已由 append_to_unified_memory 全局統一寫入，不再重寫舊版 channel_history / channel_meta
    if str(channel_id) in [str(DEFAULT_CHANNEL_ID), "tiktok_live_stream", "stream"]:
        return

    raw_history_limit = 500  # 🧠 深度上下文記憶容量擴增至 500 句
    clean_history = [msg for msg in history if not (msg.get("role") == "system" and ("【" in msg.get("content", "")))]
    if len(clean_history) > raw_history_limit: clean_history = clean_history[-raw_history_limit:]
        
    if db_module.db is not None:
        try:
            await db_module.db.collection("channel_history").document(str(channel_id)).set({"history": clean_history, "last_updated": time.time()}, merge=True)
        except Exception: pass
    
    file_path = os.path.join(DATA_DIR, f"memory_{channel_id}.json")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(clean_history, f, ensure_ascii=False, indent=2)
    except Exception: pass

async def clear_all_memories() -> str:
    """清空 7L 與老爸的所有雲端與本機記憶對話紀錄。"""
    if db_module.db is not None:
        try:
            await db_module.db.collection("channel_history").document(DEFAULT_CHANNEL_ID).delete()
            await db_module.db.collection("channel_meta").document(DEFAULT_CHANNEL_ID).delete()
            await db_module.db.collection("channel_history").document("tiktok_live_stream").delete()
            await db_module.db.collection("channel_meta").document("tiktok_live_stream").delete()
            await db_module.db.collection("unified_memory").document("live_stream_timeline").delete()
            await db_module.db.collection("user_memory").document(DEFAULT_CHANNEL_ID).delete()
        except Exception:
            pass
    # 徹底清除所有潛在的記憶檔案，包含舊版與跨模式檔案，但保留設定檔
    for fn in os.listdir(DATA_DIR):
        if ("memory" in fn or "history" in fn) and not fn.endswith("config.json"):
            fp = os.path.join(DATA_DIR, fn)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
    
    for fp in [USER_PROFILE_FILE, VIEWER_PROFILES_FILE, CLOUD_KNOWLEDGE_FILE]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass
    try:
        if 'STREAMER_MIND_BOARD' in globals() and hasattr(STREAMER_MIND_BOARD, 'clear'):
            STREAMER_MIND_BOARD.clear()
        if 'UNIFIED_DIALOGUE_MEMORY' in globals() and hasattr(UNIFIED_DIALOGUE_MEMORY, 'clear'):
            UNIFIED_DIALOGUE_MEMORY.clear()
        if 'UNIFIED_THOUGHT_MEMORY' in globals() and hasattr(UNIFIED_THOUGHT_MEMORY, 'clear'):
            UNIFIED_THOUGHT_MEMORY.clear()
        if 'UNIFIED_LIVE_MEMORY' in globals() and hasattr(UNIFIED_LIVE_MEMORY, 'clear'):
            UNIFIED_LIVE_MEMORY.clear()
            
        try:
            from services.rag_store import reset as reset_rag_store
            reset_rag_store()
        except Exception:
            pass
            
    except Exception:
        pass
    log_print("🧹 [系統] 雲端與本地所有記憶（含對話 500 句專區、心流思緒專區與全景記憶）已徹底重置！")
    return "已成功清空所有雲端與本地對話記憶！"

def record_bot_message(msg: str):
    global RECENT_BOT_MESSAGES, CURRENT_TTS_ID
    clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', msg).strip()
    if clean:
        CURRENT_TTS_ID += 1
        RECENT_BOT_MESSAGES.append(clean)
        if len(RECENT_BOT_MESSAGES) > 30:
            RECENT_BOT_MESSAGES.pop(0)

_SAVE_LOCK = threading.Lock()  # 存檔可能同時從 loop 執行緒和執行緒池進來，同一個 .tmp 不能兩邊一起寫


def _schedule_on_loop(coro, loop=None) -> None:
    """把協程排到 event loop 上。存檔常在執行緒池裡跑，那裡沒有 running loop，
    舊版直接 get_running_loop() 必定 RuntimeError 被吞掉，雲端備份從沒送出過。"""
    try:
        asyncio.get_running_loop().create_task(coro)
        return
    except RuntimeError:
        pass
    if loop is not None and loop.is_running() and not loop.is_closed():
        asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        coro.close()


def _save_unified_memory_to_disk(loop=None, cloud: bool = True):
    """安全將最新對話記憶、心流思緒與全域記憶時間線序列化保存至本地磁碟並同步備份至雲端 Firestore。
    loop：從執行緒池呼叫時傳入主 event loop，雲端同步才排得回去。"""
    with _SAVE_LOCK:
        _save_unified_memory_to_disk_locked(loop, cloud)


def _save_unified_memory_to_disk_locked(loop, cloud):
    global UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY, _LAST_CLOUD_PUSH_TIME
    try:
        # 1. 儲存對話專屬記憶（保留最近 500 句，永不被心流稀釋）
        diag_file = DIALOGUE_MEMORY_FILE + ".tmp"
        with open(diag_file, "w", encoding="utf-8") as f:
            json.dump(list(UNIFIED_DIALOGUE_MEMORY), f, ensure_ascii=False, indent=2)
        if os.path.exists(diag_file):
            if os.path.exists(DIALOGUE_MEMORY_FILE):
                os.replace(diag_file, DIALOGUE_MEMORY_FILE)
            else:
                os.rename(diag_file, DIALOGUE_MEMORY_FILE)

        # 2. 儲存心流專屬記憶（保留最近 150 筆）
        th_file = THOUGHT_MEMORY_FILE + ".tmp"
        with open(th_file, "w", encoding="utf-8") as f:
            json.dump(list(UNIFIED_THOUGHT_MEMORY), f, ensure_ascii=False, indent=2)
        if os.path.exists(th_file):
            if os.path.exists(THOUGHT_MEMORY_FILE):
                os.replace(th_file, THOUGHT_MEMORY_FILE)
            else:
                os.rename(th_file, THOUGHT_MEMORY_FILE)

        # 3. 儲存全景時序綜合記憶
        data_to_save = list(UNIFIED_LIVE_MEMORY)
        temp_file = UNIFIED_MEMORY_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        if os.path.exists(temp_file):
            if os.path.exists(UNIFIED_MEMORY_FILE):
                os.replace(temp_file, UNIFIED_MEMORY_FILE)
            else:
                os.rename(temp_file, UNIFIED_MEMORY_FILE)
                
        # ☁️ 同步備份最新全集中全景時序記憶至雲端 Firestore
        if cloud and db_module.db is not None and time.time() - _LAST_CLOUD_PUSH_TIME >= _CLOUD_PUSH_INTERVAL:
            _LAST_CLOUD_PUSH_TIME = time.time()

            async def sync_unified_to_cloud(items, dialogues):
                try:
                    await db_module.db.collection("unified_memory").document("live_stream_timeline").set({
                        "timeline": items[-150:],
                        "dialogues": dialogues[-150:],
                        "last_updated": time.time()
                    }, merge=True)
                except Exception:
                    pass
            _schedule_on_loop(sync_unified_to_cloud(data_to_save, list(UNIFIED_DIALOGUE_MEMORY)), loop)
    except Exception as e:
        log_print(f"⚠️ [記憶存檔失敗]: {e}")

_SAVE_INTERVAL = 2.0
_TRAILING_SAVE_HANDLE = None
_MEMORY_LOADED = False  # init_unified_memory 載入完才 True；之前 flush 會用空記憶蓋掉磁碟檔


def _kick_save_now() -> None:
    """立刻存一次：有 event loop 就丟執行緒池（帶上 loop 讓雲端同步排得回來），沒有就同步存。"""
    global _LAST_UNIFIED_SAVE_TIME
    _LAST_UNIFIED_SAVE_TIME = time.time()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _save_unified_memory_to_disk()
        return
    loop.run_in_executor(None, _save_unified_memory_to_disk, loop)


def _request_unified_save(now_t: float) -> None:
    """節流存檔：距上次超過 2 秒就立刻存；否則排一次「窗口結束補存」。
    舊版只存窗口開頭那筆，2 秒內的後續對話要等下一次有人說話才落地，關機前那幾句常常丟掉。"""
    global _TRAILING_SAVE_HANDLE
    if now_t - _LAST_UNIFIED_SAVE_TIME > _SAVE_INTERVAL:
        _kick_save_now()
        return
    if _TRAILING_SAVE_HANDLE is not None:
        return  # 已排了補存，這筆會一起存到
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 沒有 loop 的同步呼叫維持舊行為；關機路徑另有 flush_unified_memory()

    def _fire():
        global _TRAILING_SAVE_HANDLE
        _TRAILING_SAVE_HANDLE = None
        _kick_save_now()

    delay = max(0.05, _SAVE_INTERVAL - (now_t - _LAST_UNIFIED_SAVE_TIME))
    _TRAILING_SAVE_HANDLE = loop.call_later(delay, _fire)


def flush_unified_memory() -> None:
    """關機／重開前呼叫：取消排程中的補存，同步把記憶寫進磁碟（雲端來不及等，略過）。"""
    global _TRAILING_SAVE_HANDLE
    if _TRAILING_SAVE_HANDLE is not None:
        try:
            _TRAILING_SAVE_HANDLE.cancel()
        except Exception:
            pass
        _TRAILING_SAVE_HANDLE = None
    if not _MEMORY_LOADED:
        return  # 還沒從磁碟載入（啟動到一半就關），存了反而把舊記憶蓋成空的
    _save_unified_memory_to_disk(cloud=False)


def append_to_unified_memory(speaker: str, target: str, content: str, role: str = "user", source: str = "text"):
    """🌟 全集中全景記憶中樞雙軌寫入常式：
    - 💬 真實對話（老爸說話、觀眾彈幕、7L 回應、系統事件）：寫入 UNIFIED_DIALOGUE_MEMORY（保留最近數百句，上限 500 句）
    - 💭 內心流動（7L 背景連續思緒、腦內心想）：寫入 UNIFIED_THOUGHT_MEMORY（依字數限制管理，約 1000 字）
    - 兩軌徹底分開計算與儲存，心流不再擠佔對話配額，對話可永遠追溯最近幾百句！
    """
    global UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY, _LAST_UNIFIED_SAVE_TIME
    clean_c = content.strip()
    if not clean_c:
        return

    is_thought = (role == "thought" or target == "內心流動" or source == "thought")

    # 防重疊去重：
    if is_thought:
        if UNIFIED_THOUGHT_MEMORY:
            last_th = UNIFIED_THOUGHT_MEMORY[-1]
            if (last_th.get("content") == clean_c and (time.time() - last_th.get("time", 0) < 1.5)):
                return
    else:
        if UNIFIED_DIALOGUE_MEMORY:
            last_item = UNIFIED_DIALOGUE_MEMORY[-1]
            if (last_item.get("speaker") == speaker and 
                last_item.get("content") == clean_c and 
                (time.time() - last_item.get("time", 0) < 1.2)):
                return

    now_t = time.time()
    try:
        t_str = datetime.fromtimestamp(now_t, tz=ZoneInfo('Asia/Taipei')).strftime('%H:%M:%S')
    except Exception:
        t_str = datetime.now().strftime('%H:%M:%S')

    entry = {
        "time": now_t,
        "time_str": t_str,
        "speaker": speaker,
        "target": target,
        "content": clean_c,
        "role": role,
        "source": source
    }

    if is_thought:
        UNIFIED_THOUGHT_MEMORY.append(entry)
    else:
        UNIFIED_DIALOGUE_MEMORY.append(entry)

    UNIFIED_LIVE_MEMORY.append(entry)
    try:
        eventlog.get().record(eventlog.memory_kind(speaker, role, target, source), clean_c, who=speaker, target=target,
                              ts=now_t, role=role, source=source)
    except Exception:
        log_swallowed()

    # 磁碟寫入節流（每隔 2 秒；窗口內的後續寫入會在窗口結束時補存）
    _request_unified_save(now_t)

    # RAG: 若為老爸對話或 AI 回應，加入向量記憶庫
    if role in ["user", "ai"] and source in ["text", "voice"]:
        try:
            rag_text = f"[{t_str}] {speaker}對{target}說: {clean_c}"
            loop = asyncio.get_running_loop()
            loop.create_task(rag_service.add_rag_memory(rag_text, source=role))
        except RuntimeError:
            pass

def init_unified_memory():
    """啟動時載入歷史雙軌記憶：
    1. 💬 對話專屬記憶（上限 500 句，若無則自動從歷史對話文件救援復原）
    2. 💭 心流專屬思緒（上限 150 筆，提取時嚴格控制約 1000 字）
    3. 🌐 全景時序記憶時間線
    """
    global UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY
    loaded_dialogues = []
    loaded_thoughts = []

    # 1. 載入對話專屬記憶
    if os.path.exists(DIALOGUE_MEMORY_FILE):
        try:
            with open(DIALOGUE_MEMORY_FILE, "r", encoding="utf-8") as f:
                d_data = json.load(f)
                if isinstance(d_data, list):
                    loaded_dialogues = d_data[-500:]
        except Exception:
            log_swallowed()

    # 若尚無模式記憶，從舊檔按模式救援（companion 只吃擁有者檔，vtuber 只吃觀眾檔；一次性）
    if not loaded_dialogues:
        recovered = []
        _owner = get_owner_name()
        _char = get_character_name()
        if MODE == "companion":
            _sources = [(os.path.join(DATA_DIR, "memory_vts_local_user.json"), _owner),
                        (os.path.join(DATA_DIR, f"memory_vts_{MODE}_user.json"), _owner)]
        else:
            _sources = [(os.path.join(DATA_DIR, "memory_tiktok_live_stream.json"), "TikTok 觀眾")]
        for fp, spk_def in _sources:
            if os.path.exists(fp):
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        raw_list = json.load(f)
                        if isinstance(raw_list, list):
                            for it in raw_list:
                                r = it.get("role", "user")
                                cnt = it.get("content", "").strip()
                                if not cnt: continue
                                spk = _char if r == "assistant" else spk_def
                                tgt = _owner if spk == _char else _char
                                recovered.append({
                                    "time": time.time() - 3600,
                                    "time_str": "歷史",
                                    "speaker": spk,
                                    "target": tgt,
                                    "content": cnt,
                                    "role": r,
                                    "source": "history"
                                })
                except Exception:
                    log_swallowed()
        if recovered:
            if DIALOGUE_MEMORY_CAPACITY > 0:
                loaded_dialogues = recovered[-DIALOGUE_MEMORY_CAPACITY:]
            else:
                loaded_dialogues = recovered
            log_print(f"🛡️ [記憶救援] 成功從歷史對話檔救援恢復 {len(loaded_dialogues)} 句真實對話！")

    # 2. 載入心流專屬記憶
    if os.path.exists(THOUGHT_MEMORY_FILE):
        try:
            with open(THOUGHT_MEMORY_FILE, "r", encoding="utf-8") as f:
                t_data = json.load(f)
                if isinstance(t_data, list):
                    loaded_thoughts = t_data[-150:]
        except Exception:
            log_swallowed()

    # 若無獨立 thought_memory.json，但有 unified_memory.json
    if not loaded_thoughts and os.path.exists(UNIFIED_MEMORY_FILE):
        try:
            with open(UNIFIED_MEMORY_FILE, "r", encoding="utf-8") as f:
                u_data = json.load(f)
                if isinstance(u_data, list):
                    for it in u_data:
                        r = it.get("role", "")
                        tgt = it.get("target", "")
                        src = it.get("source", "")
                        if r == "thought" or tgt == "內心流動" or src == "thought":
                            loaded_thoughts.append(it)
                        elif not loaded_dialogues:
                            loaded_dialogues.append(it)
                    loaded_thoughts = loaded_thoughts[-150:]
                    if not loaded_dialogues:
                        if DIALOGUE_MEMORY_CAPACITY > 0:
                            loaded_dialogues = loaded_dialogues[-DIALOGUE_MEMORY_CAPACITY:]
        except Exception:
            log_swallowed()

    # 賦值給雙軌 deque
    UNIFIED_DIALOGUE_MEMORY.clear()
    UNIFIED_DIALOGUE_MEMORY.extend(loaded_dialogues)

    UNIFIED_THOUGHT_MEMORY.clear()
    UNIFIED_THOUGHT_MEMORY.extend(loaded_thoughts)

    # 重建全景綜合時序隊列（依時間排序）
    combined_all = sorted(list(UNIFIED_DIALOGUE_MEMORY) + list(UNIFIED_THOUGHT_MEMORY), key=lambda x: x.get("time", 0.0))
    UNIFIED_LIVE_MEMORY.clear()
    if DIALOGUE_MEMORY_CAPACITY > 0:
        live_cap = DIALOGUE_MEMORY_CAPACITY + 200
        UNIFIED_LIVE_MEMORY.extend(combined_all[-live_cap:])
    else:
        UNIFIED_LIVE_MEMORY.extend(combined_all)

    _save_unified_memory_to_disk()
    try:
        n = eventlog.import_memory_entries(eventlog.get(), combined_all)
        if n:
            log_print(f"📒 [流水帳] 第一次開：舊對話記憶 {n} 筆匯進 {os.path.basename(eventlog.get().path)}")
    except Exception:
        log_swallowed()
    global _MEMORY_LOADED
    _MEMORY_LOADED = True
    cap_str = f"上限 {DIALOGUE_MEMORY_CAPACITY} 句" if DIALOGUE_MEMORY_CAPACITY > 0 else "⚡ 無上限"
    log_print(f"📜 [全集中記憶] 雙軌獨立載入成功：💬 對話記憶 {len(UNIFIED_DIALOGUE_MEMORY)} 句（{cap_str}），💭 心流思緒 {len(UNIFIED_THOUGHT_MEMORY)} 筆！")

def get_memory_capacity_config() -> dict:
    """取得當前底層記憶池容量配置與即時數據"""
    global DIALOGUE_MEMORY_CAPACITY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY, UNIFIED_LIVE_MEMORY
    return {
        "ok": True,
        "dialogue_capacity": DIALOGUE_MEMORY_CAPACITY,
        "is_unlimited": DIALOGUE_MEMORY_CAPACITY <= 0,
        "dialogue_count": len(UNIFIED_DIALOGUE_MEMORY),
        "thought_count": len(UNIFIED_THOUGHT_MEMORY),
        "total_count": len(UNIFIED_LIVE_MEMORY)
    }

def set_memory_capacity_config(new_capacity: int) -> dict:
    """修訂底層真實對話記憶池上限（0 = 無上限），即時重組 deque 容量並持久化"""
    global DIALOGUE_MEMORY_CAPACITY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_LIVE_MEMORY
    try:
        val = int(new_capacity)
        if val < 0:
            val = 0
        DIALOGUE_MEMORY_CAPACITY = val

        cur_dialogues = list(UNIFIED_DIALOGUE_MEMORY)
        cur_live = list(UNIFIED_LIVE_MEMORY)

        if val <= 0:
            # ⚡ 徹底解除容量限制：無上限！
            UNIFIED_DIALOGUE_MEMORY = deque(cur_dialogues, maxlen=None)
            UNIFIED_LIVE_MEMORY = deque(cur_live, maxlen=None)
        else:
            UNIFIED_DIALOGUE_MEMORY = deque(cur_dialogues[-val:], maxlen=val)
            live_cap = val + 200
            UNIFIED_LIVE_MEMORY = deque(cur_live[-live_cap:], maxlen=live_cap)

        # 持久化儲存至 memory_config.json
        try:
            with open(MEMORY_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"dialogue_capacity": val}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log_print(f"⚠️ [記憶設定存檔警告]: {e}")

        _save_unified_memory_to_disk()
        cap_desc = "⚡ 無上限" if val <= 0 else f"{val} 句"
        log_print(f"⚙️ [記憶池配置] 底層對話記憶池上限已成功更新為: {cap_desc}（目前對話庫保存: {len(UNIFIED_DIALOGUE_MEMORY)} 句）")
        return get_memory_capacity_config()
    except Exception as e:
        log_print(f"❌ [記憶池配置更新異常]: {e}")
        return {"ok": False, "error": str(e)}

def get_all_unified_memories() -> List[Dict[str, Any]]:
    """取得當前所有全景時序記憶清單（帶有全局索引）"""
    global UNIFIED_LIVE_MEMORY
    items = list(UNIFIED_LIVE_MEMORY)
    res = []
    for idx, it in enumerate(items):
        item_copy = dict(it)
        item_copy["index"] = idx
        res.append(item_copy)
    return res

def _sync_deques_from_live_memory():
    """輔助函式：當全景記憶發生編輯、刪除或去重時，同步重組雙軌隊列"""
    global UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY, DIALOGUE_MEMORY_CAPACITY
    items = list(UNIFIED_LIVE_MEMORY)
    d_list = []
    t_list = []
    for it in items:
        r = it.get("role", "")
        tgt = it.get("target", "")
        src = it.get("source", "")
        if r == "thought" or tgt == "內心流動" or src == "thought":
            t_list.append(it)
        else:
            d_list.append(it)
    UNIFIED_DIALOGUE_MEMORY.clear()
    if DIALOGUE_MEMORY_CAPACITY > 0:
        UNIFIED_DIALOGUE_MEMORY.extend(d_list[-DIALOGUE_MEMORY_CAPACITY:])
    else:
        UNIFIED_DIALOGUE_MEMORY.extend(d_list)
    UNIFIED_THOUGHT_MEMORY.clear()
    UNIFIED_THOUGHT_MEMORY.extend(t_list[-150:])

def update_unified_memory_item(index: int, new_content: str, speaker: Optional[str] = None, role: Optional[str] = None) -> bool:
    """修改指定索引的記憶內容並即時保存"""
    global UNIFIED_LIVE_MEMORY
    items = list(UNIFIED_LIVE_MEMORY)
    if 0 <= index < len(items):
        items[index]["content"] = new_content.strip()
        if speaker is not None:
            items[index]["speaker"] = speaker.strip()
        if role is not None:
            items[index]["role"] = role.strip()
        UNIFIED_LIVE_MEMORY.clear()
        UNIFIED_LIVE_MEMORY.extend(items)
        _sync_deques_from_live_memory()
        _save_unified_memory_to_disk()
        log_print(f"✏️ [記憶庫修改] 已成功修改第 #{index} 筆記憶: 「{new_content[:30]}...」")
        return True
    return False

def delete_unified_memory_item(index: int) -> bool:
    """刪除指定索引的記憶並即時保存"""
    global UNIFIED_LIVE_MEMORY
    items = list(UNIFIED_LIVE_MEMORY)
    if 0 <= index < len(items):
        deleted = items.pop(index)
        UNIFIED_LIVE_MEMORY.clear()
        UNIFIED_LIVE_MEMORY.extend(items)
        _sync_deques_from_live_memory()
        _save_unified_memory_to_disk()
        log_print(f"🗑️ [記憶庫刪除] 已成功刪除第 #{index} 筆記憶: 「{deleted.get('content', '')[:30]}...」")
        return True
    return False

def clean_duplicate_unified_memories(threshold: float = 0.75) -> int:
    """智慧掃描並清理重複思緒與跳針記憶"""
    global UNIFIED_LIVE_MEMORY
    import difflib
    items = list(UNIFIED_LIVE_MEMORY)
    unique_items = []
    removed_count = 0
    
    for it in items:
        content = it.get("content", "").strip()
        role = it.get("role", "")
        is_dup = False
        if role == "thought":
            for prev in unique_items[-5:]:
                if prev.get("role") == "thought":
                    prev_c = prev.get("content", "").strip()
                    if content == prev_c or difflib.SequenceMatcher(None, content, prev_c).ratio() > threshold:
                        is_dup = True
                        break
        else:
            if unique_items:
                prev = unique_items[-1]
                if prev.get("speaker") == it.get("speaker") and prev.get("content", "").strip() == content:
                    is_dup = True

        if is_dup:
            removed_count += 1
        else:
            unique_items.append(it)

    if removed_count > 0:
        UNIFIED_LIVE_MEMORY.clear()
        UNIFIED_LIVE_MEMORY.extend(unique_items)
        _sync_deques_from_live_memory()
        _save_unified_memory_to_disk()
        log_print(f"🧹 [記憶庫去重] 已智慧清理 {removed_count} 筆重複/跳針記憶！剩餘 {len(unique_items)} 筆。")
    return removed_count

def get_recent_thoughts_by_chars(max_chars: int = 1000) -> List[Dict[str, Any]]:
    """提取最近的心流思緒，精確限制在指定字數以內（預設約 1000 字），兼顧思維連貫與極速回覆"""
    global UNIFIED_THOUGHT_MEMORY
    if max_chars <= 0:
        return []
    thoughts = list(UNIFIED_THOUGHT_MEMORY)
    if not thoughts:
        return []

    collected = []
    current_chars = 0
    # 從最新思緒往舊回溯
    for it in reversed(thoughts):
        cnt = str(it.get("content", "")).strip()
        if not cnt or any(k in cnt for k in ["trigger_vts", "move_spatial", "[SILENCE]", "無全新事件", "根據規範"]):
            continue
        c_len = len(cnt)
        if current_chars + c_len > max_chars and collected:
            break
        collected.append(it)
        current_chars += c_len
        if current_chars >= max_chars:
            break

    collected.reverse()
    return collected

def get_unified_memory_context(limit: int = 100, thought_char_limit: int = 1000, include_dialogue: bool = True) -> str:
    """提取雙軌全景時序記憶：
    - 💬 對話部分：取最近 limit 句真實對話（預設 60 句，可擴至百句，上限 500 句，永不被心流擠佔）
    - 💭 心流部分：取最近約 thought_char_limit 字（預設約 1000 字），嚴格控管字數，確保回覆時不會卡太久
    """
    global UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY
    
    if limit <= 0 and thought_char_limit <= 0:
        return ""

    dialogue_items = list(UNIFIED_DIALOGUE_MEMORY)[-limit:] if (limit > 0 and include_dialogue) else []
    thought_items = get_recent_thoughts_by_chars(max_chars=thought_char_limit) if thought_char_limit > 0 else []

    if not dialogue_items and not thought_items:
        return ""

    sections = []

    # 1. 格式化對話區塊
    if dialogue_items:
        d_lines = []
        for it in dialogue_items:
            t_str = it.get("time_str", "即時")
            spk = it.get("speaker", "有人")
            tgt = it.get("target", "")
            cnt = it.get("content", "")
            role = it.get("role", "user")

            if role == "system" or spk == "系統":
                d_lines.append(f"[{t_str}] 📢【系統事件】：{cnt}")
            elif spk == "7L":
                target_str = f"(對{tgt}說)" if tgt and tgt != "所有人" else ""
                d_lines.append(f"[{t_str}] 🤖【7L】{target_str}：{cnt}")
            elif spk in ["老爸", "dad", "E5"]:
                d_lines.append(f"[{t_str}] 👑【老爸】(對 7L 說)：{cnt}")
            else:
                target_str = f"(對 {tgt} 說)" if tgt else ""
                d_lines.append(f"[{t_str}] 💬【{spk}】{target_str}：{cnt}")
        sections.append("【💬 最近真實對話記憶（掌握老爸與觀眾最新聊天脈絡，務必結合理解）：\n" + "\n".join(d_lines))

    # 2. 格式化心流區塊（嚴格字數上限控制，約 1000 字）
    if thought_items:
        t_lines = []
        total_th_chars = sum(len(str(it.get("content", ""))) for it in thought_items)
        for it in thought_items:
            t_str = it.get("time_str", "即時")
            cnt = it.get("content", "")
            t_lines.append(f"[{t_str}] 💭【7L 內心流動】：{cnt}")
        sections.append(f"【💭 7L 近期腦內心流思緒（最新約 {total_th_chars} 字連續心聲，體會當前思考狀態，切勿逐字複誦）】：\n" + "\n".join(t_lines))

    return "\n\n".join(sections)

def get_recent_100_memory_context() -> str:
    """提取當前直播間/系統累積的最新 100 句對話記憶 + 約 1000 字近期心流（供潛意識哨兵極速審核）"""
    return get_unified_memory_context(limit=100, thought_char_limit=1000)

DEFAULT_CLOUD_KNOWLEDGE = {
    "persona_core": "",
    "conversation_style": "",
    "memes_and_slang": [],
    "few_shot_examples": [],
    "learned_facts": [],
    "custom_rules": [],
    "banned_phrases": [],
    "proactive_guide": "",
    "streamer_bio": "",
    "last_updated": ""
}

async def save_cloud_knowledge(knowledge: dict):
    """保存 7L 雲端大腦認知庫至 Firestore 與本地 JSON 快取"""
    global CLOUD_KNOWLEDGE_CACHE, CLOUD_KNOWLEDGE_CACHE_TIME
    knowledge["last_updated"] = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    CLOUD_KNOWLEDGE_CACHE = knowledge
    CLOUD_KNOWLEDGE_CACHE_TIME = time.time()

    local_path = CLOUD_KNOWLEDGE_FILE
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(knowledge, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_print(f"⚠️ [本地大腦寫入錯誤]: {e}")

    if db_module.db is not None:
        try:
            status = await db_module.db.collection("cloud_mind_knowledge").document("core_knowledge").set(knowledge, merge=True)
            if status == 429:
                log_print("⚠️ [雲端大腦同步] Firestore 配額不足，已轉交離線備用佇列。")
            elif status not in (200, 201):
                raise Exception(f"Firestore API returned status {status}")
        except Exception as e:
            log_print(f"⚠️ [雲端記憶寫入異常]: {e}")
            raise Exception(f"雲端大腦同步失敗，請檢查網路 ({e})")
        pass
