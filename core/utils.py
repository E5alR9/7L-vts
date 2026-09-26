import shutil
import time
from datetime import datetime

current_system_notification = ""
notification_expire_time = 0.0

# ⏱️ 7L 統一神經時間心跳中樞 (Unified Tick Engine: 1 Tick = 1 秒)
SYSTEM_BOOT_TIME = time.time()
LAST_INTERACTION_TIME = time.time()

def record_interaction_tick():
    """當老爸說話、打字、麥克風捕捉到人聲、TikTok 彈幕或 7L 開口發言時調用，重設沉默心跳為 0"""
    global LAST_INTERACTION_TIME
    LAST_INTERACTION_TIME = time.time()

def get_uptime_ticks() -> int:
    """獲取 7L 從本次啟動以來的累積生存總心跳數 (Ticks)"""
    return max(0, int(time.time() - SYSTEM_BOOT_TIME))

def get_silence_ticks() -> int:
    """獲取現場當前安靜 / 無對話累積的心跳數 (Ticks，1 Tick = 1 秒)"""
    return max(0, int(time.time() - LAST_INTERACTION_TIME))

def format_ticks_to_human(ticks: int) -> str:
    """將 ticks 轉換為直觀易讀的時間描述"""
    if ticks < 60:
        return f"{ticks} 秒"
    elif ticks < 3600:
        m = ticks // 60
        s = ticks % 60
        return f"{m} 分 {s} 秒" if s > 0 else f"{m} 分鐘"
    else:
        h = ticks // 3600
        m = (ticks % 3600) // 60
        return f"{h} 小時 {m} 分鐘" if m > 0 else f"{h} 小時"

def log_print(msg: str):
    """清除動態狀態列並乾淨輸出單行日誌，避免任何換行溢出或殘留空格"""
    term_cols = shutil.get_terminal_size((80, 20)).columns
    blank = " " * max(1, min(term_cols - 1, 79))
    print(f"\r\033[2K\r{blank}\r{msg}", flush=True)

def sys_notify(msg, duration=4.0):
    global current_system_notification, notification_expire_time
    clean_msg = str(msg).replace('\n', ' ').replace('\r', ' ')
    current_system_notification = clean_msg
    add_time = max(3.0, min(8.0, len(clean_msg) * 0.15))
    notification_expire_time = time.time() + add_time

def get_current_time_string(include_ticks: bool = True):
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        now = datetime.now()
        
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    base_time = f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]} {now.strftime('%H:%M')}"
    if not include_ticks:
        return base_time
    
    silence = get_silence_ticks()
    silence_human = format_ticks_to_human(silence)
    uptime = get_uptime_ticks()
    return f"{base_time} (生命刻度: 第 {uptime} Ticks | 現場沉默: {silence} Ticks / 約 {silence_human})"

def get_unified_time_prompt() -> str:
    """建構統一神經時間感知 Prompt 注入 7L 大腦提示詞"""
    time_str = get_current_time_string(include_ticks=True)
    silence = get_silence_ticks()
    silence_human = format_ticks_to_human(silence)
    
    return f"""時間：{time_str}
【⏳ 7L 統一神經時間感知 (Unified Tick Clock)】：
- 妳以「Tick（心跳秒數）」作為主觀時間度量衡，1 Tick 相當於 1 秒。
- 當前現場已安靜了 {silence} Ticks（約 {silence_human}）：
  * 剛說過話（< 60 Ticks / 1分鐘內）：屬於連貫的即時對話，延續當前話題與互動情緒。
  * 專注安靜（60 ~ 600 Ticks / 1~10分鐘）：老爸正專心操作電腦，若老爸開口，自然接話；若自主陪伴，保持安靜守護。
  * 長期安靜（> 600 Ticks / 10分鐘以上）：老爸已專注很久，開口或自主搭話時可自然帶有時間流逝感，表現出對時間陪伴的真實感知。"""
