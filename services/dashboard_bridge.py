# -*- coding: utf-8 -*-
"""Web 後台 ↔ 主程式的橋（2026-10-23 從 vts_7L_test.main() 拆出，原本是 main() 裡的巢狀 callback）。

組裝方式（main() 只做這幾行）：
    bridge = DashboardBridge(core=sys.modules[__name__], vts=vts, input_queue=input_queue, run_mode=_RUN_MODE)
    await bridge.restore_switches_from_cloud()
    asyncio.create_task(web_dash.start_web_dashboard(port=7860, **bridge.dashboard_callbacks()))

主程式狀態一律經 self.core.<名稱> 即時讀寫（core 由 main() 明確傳入，本檔不 import 主程式、
不翻 sys.modules["__main__"]）。用到的名稱全列在 CORE_ATTRS，tests/test_dashboard_bridge.py
會核對主程式真的都有定義——主程式改名或刪變數，測試先紅。
"""
import re
import time

import core.stage_state as stage
from core.utils import log_print, get_silence_ticks, get_uptime_ticks, format_ticks_to_human

_TAG_RE = re.compile(r"\[[A-Z_]+(?:[:：][^\]]*)?\]")   # 回給後台顯示前拿掉 [EXPRESSION: …] 這類標籤

# 當下的狀態，不是設定：不存進雲端開關、開機也不還原（2026-10-31 Fable 審查：
# 測試按了睡覺，叫醒的路徑又不會再存，她下次真的開機就睡著；直播連線是監聽器自己管的狀態）
TRANSIENT_SWITCHES = frozenset({"IS_SLEEPING", "IS_STREAM_CHAT_ENABLED"})

# 本檔經 core 讀寫的主程式名稱（新增 c.<名稱> 用法時一併登記）
CORE_ATTRS = (
    # 模組
    "pe", "yt_comp", "tk_listener", "live_timer_hub",
    # 狀態（讀）
    "current_ai_status_str", "current_mic_action_str", "is_user_listening",
    "CURRENT_SYSTEM_AUDIO_VOL_PERCENT", "CURRENT_MIC_VOL_PERCENT",
    "LATEST_SYSTEM_AUDIO_TEXT", "LATEST_SYSTEM_AUDIO_TEXT_TIME",
    "LATEST_SYSTEM_MUSIC_INFO", "LATEST_SYSTEM_MUSIC_TIME",
    "LATEST_REALWORLD_SPEECH_TEXT", "LATEST_REALWORLD_SPEECH_TIME",
    "current_screen_context", "current_system_audio_context",
    "IS_LIVE_MODE_ACTIVE", "TOTAL_API_CALLS",
    "CURRENT_VISION_CHANGE_LEVEL", "CURRENT_VISION_CHANGE_SCORE",
    "VISION_HISTORY_STREAM", "LAST_VISION_LOOK_TIME",
    "LATEST_HD_SCREEN_BYTES", "latest_screen_cache", "STREAMER_MIND_BOARD",
    # 開關（讀寫）
    "IS_SLEEPING", "IS_MIC_ENABLED", "IS_AUTO_PIANO_ENABLED", "IS_AUTO_WANDER_ENABLED",
    "IS_PROACTIVE_SPEAK_ENABLED", "IS_PERIPHERAL_VISION_ENABLED", "IS_FACE_TRACKING_ENABLED", "IS_GAZE_CURSOR_ENABLED",
    # 函式
    "set_ai_state", "get_api_stress_metrics", "set_vts_expression", "shutdown_7l", "apply_spatial_position",
    "control_microphone", "set_sleep_mode", "set_timer", "search_google",
    "update_cloud_prompt_field", "clear_all_memories", "generate_ai_image",
    "request_cover_song", "stop_singing", "execute_local_python_code", "execute_tool_dispatch",
    "execute_punish_action", "execute_reward_action",
)


class DashboardBridge:
    """Web 後台全部 callback；core＝主程式模組，vts／input_queue／run_mode 由 main() 帶進來。"""

    def __init__(self, core, vts, input_queue, run_mode: str):
        self.core = core
        self.vts = vts
        self.input_queue = input_queue
        self.run_mode = run_mode  # MODE_TOGGLE 切換時改這裡（原 main() 的 nonlocal _RUN_MODE）

    def dashboard_callbacks(self) -> dict:
        """交給 web_dash.start_web_dashboard 的 callback 全集（port 由 main() 給）。"""
        c = self.core
        import core.memory as _mem
        return dict(
            input_queue=self.input_queue,
            vts=self.vts,
            get_system_state_cb=self.get_system_state,
            set_mic_cb=self.set_mic,
            set_sleep_cb=lambda enable: self.set_switch("IS_SLEEPING", enable),
            trigger_expression_cb=self.trigger_expression,
            # 走模組屬性：後台改記憶容量時 core.memory 會換一個新 deque，檔頭 import 的名字會變舊殼
            get_memory_cb=lambda: list(_mem.UNIFIED_LIVE_MEMORY),
            get_mind_board_cb=lambda: list(c.STREAMER_MIND_BOARD),
            get_last_vision_image_cb=self.get_last_vision_image,
            restart_cb=self.restart,
            shutdown_cb=self.shutdown,
            execute_tool_cb=self.execute_tool_manually,
            get_switches_cb=self.get_switches,
            set_switch_cb=self.set_switch,
            punish_cb=c.execute_punish_action,
            reward_cb=c.execute_reward_action,
        )

    def get_audio_perception_summary(self):
        """整合電腦內部聲音 (WASAPI Loopback) 與現實環境聲音 (MIC) 的多模態感知資料"""
        c = self.core
        # 1. 電腦內部聲音感知 (全系統聲音：WASAPI Loopback 捕捉所有喇叭輸出)
        #  LEVEL 音量百分比：100% 真實反映整台電腦當前的即時音量跳動，絕不死鎖在固定數值！
        sys_level = min(100, max(0, int(c.CURRENT_SYSTEM_AUDIO_VOL_PERCENT)))
        piano_playing = False
        piano_song = ""

        try:
            if c.pe and c.pe.is_piano_active_and_alive():
                piano_playing = True
                piano_song = c.pe.current_piano_song_title or c.pe.GLOBAL_PIANO_REALTIME_STATE.get("title") or "名曲"
        except Exception:
            pass

        now = time.time()
        has_recent_sys_text = bool(c.LATEST_SYSTEM_AUDIO_TEXT and (now - c.LATEST_SYSTEM_AUDIO_TEXT_TIME < 20.0))
        has_recent_music = bool(c.LATEST_SYSTEM_MUSIC_INFO and (now - c.LATEST_SYSTEM_MUSIC_TIME < 25.0))

        if piano_playing:
            if has_recent_sys_text:
                sys_tag = "全系統音訊 (鋼琴+語音)"
                sys_detail = f"7L 正在彈奏：《{piano_song}》 | 聽見電腦語音：『{c.LATEST_SYSTEM_AUDIO_TEXT}』"
            elif sys_level > 5:
                sys_tag = "全系統音訊 (鋼琴演奏)"
                sys_detail = f"電腦全系統聲音監聽中 | 7L 正在彈奏：《{piano_song}》"
            else:
                sys_tag = "全系統音訊 (鋼琴待命)"
                sys_detail = f"7L 琴房在線 | 曲目：《{piano_song}》"
        elif has_recent_music and sys_level > 3:
            sys_tag = "辨識到音樂/音效"
            sys_detail = f"聽出電腦正在播放：{c.LATEST_SYSTEM_MUSIC_INFO}"
        elif has_recent_sys_text:
            sys_tag = "辨識到電腦語音/台詞"
            sys_detail = f"聽見電腦音訊：『{c.LATEST_SYSTEM_AUDIO_TEXT}』"
        elif sys_level > 5:
            # 檢查是否有螢幕影音線索
            screen_ctx = c.current_screen_context
            if screen_ctx and any(k in screen_ctx for k in ["YouTube", "影片", "音樂", "鋼琴", "Campanella", "piano", "歌"]):
                hint_clean = screen_ctx.split("，")[0].split("。")[0][:28]
                sys_tag = "播放影音中"
                sys_detail = f"偵測到螢幕影音播放中 ({hint_clean})，7L 正在聆聽曲目..."
            else:
                sys_tag = "播放全系統音訊"
                sys_detail = "電腦正在播放背景音樂/旋律，7L 正在辨識中..."
        elif c.current_system_audio_context and "目前沒有" not in c.current_system_audio_context:
            sys_tag = "播放中"
            sys_detail = c.current_system_audio_context
        else:
            sys_tag = "安靜無聲"
            sys_detail = "電腦目前無音訊輸出（全系統聲音安靜）。"

        # 2. 現實環境聲音感知
        real_tag = "靈敏傾聽中"
        real_detail = "現實環境安靜，等待老爸說話中..."
        real_level = min(100, max(0, int(c.CURRENT_MIC_VOL_PERCENT)))

        if c.IS_SLEEPING:
            real_tag = "休眠暫停"
            real_detail = "7L 正在睡覺，已暫停接收現實人聲。"
            real_level = 0
        elif not c.IS_MIC_ENABLED:
            real_tag = "麥克風靜音"
            real_detail = "麥克風目前已手動關閉。"
            real_level = 0
        elif c.is_user_listening:
            real_tag = "捕捉到人聲"
            real_detail = "正在傾聽老爸說話中..."
            if real_level < 25:
                real_level = 45
        elif c.LATEST_REALWORLD_SPEECH_TEXT and (time.time() - c.LATEST_REALWORLD_SPEECH_TIME < 45):
            diff_sec = int(time.time() - c.LATEST_REALWORLD_SPEECH_TIME)
            time_hint = "剛剛" if diff_sec < 5 else f"{diff_sec} 秒前"
            real_tag = "剛才發話"
            real_detail = f"老爸{time_hint}說：『{c.LATEST_REALWORLD_SPEECH_TEXT}』"
        elif real_level > 12:
            real_tag = "環境動態"
            real_detail = "偵測到微弱聲響，隨時待命辨識..."

        # 整體狀態
        if c.IS_SLEEPING:
            status_text = "休眠暫停中"
        elif piano_playing:
            status_text = " 鋼琴演奏 & 全系統聲音"
        elif sys_level > 5 and c.is_user_listening:
            status_text = "電腦全系統音訊 & 聆聽老爸"
        elif c.is_user_listening:
            status_text = " 聆聽老爸中"
        elif sys_level > 5:
            status_text = " 電腦全系統音訊播放中"
        else:
            status_text = "雙向全雙工監聽"

        return {
            "status_text": status_text,
            "sys_tag": sys_tag,
            "sys_detail": sys_detail,
            "sys_level": sys_level,
            "real_tag": real_tag,
            "real_detail": real_detail,
            "real_level": real_level,
            "user_speaking": c.LATEST_REALWORLD_SPEECH_TEXT if (time.time() - c.LATEST_REALWORLD_SPEECH_TIME < 45) else ""
        }

    def get_system_state(self):
        c = self.core
        #  鋼琴在線狀態即時動態核實 (若鋼琴被強制關機，秒級自動回歸 IDLE，絕不卡死)
        if stage.ai_state() == "PIANO" and not c.pe.is_piano_active_and_alive():
            c.set_ai_state("IDLE", "後台核實：鋼琴已不在線", only_from="PIANO")

        yt = c.yt_comp
        eff_status = " 正常運作中" if not c.IS_SLEEPING and stage.ai_state() == "IDLE" and "休眠" not in c.current_ai_status_str else c.current_ai_status_str
        stress_info = c.get_api_stress_metrics()
        silence_ticks = get_silence_ticks()
        uptime_ticks = get_uptime_ticks()
        return {
            "ai_status": eff_status,
            "ai_state": "sleep" if c.IS_SLEEPING else stage.ai_state().lower(),
            "silence_ticks": silence_ticks,
            "silence_human": format_ticks_to_human(silence_ticks),
            "uptime_ticks": uptime_ticks,
            "uptime_human": format_ticks_to_human(uptime_ticks),
            "is_sleeping": c.IS_SLEEPING,
            "mic_action": " 聆聽中" if c.is_user_listening else c.current_mic_action_str,
            "is_mic_enabled": c.IS_MIC_ENABLED,
            "mic_volume": 0.0 if c.IS_SLEEPING else c.CURRENT_MIC_VOL_PERCENT / 100.0,
            "model_name": "Gemini Live API (WebSocket)" if c.IS_LIVE_MODE_ACTIVE else "Gemini 3.5 Flash-Lite (REST)",
            "api_calls": c.TOTAL_API_CALLS,
            "api_energy": max(5.0, round(100.0 - (c.TOTAL_API_CALLS * 0.4), 1)),
            "api_stress": stress_info,
            "vision_change": "high" if yt.IS_YT_COMPANION_ACTIVE else c.CURRENT_VISION_CHANGE_LEVEL,
            "vision_change_score": 85 if yt.IS_YT_COMPANION_ACTIVE else c.CURRENT_VISION_CHANGE_SCORE,
            "vts_expression": getattr(self.vts, "current_expression", "自然") if self.vts else "未連線",
            "screen_context": f"正在觀看 YouTube 影片《{yt.CURRENT_YT_TITLE[:25]}》" if yt.IS_YT_COMPANION_ACTIVE else c.current_screen_context,
            "vision_history": list(c.VISION_HISTORY_STREAM),
            "last_vision_time": time.time() if yt.IS_YT_COMPANION_ACTIVE else c.LAST_VISION_LOOK_TIME,
            "audio_context": c.current_system_audio_context,
            "audio_perception": self.get_audio_perception_summary(),
            "timer_sensor": c.live_timer_hub.get_sensor_summary()
        }

    async def set_mic(self, enable=None):
        target = not self.core.IS_MIC_ENABLED if enable is None else bool(enable)
        return await self.set_switch("IS_MIC_ENABLED", target)

    async def trigger_expression(self, expr):
        if self.vts:
            await self.core.set_vts_expression(self.vts, expr)

    def get_last_vision_image(self):
        c = self.core
        #  若 YouTube 伴看活躍中，優先返回 YouTube 視窗高畫質截圖
        if c.yt_comp.IS_YT_COMPANION_ACTIVE and c.yt_comp.LATEST_YT_FRAME_BYTES:
            return c.yt_comp.LATEST_YT_FRAME_BYTES
        if c.LATEST_HD_SCREEN_BYTES:
            return c.LATEST_HD_SCREEN_BYTES
        cache = c.latest_screen_cache
        if cache and isinstance(cache, list) and len(cache) > 0:
            return cache[0][1]
        return None

    def restart(self):
        log_print("🔄 [系統] 收到 Web 控制台重啟指令，正在重新啟動 7L 系統...")
        self.core.shutdown_7l(restart=True)

    def shutdown(self):
        log_print("👋 [系統] 收到 Web 控制台關機指令，正在安全退出 7L 系統...")
        self.core.shutdown_7l()

    # 後台專屬（主派發器沒有，或後台要等結果顯示）；其他工具一律走主程式同一個派發器
    _BRIDGE_ONLY_TOOLS = {"set_sleep_mode", "open_browser", "trigger_vts_expression",
                          "execute_local_python_code", "generate_ai_image", "draw_illustration"}

    async def execute_tool_manually(self, tool_name: str, args: dict):
        """後台手動呼叫工具。以前這裡另寫一份派發器：少 13 個工具（曲庫清單、點播看片、知識庫…），
        行為也跟主程式不同步（收鋼琴的 force 要改兩處）。現在除了後台專屬的，都走 execute_tool_dispatch。"""
        c = self.core
        args = dict(args or {})
        log_print(f"🛠️ [老爸手動調用] 正在執行工具: {tool_name}，參數: {args}")
        if tool_name == "set_sleep_mode":
            enable = bool(args.get("enable", False))
            await c.set_sleep_mode(enable)
            return f"已切換為{'深層休眠 (0 API)' if enable else '全速運作喚醒狀態'}"
        elif tool_name == "open_browser":
            url = args.get("url", "https://www.google.com")
            if not url.startswith("http"):
                url = "https://" + url
            import webbrowser
            webbrowser.open(url)
            return f"已在預設瀏覽器中開啟網頁：{url}"
        elif tool_name == "trigger_vts_expression":
            # 主派發器這個工具只回表情標籤、由說話流程去做；後台要直接做
            expr = args.get("expression_name", "自然")
            if self.vts:
                await c.set_vts_expression(self.vts, expr)
            return f"已觸發 VTS 表情：{expr}"
        elif tool_name == "execute_local_python_code":
            res = await c.execute_local_python_code(args.get("code_string", ""))
            return res or "Python 程式碼執行完成"
        elif tool_name in ("generate_ai_image", "draw_illustration"):
            p = args.get("prompt", "")
            res = await c.generate_ai_image(p)
            return res or f"已生成 AI 插畫：「{p}」"

        import services.web_dashboard as _wd
        if tool_name.split(".")[-1] not in {t["name"].split(".")[-1] for t in _wd.full_tools_catalog()}:
            raise ValueError(f"未知的工具名稱: {tool_name}")   # 主派發器遇到不認得的會安靜略過，這裡先擋
        if tool_name.split(".")[-1] == "stop_virtual_piano":
            args["force"] = True   # 後台按的就是老爸本人，不受「剛拿出 3.5 秒」防護擋
        try:
            from core.identity import get_owner_name
            owner = get_owner_name()
        except Exception:
            owner = "老爸"
        res = await c.execute_tool_dispatch(tool_name, args, caller_target="dad", caller_user=owner)
        return _TAG_RE.sub("", str(res or "")).strip() or f"已執行 {tool_name}"

    # 後台「系統開關」頁照這個順序、分組顯示（老爸 2026-10-31：後台整理一下；名字、說明寫白話，說清楚現在真的做什麼）
    _SWITCH_GROUPS = {
        "voice": "聲音與直播",
        "vision": "看螢幕與視線",
        "idle": "閒著的時候",
        "piano": "鋼琴",
        "system": "睡覺與模式",
    }

    def get_switches(self):
        c = self.core
        items = [
            ("IS_MIC_ENABLED", "voice", "mic", "麥克風（聽老爸說話）",
             "聽麥克風、把老爸說的話轉成文字。關掉後她聽不到，只能在對話框打字跟她說。",
             c.IS_MIC_ENABLED),
            ("IS_STREAM_CHAT_ENABLED", "voice", "broadcast", "理直播聊天室",
             "直播連上時會自動打開，觀眾的留言會排隊讓她回。關掉就先不理聊天室；直播斷線時這裡也會自己變回關。",
             getattr(c.tk_listener, "IS_STREAMING", False)),
            ("IS_PERIPHERAL_VISION_ENABLED", "vision", "eye", "看老爸的螢幕（餘光視覺）",
             "每隔一陣子看一次螢幕，知道老爸在做什麼、畫面有什麼變化，聊天時拿來當話題。"
             "她「想看哪裡」也靠這個：Live 看螢幕挑她想看的東西（視線副腦）。關掉時她看哪裡只照簡單規則。",
             c.IS_PERIPHERAL_VISION_ENABLED),
            ("IS_FACE_TRACKING_ENABLED", "vision", "user", "眼睛和頭會動",
             "眼睛看螢幕上的東西（滑鼠、正在用的視窗、剛有變化的地方、鏡頭），頭跟著轉，還有呼吸和眨眼。關掉後臉不會自己動。",
             c.IS_FACE_TRACKING_ENABLED),
            ("IS_GAZE_CURSOR_ENABLED", "vision", "eye", "顯示她在看哪裡",
             "在她現在看的位置放一個桃紅色箭頭（點不到；截圖、直播畫面都看不到），用來確認她的視線。",
             c.IS_GAZE_CURSOR_ENABLED),
            ("IS_YT_WATCHER_ENABLED", "vision", "video", "陪看 YouTube",
             "螢幕上有 YouTube 在播時，每秒看一張影片畫面、同時聽影片聲音，跟老爸一起看、一起聊。",
             c.yt_comp.IS_YT_WATCHER_ENABLED),
            ("IS_PROACTIVE_SPEAK_ENABLED", "idle", "chat", "自己找話聊",
             "安靜大約 3 分鐘（彈琴時 10 分鐘），她會看畫面和剛聊過的事自己開話題講 1～2 句，講完休息 7 分鐘。關掉就只有人問才回。",
             c.IS_PROACTIVE_SPEAK_ENABLED),
            ("IS_AUTO_WANDER_ENABLED", "idle", "walk", "閒著時走來走去",
             "沒事超過 60 秒，每 60 秒在畫面上換個位置、換個姿勢。",
             c.IS_AUTO_WANDER_ENABLED),
            ("IS_AUTO_PIANO_ENABLED", "piano", "piano", "閒著時自己彈琴",
             "沒事、房間也沒聲音超過 60 秒，每 5 分鐘自己坐到鋼琴前挑一首彈。",
             c.IS_AUTO_PIANO_ENABLED),
            ("IS_PIANO_AUTO_RADIO_MODE", "piano", "radio", "彈完自動接下一首",
             "一首彈完、又沒有人點歌時，自動從曲庫隨機挑下一首一直彈下去。",
             getattr(c.pe, "IS_PIANO_AUTO_RADIO_MODE", False)),
            ("IS_SLEEPING", "system", "moon", "睡覺（不花 API）",
             "閉上眼睛睡覺：不看螢幕、不在背景想事情、計時器也暫停，完全不呼叫 AI。叫她起床或關掉這個就醒來。",
             c.IS_SLEEPING),
            ("MODE_TOGGLE", "system", "user", "陪伴模式（要重開才完整生效）",
             "開著：同時陪老爸和直播聊天室。關掉：實況主模式，只理聊天室。切換後按上面的「重開」。",
             self.run_mode == "companion"),
        ]
        return [{"key": key, "name": name, "category": cat, "category_name": self._SWITCH_GROUPS[cat],
                 "description": desc, "value": bool(val), "icon": icon}
                for key, cat, icon, name, desc, val in items]

    async def set_switch(self, key: str, value=None, sync_cloud=True):
        c = self.core
        if key in TRANSIENT_SWITCHES:
            sync_cloud = False   # 睡著、直播連線是當下的狀態，不是設定：不存、開機也不還原
        current_map = {
            "IS_AUTO_PIANO_ENABLED": c.IS_AUTO_PIANO_ENABLED,
            "IS_PIANO_AUTO_RADIO_MODE": getattr(c.pe, "IS_PIANO_AUTO_RADIO_MODE", False),
            "IS_AUTO_WANDER_ENABLED": c.IS_AUTO_WANDER_ENABLED,
            "IS_PROACTIVE_SPEAK_ENABLED": c.IS_PROACTIVE_SPEAK_ENABLED,
            "IS_PERIPHERAL_VISION_ENABLED": c.IS_PERIPHERAL_VISION_ENABLED,
            "IS_FACE_TRACKING_ENABLED": c.IS_FACE_TRACKING_ENABLED,
            "IS_GAZE_CURSOR_ENABLED": c.IS_GAZE_CURSOR_ENABLED,
            "IS_MIC_ENABLED": c.IS_MIC_ENABLED,
            "IS_STREAM_CHAT_ENABLED": getattr(c.tk_listener, "IS_STREAMING", False),
            "IS_SLEEPING": c.IS_SLEEPING,
            "IS_YT_WATCHER_ENABLED": c.yt_comp.IS_YT_WATCHER_ENABLED,
            "MODE_TOGGLE": self.run_mode == "companion"
        }

        target_val = not current_map.get(key, False) if value is None else bool(value)

        if key == "IS_AUTO_PIANO_ENABLED":
            c.IS_AUTO_PIANO_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 閒置自主彈琴已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_PIANO_AUTO_RADIO_MODE":
            c.pe.IS_PIANO_AUTO_RADIO_MODE = target_val
            log_print(f"🎛️ [系統開關] 鋼琴無限隨機電台已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_AUTO_WANDER_ENABLED":
            c.IS_AUTO_WANDER_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 閒置自主漫遊已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_PROACTIVE_SPEAK_ENABLED":
            c.IS_PROACTIVE_SPEAK_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 視覺陪伴主動搭話已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_PERIPHERAL_VISION_ENABLED":
            c.IS_PERIPHERAL_VISION_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 餘光視覺感知已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_FACE_TRACKING_ENABLED":
            c.IS_FACE_TRACKING_ENABLED = target_val
            log_print(f"🎛️ [系統開關] AI 視線與頭部追蹤已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_GAZE_CURSOR_ENABLED":
            c.IS_GAZE_CURSOR_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 顯示視線位置已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_MIC_ENABLED":
            c.IS_MIC_ENABLED = target_val
            log_print(f"🎛️ [系統開關] 麥克風收音已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_STREAM_CHAT_ENABLED":
            c.tk_listener.IS_STREAMING = target_val
            log_print(f"🎛️ [系統開關] 直播彈幕即時互動已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_SLEEPING":
            await c.set_sleep_mode(target_val)
            target_val = c.IS_SLEEPING
            log_print(f"🎛️ [系統開關] 深層休眠模式已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "IS_YT_WATCHER_ENABLED":
            c.yt_comp.IS_YT_WATCHER_ENABLED = target_val
            log_print(f"🎛️ [系統開關] YouTube 即時伴看已{'🟢 開啟' if target_val else '🔴 關閉'}")
        elif key == "MODE_TOGGLE":
            from core.settings import apply_mode
            new_mode = apply_mode("companion" if target_val else "vtuber")
            self.run_mode = new_mode
            log_print(f"🎛️ [系統開關] 運行模式已切換為 {new_mode} (已即時生效，徹底生效請點擊重啟大腦)")

        if sync_cloud:
            try:
                from core.memory import get_cloud_knowledge, save_cloud_knowledge
                kn = await get_cloud_knowledge()
                if "system_switches" not in kn:
                    kn["system_switches"] = {}
                kn["system_switches"][key] = target_val
                await save_cloud_knowledge(kn)
                log_print(f"☁️ [全域開關同步] {key} = {target_val} 已儲存至雲端大腦")
            except Exception as e:
                log_print(f"⚠️ [全域開關同步失敗]: {e}")

        return target_val

    async def restore_switches_from_cloud(self):
        """開機把雲端存的全域開關套回來（MODE_TOGGLE 由 main() 更早處理，這裡跳過）。"""
        try:
            from core.memory import get_cloud_knowledge
            kn = await get_cloud_knowledge()
            switches = kn.get("system_switches", {})
            if switches:
                log_print("☁️ [雲端還原] 正在載入全域系統開關...")
                for k, v in switches.items():
                    if k != "MODE_TOGGLE" and k not in TRANSIENT_SWITCHES:
                        await self.set_switch(k, v, sync_cloud=False)
                log_print("✅ [雲端還原] 全域系統開關載入完成")
        except Exception as e:
            log_print(f"⚠️ [雲端開關載入失敗]: {e}")
