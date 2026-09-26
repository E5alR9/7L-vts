# -*- coding: utf-8 -*-
"""
7L 實時任務管理器與 Firebase 雲端狀態中樞 (RealtimeTaskManager)
- 統一集中維護 7L 當前進行中的所有任務與狀態 (鋼琴演奏、老爸對話、直播觀眾、背景視覺、系統音訊)
- 自動即時非阻塞同步至 Firebase Firestore (集合: realtime_status, 文件: 7L_current_task) 與本地快取
- 提供給所有 AI 協程 (Gemini 主腦、Live 管道、自主發話 Proactive、Discord 機器人等) 一鍵提取即時狀態摘要
"""

import os
import json
import time
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

class RealtimeTaskManager:
    def __init__(self, local_cache_path: str = None):
        if local_cache_path is None:
            data_dir = "data"
            os.makedirs(data_dir, exist_ok=True)
            self.local_cache_path = os.path.join(data_dir, "realtime_tasks_local.json")
        else:
            self.local_cache_path = local_cache_path
        self.db = None  # Firebase Firestore async client
        
        # 🌟 7L 即時全域狀態快照
        self.current_activity: str = "7L 正常待命中"
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.piano_state: Dict[str, Any] = {
            "is_playing": False,
            "title": "",
            "progress_percent": 0.0,
            "current_time_str": "00:00",
            "total_duration_str": "00:00",
            "instrument": "🎹 古典平台鋼琴 (Grand Piano)",
            "speed": 1.0,
            "volume": 100
        }
        self.vision_context: str = "目前沒有特別的畫面動態。"
        self.audio_context: str = "目前沒有播放特別的聲音。"
        self.dad_context: Dict[str, Any] = {
            "last_input": "",
            "last_interaction_time": 0.0,
            "current_topic": "日常互動",
            "is_read": True,
            "read_time": 0.0
        }
        self.audience_context: Dict[str, Any] = {
            "last_viewer": "",
            "last_comment": "",
            "last_interaction_time": 0.0,
            "active_viewers_count": 0,
            "is_read": True,
            "read_time": 0.0
        }
        self.system_status: Dict[str, Any] = {
            "ai_status": "🟢 通道就緒",
            "mic_volume": "[🟢 麥克風就緒]",
            "mic_action": "待命",
            "is_streaming": False,
            "is_piano_active": False,
            "is_mic_enabled": True
        }
        
        self._last_sync_time: float = 0.0
        self._sync_task: Optional[asyncio.Task] = None
        self._load_local_cache()

    def set_db(self, db_client):
        """綁定 Firebase Firestore 異步客戶端"""
        self.db = db_client

    def _load_local_cache(self):
        """啟動時載入背景情境，並【強制重置短暫硬體狀態 (鋼琴/任務)】，徹底防止重開機殘留舊狀態"""
        if os.path.exists(self.local_cache_path):
            try:
                with open(self.local_cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.vision_context = data.get("vision_context", self.vision_context)
                    self.audio_context = data.get("audio_context", self.audio_context)
                    self.dad_context = data.get("dad_context", self.dad_context)
                    self.audience_context = data.get("audience_context", self.audience_context)
            except Exception:
                pass

        # 🛑 【重開機防殘留鐵律】：系統重啟時，硬體必未演奏、任務必清空，絕不載入舊 session 的殘留演奏狀態！
        self.piano_state["is_playing"] = False
        self.piano_state["title"] = ""
        self.piano_state["progress_percent"] = 0.0
        self.piano_state["current_time_str"] = "00:00"
        self.piano_state["total_duration_str"] = "00:00"
        self.system_status["is_piano_active"] = False
        self.active_tasks.clear()
        self.current_activity = "7L 正常待命中 (全新啟動就緒)"

    def _trigger_sync(self):
        """節流非同步觸發雲端與本地同步 (每秒最多同步一次，避免頻繁打擊 Firebase 額度)"""
        now = time.time()
        if self._sync_task and not self._sync_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._sync_task = loop.create_task(self.sync_to_cloud())
        except RuntimeError:
            pass

    async def sync_to_cloud(self):
        """將當前全量實時狀態同步寫入 Firebase Firestore 與本地快取"""
        now = time.time()
        self._last_sync_time = now
        tz_taipei = ZoneInfo("Asia/Taipei")
        time_str = datetime.now(tz_taipei).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            "current_activity": self.current_activity,
            "active_tasks": self.active_tasks,
            "piano_state": self.piano_state,
            "vision_context": self.vision_context,
            "audio_context": self.audio_context,
            "dad_context": self.dad_context,
            "audience_context": self.audience_context,
            "system_status": self.system_status,
            "updated_at": time_str,
            "timestamp": now
        }

        # 1. 寫入本地快取 (0 延遲保底)
        try:
            with open(self.local_cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 2. 寫入 Firebase Firestore 雲端
        if self.db is not None:
            try:
                await self.db.collection("realtime_status").document("7L_current_task").set(payload, merge=True)
            except Exception:
                pass

    # ────────────────────────────────────────────────────────
    # 📌 任務生命週期管理
    # ────────────────────────────────────────────────────────

    def register_task(self, task_id: str, task_type: str, description: str, detail: Optional[dict] = None):
        """註冊新任務至活躍任務清單"""
        self.active_tasks[task_id] = {
            "type": task_type,
            "description": description,
            "start_time": time.time(),
            "detail": detail or {}
        }
        self._trigger_sync()

    def finish_task(self, task_id: str):
        """結束並移除指定任務"""
        if task_id in self.active_tasks:
            del self.active_tasks[task_id]
            self._trigger_sync()

    def update_activity(self, activity_text: str):
        """更新 7L 當前主要活動描述"""
        self.current_activity = str(activity_text).strip()
        self._trigger_sync()

    # ────────────────────────────────────────────────────────
    # 🎹 鋼琴演奏狀態更新
    # ────────────────────────────────────────────────────────

    def update_piano_state(self, pkg: dict):
        """同步鋼琴即時演奏數據"""
        is_playing = pkg.get("is_playing", False)
        title = pkg.get("title", "")
        self.piano_state.update({
            "is_playing": is_playing,
            "title": title,
            "tracks": pkg.get("tracks", []),
            "progress_percent": pkg.get("progress_percent", 0.0),
            "current_time_str": pkg.get("current_time_str", "00:00"),
            "total_duration_str": pkg.get("total_duration_str", "00:00"),
            "instrument": pkg.get("instrument", self.piano_state.get("instrument")),
            "speed": pkg.get("speed", self.piano_state.get("speed")),
            "volume": pkg.get("volume", self.piano_state.get("volume"))
        })
        self.system_status["is_piano_active"] = is_playing or pkg.get("is_window_open", False)
        if is_playing and title:
            self.current_activity = f"🎹 正在演奏鋼琴: 《{title}》 ({self.piano_state['current_time_str']}/{self.piano_state['total_duration_str']})"
        elif not is_playing and "演奏" in self.current_activity:
            self.current_activity = "7L 正常待命中"
        self._trigger_sync()

    # ────────────────────────────────────────────────────────
    # 👁️ 視覺、聲音與對話情境更新
    # ────────────────────────────────────────────────────────

    def update_vision_context(self, desc: str):
        """更新餘光視覺對螢幕畫面的最新理解"""
        if desc:
            self.vision_context = str(desc).strip()
            self._trigger_sync()

    def update_audio_context(self, desc: str):
        """更新系統聲音感知理解"""
        if desc:
            self.audio_context = str(desc).strip()
            self._trigger_sync()

    def start_dad_task(self, user_input: str, topic: str = ""):
        """記錄老爸發起的最新主腦對話與任務 (新發話標記為未讀)"""
        self.dad_context["last_input"] = str(user_input).strip()
        self.dad_context["last_interaction_time"] = time.time()
        self.dad_context["is_read"] = False
        self.dad_context["read_time"] = 0.0
        if topic:
            self.dad_context["current_topic"] = topic
        if not self.piano_state.get("is_playing", False):
            self.current_activity = f"👑 正在與老爸互動: 「{user_input[:20]}...」"
        self.register_task("dad_main_task", "dad_interaction", f"處理老爸輸入: {user_input[:30]}")

    def finish_dad_task(self):
        """結束老爸主腦任務並標記已讀"""
        self.finish_task("dad_main_task")
        self.dad_context["is_read"] = True
        self.dad_context["read_time"] = time.time()
        if not self.piano_state.get("is_playing", False):
            self.current_activity = "7L 正常待命中"
        self._trigger_sync()

    def mark_dad_input_read(self):
        """📖 將老爸的最新對話標記為已讀（防止 Live API 與自主發話反覆拿同一句話重複開口）"""
        self.dad_context["is_read"] = True
        self.dad_context["read_time"] = time.time()
        self.finish_task("dad_main_task")
        self._trigger_sync()

    def start_audience_task(self, viewer_name: str, comment: str):
        """記錄 TikTok 直播觀眾發起的 Live 互動 (新留言標記為未讀)"""
        self.audience_context["last_viewer"] = viewer_name
        self.audience_context["last_comment"] = comment
        self.audience_context["last_interaction_time"] = time.time()
        self.audience_context["is_read"] = False
        self.audience_context["read_time"] = 0.0
        self.register_task(f"audience_{viewer_name}", "audience_live", f"回應觀眾 {viewer_name}: {comment[:25]}")

    def finish_audience_task(self, viewer_name: str):
        """結束觀眾 Live 互動並標記已讀"""
        self.finish_task(f"audience_{viewer_name}")
        self.audience_context["is_read"] = True
        self.audience_context["read_time"] = time.time()
        self._trigger_sync()

    def mark_audience_input_read(self, viewer_name: str = ""):
        """📖 將直播觀眾留言標記為已讀"""
        self.audience_context["is_read"] = True
        self.audience_context["read_time"] = time.time()
        if viewer_name:
            self.finish_task(f"audience_{viewer_name}")
        self._trigger_sync()

    def update_system_status(self, ai_status: Optional[str] = None, mic_volume: Optional[str] = None, 
                             mic_action: Optional[str] = None, is_streaming: Optional[bool] = None,
                             is_piano_active: Optional[bool] = None, is_mic_enabled: Optional[bool] = None):
        """更新系統硬體與協程狀態"""
        if ai_status is not None: self.system_status["ai_status"] = ai_status
        if mic_volume is not None: self.system_status["mic_volume"] = mic_volume
        if mic_action is not None: self.system_status["mic_action"] = mic_action
        if is_streaming is not None: self.system_status["is_streaming"] = is_streaming
        if is_piano_active is not None: self.system_status["is_piano_active"] = is_piano_active
        if is_mic_enabled is not None: self.system_status["is_mic_enabled"] = is_mic_enabled
        self._trigger_sync()

    # ────────────────────────────────────────────────────────
    # 🧠 AI 自主感知一鍵提取介面 (Prompt Context Builder)
    # ────────────────────────────────────────────────────────

    def get_realtime_summary(self) -> str:
        """生成一鍵注入給所有 AI 大腦 (主腦、Live 管道、Proactive 等) 的即時全量狀態感知文字"""
        piano_info = "無 (鋼琴未開啟/未演奏)"
        if self.piano_state.get("is_playing", False) and self.piano_state.get("title"):
            p = self.piano_state
            t_title = p.get('title', '名曲')
            tracks = p.get('tracks', [])
            track_str = f"（多軌合奏：{'、'.join(tracks)}）" if len(tracks) > 1 else ""
            piano_info = f"🎵 真正正在演奏《{t_title}》{track_str} | 進度: {p.get('current_time_str', '00:00')}/{p.get('total_duration_str', '00:00')} ({p.get('progress_percent', 0):.1f}%) | 音色: {p.get('instrument')} | 倍速: {p.get('speed', 1.0)}x | 音量: {p.get('volume', 100)}%\n  🛑【防歷史過期鐵律】：老爸或觀眾隨時可能在電腦鋼琴視窗中手動選曲或切歌！當前曲目【100% 絕對以此處硬體即時顯示的《{t_title}》為唯一真理】，嚴禁參考舊歷史對話誤認為還在彈上一首！"
        elif self.system_status.get("is_piano_active", False):
            piano_info = "⏸️ 鋼琴已在桌面上就位待命 (目前暫停或已彈完，背景無鋼琴聲)"

        active_tasks_list = []
        for tid, t in self.active_tasks.items():
            active_tasks_list.append(f"• [{t.get('type')}] {t.get('description')}")
        tasks_str = "\n".join(active_tasks_list) if active_tasks_list else "無進行中的繁重背景任務"

        # 👑 老爸對話狀態（已讀/未讀防跳針判斷）
        dad_last = self.dad_context.get('last_input', '')
        dad_is_read = self.dad_context.get('is_read', False)
        if not dad_last:
            dad_info = "無"
        elif dad_is_read:
            dad_info = f"[已讀/剛才已回覆完畢] 前次話語：「{dad_last}」（⚠️ 剛才已對此話進行過完整互動，嚴禁反覆抓著同一句重複發話或調侃！請關注當前螢幕畫面最新進展，無事請安靜陪伴）"
        else:
            dad_info = f"「{dad_last}」 (未讀/待處理，焦點: {self.dad_context.get('current_topic', '日常')})"

        # 📱 直播觀眾狀態（已讀/未讀防跳針判斷）
        aud_viewer = self.audience_context.get('last_viewer', '')
        aud_comment = self.audience_context.get('last_comment', '')
        aud_is_read = self.audience_context.get('is_read', False)
        if not aud_comment:
            aud_info = "無"
        elif aud_is_read:
            aud_info = f"[已讀/已回覆] {aud_viewer}: 「{aud_comment}」"
        else:
            aud_info = f"{aud_viewer}: 「{aud_comment}」 (未讀/待處理)"

        summary = f"""【⚡ 7L 實時全域狀態與進行中任務感知 (即時中樞)】
- 🎯 當前核心動態：{self.current_activity}
- 🎹 鋼琴演奏狀態：{piano_info}
- 👁️ 螢幕畫面感知：{self.vision_context}
- 🎧 系統聲音感知：{self.audio_context}
- 👑 老爸對話狀態：{dad_info}
- 📱 直播間觀眾狀態：{aud_info}
- 🔄 背景並行任務清單：
{tasks_str}"""
        return summary.strip()

# 全域單例
realtime_task_mgr = RealtimeTaskManager()
