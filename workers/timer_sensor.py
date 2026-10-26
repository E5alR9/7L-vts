# -*- coding: utf-8 -*-
"""計時感測：計時器、鬧鐘到點時讓 7L 開口提醒（排進說話佇列、寫記憶、更新字幕）。

主程式的狀態經 host.<名稱> 即時讀寫（host＝主程式模組，主程式 import 本檔後 bind()）。
用到的名稱列在 HOST_ATTRS，tests/test_workers_host.py 核對主程式真的都有定義。
"""
import asyncio
import time

import services.web_dashboard as web_dash
from core.live_timer_sensor import live_timer_hub
from core.memory import append_to_unified_memory, record_bot_message
from core.prompts import PromptTemplateEngine
from core.utils import get_current_time_string, log_print, log_swallowed

HOST_ATTRS = (
    "LATEST_SYSTEM_MUSIC_INFO",
    "execute_actions",
    "speech_queue",
    "touch_interaction",
    "update_subtitle",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


async def live_timer_sensor_worker(vts, input_queue):
    """ API Live 持續時間感測哨兵協程：
    - 以 1 秒 (1 Tick) 精度全時感測倒數時間與老爸當前狀態
    - 時間到達時自動喚醒主力多模態大腦 (Gemini 3.8 / 3.1 Flash) 生成專屬生動提醒並主動開口發言
    """
    log_print("⏱️ [API Live 時間感測哨兵] 協程已就緒，開始全時任務與倒數感測...")
    while True:
        try:
            await asyncio.sleep(1.0)
            now = time.time()
            
            # 遍歷所有進行中的定時感測任務
            for tid, task in list(live_timer_hub.timers.items()):
                if task.get("status") != "sensing":
                    continue
                    
                rem = task["target_time"] - now
                if rem <= 0:
                    task["status"] = "triggered"
                    task_msg = task.get("message", "提醒時間到了")
                    # ⚠️ 定時人不一定是老爸：記錄誰寫誰，未知就中性，絕不預設老爸
                    caller = task.get("caller_user") or ""
                    log_print(f"⏰ [API Live 定時感測到期] 任務 {tid}（{task_msg}）到期！正在呼叫主力大腦生成自然提醒口語...")
                    
                    del live_timer_hub.timers[tid]
                    
                    # 取得當前環境多模態上下文
                    curr_fg_title = ""
                    curr_fg_app = ""
                    try:
                        from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
                        fg_info = os_desktop_sensor.get_foreground_window()
                        curr_fg_title = fg_info.get("window_title", "").strip()
                        curr_fg_app = fg_info.get("app_label", "").strip()
                    except Exception:
                        log_swallowed()
                        
                    fg_hint = f"（老爸當前正在使用視窗：{curr_fg_title} - {curr_fg_app}）" if curr_fg_title else ""
                    music_hint = f"（電腦音樂：{host.LATEST_SYSTEM_MUSIC_INFO}）" if host.LATEST_SYSTEM_MUSIC_INFO else ""
                    
                    reminder_messages = [
                        {"role": "system", "content": PromptTemplateEngine.HARD_TECHNICAL_RULES},
                        {"role": "user", "content": f"""時間：{get_current_time_string()}
【 API Live 定時感測到期提醒】：
{caller or '你'}剛才交代的時間提醒到了！
- 預定提醒事項：『{task_msg}』
- 當前現場環境：{fg_hint} {music_hint}

請妳依循妳的人設性格，主動開口提醒{caller or '你'}時間到了！（直接給出一兩句自然生動的發言，可附帶 [EXPRESSION: 瞇眼/笑/WINK] 表情與 [SPEED:...] 語調標籤，請務必發出聲音提醒！）"""}
                    ]
                    
                    try:
                        #  背景純文字（定時提醒口語）走 Groq，不佔 Gemini 額度；失敗直接走下方固定備援句
                        from core.groq_router import groq_chat
                        g_resp = await groq_chat(reminder_messages, temperature=0.85, max_tokens=220, timeout=6.0)
                        raw_reply = (g_resp.text if g_resp and g_resp.text else "").strip()
                        if not raw_reply:
                            raise RuntimeError("Groq 無回應，改用固定備援提醒句")
                        spoken = await host.execute_actions(vts, raw_reply, input_queue, caller_target="dad", caller_user=caller)
                        clean_spoken = spoken.strip(" *'\"-.,!?。，！？\n\r") if spoken else ""
                        
                        if not clean_spoken:
                            if caller:
                                clean_spoken = f"{caller}～剛才說好的「{task_msg}」時間到了喔！快起來休息一下～"
                            else:
                                clean_spoken = f"你～剛才說好的「{task_msg}」時間到了喔！"
                            
                        await asyncio.to_thread(host.update_subtitle, clean_spoken)
                        record_bot_message(clean_spoken)
                        log_print(f"💬 7L (定時感測主動提醒): {clean_spoken}")
                        await host.speech_queue.put({"text": clean_spoken, "target": "dad", "raw_text": raw_reply})
                        host.touch_interaction()
                        
                        append_to_unified_memory(speaker="7L", target=caller, content=clean_spoken, role="assistant", source="tts")
                        try:
                            web_dash.broadcast_event("timer_triggered", {
                                "task_id": tid,
                                "message": task_msg,
                                "spoken": clean_spoken
                            })
                        except Exception:
                            log_swallowed()
                    except Exception as err:
                        log_print(f"❌ [定時感測喚醒模型發言異常]: {err}")
                        if caller:
                            fallback_msg = f"{caller}！時間到囉～剛才說好的「{task_msg}」要記得喔！"
                        else:
                            fallback_msg = f"時間到囉～剛才說好的「{task_msg}」要記得喔！"
                        await asyncio.to_thread(host.update_subtitle, fallback_msg)
                        await host.speech_queue.put({"text": fallback_msg, "target": "dad"})
                        host.touch_interaction()
        except Exception as e:
            log_print(f"⚠️ [API Live 時間感測協程異常]: {e}")
            await asyncio.sleep(1.0)
