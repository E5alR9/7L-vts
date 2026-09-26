import asyncio
import time
import re
from typing import Dict, Any, List, Optional, Tuple
from core.utils import log_print, get_current_time_string, get_uptime_ticks, format_ticks_to_human

CN_NUM = {
    '零': 0, '一': 1, '二': 2, '兩': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10
}

class LiveTimerSensorHub:
    """⏱️ 7L API Live 持續時間感測哨兵中樞 (Live Timer & Countdown Sensor)
    - 以 1 Tick (1 秒) 精度持續感測倒數時間與環境動態
    - 到期後自動呼叫 Gemini 3.8 / 3.1 Flash / 主力多模態模型自主發言提醒
    """
    def __init__(self):
        self.timers: Dict[str, Dict[str, Any]] = {}
        self._counter: int = 0

    def add_timer(self, seconds: int, message: str = "", source: str = "老爸口語/指令", caller_user: str = "老爸") -> Dict[str, Any]:
        """新增一個定時感測任務 (單位: 秒數 / Ticks)"""
        self._counter += 1
        task_id = f"timer_{int(time.time())}_{self._counter}"
        now = time.time()
        
        clean_msg = message.strip() if message else "提醒老爸時間到了"
        clean_msg = re.sub(r'^(?:叫我|提醒我|叫醒我|跟我說|通知我|喊我)', '', clean_msg).strip()
        if not clean_msg:
            clean_msg = "時間到了，來看看老爸"

        timer_item = {
            "task_id": task_id,
            "created_at": now,
            "created_tick": get_uptime_ticks(),
            "target_seconds": max(1, int(seconds)),
            "target_time": now + max(1, int(seconds)),
            "message": clean_msg,
            "source": source,
            "caller_user": caller_user,
            "status": "sensing"  # sensing / triggered / cancelled
        }
        self.timers[task_id] = timer_item
        log_print(f"⏱️ [API Live 定時感測啟動] 註冊任務 #{self._counter}: {seconds} Ticks ({format_ticks_to_human(seconds)}) ➔ 「{clean_msg}」")
        return timer_item

    def cancel_timer(self, task_id: str) -> bool:
        """取消指定定時感測任務"""
        if task_id in self.timers:
            self.timers[task_id]["status"] = "cancelled"
            log_print(f"⏱️ [API Live 定時感測] 已取消任務 {task_id}")
            del self.timers[task_id]
            return True
        return False

    def clear_all(self):
        """清空所有感測任務"""
        self.timers.clear()

    def get_active_timers(self) -> List[Dict[str, Any]]:
        """獲取所有進行中感測任務的即時狀態清單"""
        now = time.time()
        active = []
        for tid, t in list(self.timers.items()):
            if t["status"] != "sensing":
                continue
            rem = max(0, int(t["target_time"] - now))
            total = t["target_seconds"]
            pct = max(0, min(100, int(((total - rem) / max(1, total)) * 100)))
            active.append({
                "task_id": tid,
                "remaining_ticks": rem,
                "remaining_human": format_ticks_to_human(rem),
                "total_ticks": total,
                "total_human": format_ticks_to_human(total),
                "progress_pct": pct,
                "message": t["message"],
                "caller_user": t["caller_user"],
                "source": t["source"]
            })
        active.sort(key=lambda x: x["remaining_ticks"])
        return active

    def get_sensor_summary(self) -> Dict[str, Any]:
        """提供給 Web 儀表板與 Telemetry 廣播的即時感測摘要"""
        active = self.get_active_timers()
        if not active:
            return {
                "has_active_timer": False,
                "active_count": 0,
                "status_text": "待命中",
                "nearest_timer": None
            }
        
        nearest = active[0]
        summary_str = f"剩餘 {nearest['remaining_ticks']} tick ({nearest['remaining_human']}) ➔ {nearest['message']}"
        return {
            "has_active_timer": True,
            "active_count": len(active),
            "status_text": summary_str,
            "nearest_timer": nearest,
            "timers": active
        }

    @staticmethod
    def detect_timer_intent(text: str) -> Optional[Tuple[int, str]]:
        """從使用者語音或文字中智慧辨識定時與提醒意圖
        支援範例：
        - 10分鐘後叫我
        - 半小時後叫我寫程式
        - 300秒後提醒我喝水
        - 5分鐘後叫我吃藥
        - 120 tick後叫我
        - 過五分鐘後跟我說
        """
        clean_text = text.strip()
        if not clean_text:
            return None

        # 模式 1: 明確時間 + 後 + 叫我/提醒我
        pattern = r'(?:(?:在|過|等|還有)?\s*([0-9一兩二三四五六七八九十百]+|半)\s*(?:個)?\s*(小時半|小時|鐘頭|分鐘|分|秒鐘|秒|ticks?|tick)\s*(?:之)?後?\s*(?:叫我|提醒我|叫醒我|通知我|跟我說|喊我|敲我)\s*(.*))'
        m = re.search(pattern, clean_text, re.IGNORECASE)
        if m:
            num_str = m.group(1).strip()
            unit = m.group(2).lower()
            extra = m.group(3).strip()
            
            if num_str == '半':
                val = 0.5
            elif num_str.isdigit():
                val = float(num_str)
            else:
                val = float(CN_NUM.get(num_str, 1))

            sec = 0
            if '小時半' in unit:
                sec = int(val * 3600 + 1800)
            elif '小時' in unit or '鐘頭' in unit:
                sec = int(val * 3600)
            elif '分' in unit:
                sec = int(val * 60)
            elif '秒' in unit or 'tick' in unit:
                sec = int(val)

            # 清理 extra 作為提醒內容
            reminder_action = extra if extra else "時間到了，叫老爸"
            return sec, reminder_action

        # 模式 2: 定時/計時/鬧鐘 [TIMER: 300|喝水] 或 倒數 X 秒/分
        tag_m = re.search(r'\[(?:TIMER|SET_TIMER|ALARM|鬧鐘|計時器)[：:]\s*([0-9]+)\s*\|?\s*([^\]]*)\]', clean_text, re.IGNORECASE)
        if tag_m:
            sec = int(tag_m.group(1))
            msg = tag_m.group(2).strip() or "時間到了"
            return sec, msg

        return None

# 全域單例
live_timer_hub = LiveTimerSensorHub()
