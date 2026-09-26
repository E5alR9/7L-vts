import os
import json
import re
import copy
from datetime import datetime
from zoneinfo import ZoneInfo
import time
import asyncio
from collections import deque
from typing import List, Dict, Any, Optional

# Project imports
from core.utils import log_print, sys_notify, get_current_time_string
import services.piano_engine as pe
import core.db as db_module
from core.prompts import PromptTemplateEngine

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# ── 全域狀態變數（須在所有函式之前宣告）──────────────────────────────────────
CLOUD_KNOWLEDGE_CACHE = None
CLOUD_KNOWLEDGE_CACHE_TIME = 0.0

UNIFIED_MEMORY_FILE = os.path.join(DATA_DIR, "unified_memory.json")
DIALOGUE_MEMORY_FILE = os.path.join(DATA_DIR, "dialogue_memory.json")
THOUGHT_MEMORY_FILE = os.path.join(DATA_DIR, "thought_memory.json")
MEMORY_CONFIG_FILE = os.path.join(DATA_DIR, "memory_config.json")

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

TIKTOK_CHATROOM_MEMORY: List[Dict[str, Any]] = []
STREAMER_MIND_BOARD: deque = deque(maxlen=200)

DEFAULT_CHANNEL_ID = "vts_local_user"

RECENT_BOT_MESSAGES: List[str] = []
CURRENT_TTS_ID: int = 0


async def get_viewer_profile(tiktok_name: str) -> dict:
    """取得 TikTok 觀眾個人資料（Firebase 優先，本地 viewer_profiles_local.json 備援）"""
    default = {"tiktok_name": tiktok_name, "call": None, "relationship": None, "impression": None}
    prof = dict(default)
    if db_module.db is not None:
        try:
            doc = await db_module.db.collection("viewer_profiles").document(tiktok_name).get()
            if doc.exists:
                prof = {**default, **doc.to_dict()}
        except Exception:
            pass
    local_path = os.path.join(DATA_DIR, "viewer_profiles_local.json")
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                all_profiles = json.load(f)
            if tiktok_name in all_profiles:
                prof = {**default, **all_profiles[tiktok_name]}
        except Exception:
            pass
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
            profile["call"] = clean_c
    if relationship:
        clean_r = str(relationship).strip().strip('"\'')
        if clean_r and clean_r not in ["關係", "REL", "none", "null", "None", "Null"]:
            profile["relationship"] = clean_r
    if impression:
        clean_i = str(impression).strip().strip('"\'')
        if clean_i and clean_i not in ["印象", "IMP", "none", "null", "None", "Null"]:
            profile["impression"] = clean_i
    profile["last_seen"] = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")
    if db_module.db is not None:
        try:
            await db_module.db.collection("viewer_profiles").document(tiktok_name).set(profile, merge=True)
        except Exception:
            pass
    local_path = os.path.join(DATA_DIR, "viewer_profiles_local.json")
    try:
        all_profiles = {}
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                all_profiles = json.load(f)
        all_profiles[tiktok_name] = profile
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(all_profiles, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

async def get_cloud_knowledge() -> dict:
    """取得 7L 雲端大腦認知庫（100% Firestore 雲端優先，本地 cloud_knowledge_local.json 快取備援）"""
    global CLOUD_KNOWLEDGE_CACHE, CLOUD_KNOWLEDGE_CACHE_TIME
    now = time.time()
    if CLOUD_KNOWLEDGE_CACHE is not None and now - CLOUD_KNOWLEDGE_CACHE_TIME < 60.0:
        return CLOUD_KNOWLEDGE_CACHE

    knowledge = None
    if db_module.db is not None:
        try:
            doc = await db_module.db.collection("cloud_mind_knowledge").document("core_knowledge").get()
            if doc.exists:
                knowledge = doc.to_dict()
        except Exception:
            pass

    if not knowledge:
        local_path = os.path.join(DATA_DIR, "cloud_knowledge_local.json")
        if os.path.exists(local_path):
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    knowledge = json.load(f)
            except Exception:
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
            kn["memes_and_slang"] = memes
            log_print(f"🧠 [7L 雲端認知演進] 7L 自主學會新梗：『{clean_val}』")
    elif clean_field in ["facts", "learned_facts", "知識", "事實"]:
        facts = kn.get("learned_facts", [])
        if clean_val not in facts:
            facts.append(clean_val)
            kn["learned_facts"] = facts
            log_print(f"🧠 [7L 雲端認知演進] 7L 自主學會新事實：『{clean_val}』")
    elif clean_field in ["rules", "custom_rules", "規範", "原則"]:
        rules = kn.get("custom_rules", [])
        if clean_val not in rules:
            rules.append(clean_val)
            kn["custom_rules"] = rules
            log_print(f"🧠 [7L 雲端心智更新] 7L 自主寫入新規範：『{clean_val}』")
    elif clean_field in ["banned", "banned_phrases", "禁用語"]:
        banned = kn.get("banned_phrases", [])
        if clean_val not in banned:
            banned.append(clean_val)
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
    for fp in [os.path.join(DATA_DIR, f"memory_{DEFAULT_CHANNEL_ID}.json"), os.path.join(DATA_DIR, "memory_tiktok_live_stream.json"), os.path.join(DATA_DIR, "user_profile_local.json"), os.path.join(DATA_DIR, "unified_memory.json"), DIALOGUE_MEMORY_FILE, THOUGHT_MEMORY_FILE]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass
    try:
        if 'TIKTOK_CHATROOM_MEMORY' in globals() and isinstance(TIKTOK_CHATROOM_MEMORY, list):
            TIKTOK_CHATROOM_MEMORY.clear()
        if 'STREAMER_MIND_BOARD' in globals() and hasattr(STREAMER_MIND_BOARD, 'clear'):
            STREAMER_MIND_BOARD.clear()
        if 'UNIFIED_DIALOGUE_MEMORY' in globals() and hasattr(UNIFIED_DIALOGUE_MEMORY, 'clear'):
            UNIFIED_DIALOGUE_MEMORY.clear()
        if 'UNIFIED_THOUGHT_MEMORY' in globals() and hasattr(UNIFIED_THOUGHT_MEMORY, 'clear'):
            UNIFIED_THOUGHT_MEMORY.clear()
        if 'UNIFIED_LIVE_MEMORY' in globals() and hasattr(UNIFIED_LIVE_MEMORY, 'clear'):
            UNIFIED_LIVE_MEMORY.clear()
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

def _save_unified_memory_to_disk():
    """安全將最新對話記憶、心流思緒與全域記憶時間線序列化保存至本地磁碟並同步備份至雲端 Firestore"""
    global UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY
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
        if db_module.db is not None:
            async def sync_unified_to_cloud(items, dialogues):
                try:
                    await db_module.db.collection("unified_memory").document("live_stream_timeline").set({
                        "timeline": items[-150:],
                        "dialogues": dialogues[-150:],
                        "last_updated": time.time()
                    }, merge=True)
                except Exception:
                    pass
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(sync_unified_to_cloud(data_to_save, list(UNIFIED_DIALOGUE_MEMORY)))
            except RuntimeError:
                pass
    except Exception:
        pass

def append_to_unified_memory(speaker: str, target: str, content: str, role: str = "user", source: str = "text", model: str = ""):
    """🌟 全集中全景記憶中樞雙軌寫入常式：
    - 💬 真實對話（老爸說話、觀眾彈幕、7L 回應、系統事件）：寫入 UNIFIED_DIALOGUE_MEMORY（保留最近數百句，上限 500 句）
    - 💭 內心流動（7L 背景連續思緒、腦內心想）：寫入 UNIFIED_THOUGHT_MEMORY（依字數限制管理，約 1000 字）
    - 兩軌徹底分開計算與儲存，心流不再擠佔對話配額，對話可永遠追溯最近幾百句！
    """
    global UNIFIED_LIVE_MEMORY, UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY, _LAST_UNIFIED_SAVE_TIME, TIKTOK_CHATROOM_MEMORY
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
        "source": source,
        "model": model or ""
    }

    if is_thought:
        UNIFIED_THOUGHT_MEMORY.append(entry)
    else:
        UNIFIED_DIALOGUE_MEMORY.append(entry)
        # 保持向後相容 TIKTOK_CHATROOM_MEMORY
        if "觀眾" in speaker or source == "tiktok_live":
            TIKTOK_CHATROOM_MEMORY.append({"user": speaker, "content": clean_c, "time": now_t})
            if len(TIKTOK_CHATROOM_MEMORY) > 200:
                TIKTOK_CHATROOM_MEMORY.pop(0)

    UNIFIED_LIVE_MEMORY.append(entry)

    # 磁碟寫入節流（每隔 2 秒或必要時儲存）
    if now_t - _LAST_UNIFIED_SAVE_TIME > 2.0:
        _LAST_UNIFIED_SAVE_TIME = now_t
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _save_unified_memory_to_disk)
        except RuntimeError:
            _save_unified_memory_to_disk()

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
            pass

    # 若尚無 dialogue_memory.json，自動從歷史老爸與直播對話庫救援復原
    if not loaded_dialogues:
        recovered = []
        for fp, spk_def in [(os.path.join(DATA_DIR, f"memory_{DEFAULT_CHANNEL_ID}.json"), "老爸"),
                            (os.path.join(DATA_DIR, "memory_tiktok_live_stream.json"), "TikTok 觀眾")]:
            if os.path.exists(fp):
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        raw_list = json.load(f)
                        if isinstance(raw_list, list):
                            for it in raw_list:
                                r = it.get("role", "user")
                                cnt = it.get("content", "").strip()
                                if not cnt: continue
                                spk = "7L" if r == "assistant" else spk_def
                                tgt = "老爸" if spk == "7L" else "7L"
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
                    pass
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
            pass

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
            pass

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

class MemoryDemandLevel:
    INSTANT = "INSTANT"       # ⚡ 極速直通 (突發電擊/摸頭/擁抱、按鈕事件、緊急口令：0歷史記憶、單圖快照、0新聞，1.2s秒級開口)
    LIGHT = "LIGHT"           # 🌸 輕量即時 (簡短問候、看畫面在幹嘛、超短句日常互動：極簡脈絡)
    STANDARD = "STANDARD"     # 💬 標準常規 (日常對話、當下連續互動：適量平衡記憶)
    DEEP = "DEEP"             # 📜 深度追憶 (問過去、算舊帳、回憶細節：調取 100 句記憶庫，滿足上百句回憶需求)
    ULTRA_DEEP = "ULTRA_DEEP" # 🌌 究極全域回溯 (回顧今天全部、從頭想、上百句歷史對話：調取 150~180 句超長記憶)

class MemoryDemandDecision:
    def __init__(self, level: str, u_lim: int, h_lim: int, th_lim: int, need_news: bool, single_screen: bool, reason: str):
        self.level = level
        self.u_lim = u_lim
        self.h_lim = h_lim
        self.th_lim = th_lim
        self.need_news = need_news
        self.single_screen = single_screen
        self.reason = reason

    # 支援元組解構 (向下相容)
    def __iter__(self):
        yield self.level
        yield self.u_lim
        yield self.h_lim
        yield self.th_lim
        yield self.reason

    def __getitem__(self, item):
        return getattr(self, item)

def evaluate_memory_demand(user_input: str, is_voice_input: bool = False, source: str = "mic") -> MemoryDemandDecision:
    """
    🧠 7L 自主記憶需求深度裁決器：
    由 7L 根據老爸發話意圖與當前情境，自主判斷本次開口需要的記憶窗口深度：
    - 按鈕/突發事件：0 記憶秒級響應
    - 常規聊天：輕量平衡記憶
    - 追溯過往/深層回憶：最高調取 100 ~ 180 句超長時序記憶！
    """
    raw = (user_input or "").strip()
    low = raw.lower()

    # 0. 究極全域回溯模式 (ULTRA_DEEP)：明確要求回顧今天全部、查所有聊天、從頭想、上百句
    ultra_keywords = [
        "上百句", "幾百句", "全部記憶", "所有記憶", "回顧今天", "今天聊了什麼", "今天說了什麼", 
        "從頭想", "從頭說", "完整回憶", "所有對話", "全部對話", "深層記憶", "徹底回想", "翻箱倒櫃",
        "回想所有", "全部回想", "今天所有", "今天都聊了"
    ]
    if any(k in low for k in ultra_keywords):
        return MemoryDemandDecision(
            level=MemoryDemandLevel.ULTRA_DEEP,
            u_lim=180,          # 全景時序 180 句 (超長時序覆蓋整場直播/整日交流)
            h_lim=80,           # 歷史對話 80 輪
            th_lim=1200,        # 心流 1200 字
            need_news=False,
            single_screen=False,
            reason="收到深層全域回溯指令，調取 180 句全景時序超長記憶（最高回憶達數百句）"
        )

    # 1. 深度記憶模式 (DEEP)：用戶明確在查驗過去、算舊帳、追問剛才/之前的細節（調取 100 句！）
    deep_keywords = [
        "還記得", "还记得", "之前", "昨天", "上次", "上一次", "剛才那", "刚才那",
        "剛剛那", "刚刚那", "剛才說", "刚才说", "剛剛說", "刚刚说", "剛才發生", "刚才发生",
        "剛剛發生", "刚刚发生", "妳不是說", "你不是说", "不是說過", "不是说过",
        "為啥剛才", "为什么刚才", "剛剛那個", "刚才那个", "以前", "回憶", "回忆", "算帳", "算账",
        "歷史", "历史", "上一把", "上局", "剛那局", "刚才那局", "昨天那", "記不記得", "记不记得",
        "剛才聊", "剛才講", "剛聊到", "剛剛聊到", "回想", "想起來"
    ]
    if any(k in low for k in deep_keywords):
        return MemoryDemandDecision(
            level=MemoryDemandLevel.DEEP,
            u_lim=100,          # 全景時序 100 句（滿足老爸要求：最高回憶能達上百句！）
            h_lim=40,           # 歷史對話 40 輪
            th_lim=800,         # 心流 800 字
            need_news=False,    # 回憶無需外掛新聞
            single_screen=False,# 完整時序畫面
            reason="偵測到追溯過往/回憶求證關鍵意圖，啟動深度記憶庫檢索（100 句全景時序脈絡）"
        )

    # 2. 極速直通模式 (INSTANT)：控制台突發物理刺激、電擊/摸頭/擁抱按鈕、極短指令
    is_console_event = (
        raw.startswith("【⚡") or raw.startswith("【💖") or raw.startswith("【系統")
        or source in ["web_console", "system", "console"]
        or any(k in low for k in ["微電", "大電", "強力電擊", "電擊", "電一下", "摸頭", "擁抱", "揉頭", "關機", "重開"])
    )
    if is_console_event:
        return MemoryDemandDecision(
            level=MemoryDemandLevel.INSTANT,
            u_lim=0,            # 0 句全景記憶（不被舊對話拖累）
            h_lim=0,            # 0 輪對話歷史（專注當前突發事件）
            th_lim=0,           # 0 字心流干擾
            need_news=False,    # 0 新聞
            single_screen=True, # 單圖即時快照（省去多圖編碼傳輸延遲）
            reason="控制台按鈕/突發電擊獎勵事件，啟動零負擔極速直通（0歷史、1.2s即時開口）"
        )

    # 3. 輕量即時模式 (LIGHT)：單純短問候、短打招呼、問螢幕當前畫面
    instant_commands = [
        "早", "晚安", "嗨", "哈囉", "hello", "hi", "hey",
        "停", "別動", "安靜", "閉嘴", "笑一個", "乖", "看螢幕", "看這裡", "好棒", "真乖", "笨蛋"
    ]
    is_short_prompt = len(raw) <= 8 and any(c in low for c in instant_commands)
    is_pure_vision = len(raw) <= 15 and any(k in low for k in ["在幹嘛", "在玩啥", "在玩什麼", "這什麼", "這是啥", "看老爸"])
    
    if is_short_prompt or is_pure_vision:
        return MemoryDemandDecision(
            level=MemoryDemandLevel.LIGHT,
            u_lim=2,            # 僅需最近 2 句時序
            h_lim=1,            # 僅需最近 1 輪對話
            th_lim=50,          # 50 字輕量輔助
            need_news=False,
            single_screen=True, # 單圖快照
            reason="日常短指令/單純視覺互動，啟動輕量記憶窗口（低負擔流暢對話）"
        )

    # 4. 標準流暢模式 (STANDARD)：一般常規互動
    news_keywords = ["新聞", "时事", "時事", "今天有啥大事", "國際", "國際焦點", "熱搜"]
    need_news = any(k in low for k in news_keywords)
    return MemoryDemandDecision(
        level=MemoryDemandLevel.STANDARD,
        u_lim=20,               # 全景時序 20 句（從 8 擴至 20，涵蓋更多輪對話脈絡）
        h_lim=8,                # 歷史對話 8 輪（從 4 擴至 8，大幅改善跨輪記憶連貫性）
        th_lim=300,             # 心流 300 字（從 180 擴至 300，提升心流感知深度）
        need_news=need_news,    # 依話題動態決定是否查新聞
        single_screen=False,    # 完整視覺感知
        reason="常規日常交流，啟動標準平衡記憶窗口（兼顧上下文脈絡與低延遲）"
    )

def get_unified_memory_context(limit: int = 100, thought_char_limit: int = 1000) -> str:
    """提取雙軌全景時序記憶：
    - 💬 對話部分：取最近 limit 句真實對話（預設 60 句，可擴至百句，上限 500 句，永不被心流擠佔）
    - 💭 心流部分：取最近約 thought_char_limit 字（預設約 1000 字），嚴格控管字數，確保回覆時不會卡太久
    """
    global UNIFIED_DIALOGUE_MEMORY, UNIFIED_THOUGHT_MEMORY
    
    if limit <= 0 and thought_char_limit <= 0:
        return ""

    dialogue_items = list(UNIFIED_DIALOGUE_MEMORY)[-limit:] if limit > 0 else []
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

def get_structured_board_context(limit: int = 40, thought_char_limit: int = 200) -> str:
    """📋 看板主腦專用結構化條列（取代 40 句原文直灌）：
    - 100 句原文只餵哨兵做 should_speak 判定，主提示詞只留本函數的精簡條列，省 token、防 MAX_TOKENS 腰斬
    - 按說話人分組：老爸近況 / 各觀眾最新一句 / 7L 上一句（防重複）/ 心流要點
    """
    global UNIFIED_DIALOGUE_MEMORY
    if limit <= 0 and thought_char_limit <= 0:
        return ""

    dialogue_items = list(UNIFIED_DIALOGUE_MEMORY)[-limit:] if limit > 0 else []
    if not dialogue_items:
        return ""

    # 1. 按說話人分組，保留最後出現順序（老爸永遠置頂）
    order: list = []
    grouped: dict = {}
    my_last_reply = ""
    for it in dialogue_items:
        spk = str(it.get("speaker", "有人")).strip() or "有人"
        cnt = str(it.get("content", "")).strip()
        if not cnt:
            continue
        # 去標籤雜訊後比對，連續同人同文只留一則
        clean_c = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', cnt).strip()
        if not clean_c:
            continue
        if spk == "7L":
            my_last_reply = clean_c
            continue
        key = spk
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        else:
            # 同一人在本窗內重複同文只留最新
            grouped[key] = [c for c in grouped[key] if c[1] != clean_c]
        grouped[key].append((it.get("time_str", "即時"), clean_c))
        if key in order:
            order.remove(key)
        order.append(key)

    def _is_dad(spk: str) -> bool:
        return spk in ["老爸", "dad", "E5"] or "老爸" in spk

    lines: list = []
    # 老爸置頂（最近 2 則）
    for spk in [s for s in order if _is_dad(s)]:
        msgs = grouped.get(spk, [])[-2:]
        if msgs:
            joined = " ｜ ".join(f"{c[:60]}" for _, c in msgs)
            lines.append(f"- 👑 老爸近況：{joined}")
    # 觀眾每人最新一句（最多 6 人，只留最近活躍；排除老爸/系統/7L 自身）
    viewers = [s for s in order if not _is_dad(s) and s not in ["系統", "7L"]]
    for spk in viewers[-6:]:
        msgs = grouped.get(spk, [])
        if not msgs:
            continue
        t_str, c = msgs[-1]
        short_spk = re.sub(r'^TikTok 觀眾「([^」]+)」$', r'\1', spk)
        lines.append(f"- 💬 {short_spk}：{c[:80]}")
    # 7L 上一句（提醒勿重複）
    if my_last_reply:
        lines.append(f"- 🤖 7L上一句：{my_last_reply[:80]}（勿重複跳針）")
    # 心流要點（只取關鍵字級長度）
    if thought_char_limit > 0:
        try:
            thoughts = get_recent_thoughts_by_chars(max_chars=thought_char_limit)
            if thoughts:
                key_pts = "；".join(str(it.get("content", "")).strip()[:60] for it in thoughts[-3:] if str(it.get("content", "")).strip())
                if key_pts:
                    lines.append(f"- 💭 心流要點：{key_pts[:200]}")
        except Exception:
            pass

    if not lines:
        return ""
    return "【📜 現場速覽（結構化條列，老爸/觀眾近況一覽，結合最新彈幕理解）】：\n" + "\n".join(lines)

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

    if db_module.db is not None:
        try:
            await db_module.db.collection("cloud_mind_knowledge").document("core_knowledge").set(knowledge, merge=True)
        except Exception as e:
            log_print(f"⚠️ [雲端記憶寫入異常]: {e}")

    local_path = os.path.join(DATA_DIR, "cloud_knowledge_local.json")
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(knowledge, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
