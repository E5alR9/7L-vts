import os
import shutil
import sys
import time
from datetime import datetime

current_system_notification = ""
notification_expire_time = 0.0


def speech_allowed(private: bool) -> bool:
    """這句回話是否允許『播出聲音』（直播對象控制的總閘門）。

    private=True → 操作者私訊管道的回話（麥克風 / 鍵盤 / Web 控制台 / 文字檔 /
    定時提醒 / 喚醒應答）：**預設不播出** —— 觀眾不該聽到 7L 對著空氣跟幕後的
    操作者講話。回話仍會：寫入記憶、列印主控台、廣播到控制台事件流、
    先前已套用的表情/計時器照舊生效（這裡只攔「播放」這一步）。

    private=False → 觀眾看得到的管道（TikTok 聊天室含老爸的公開帳號、
    proactive 主動發言、自主彈琴開場）一律播出。

    要恢復舊行為（對操作者也開口）：設環境變數 OPERATOR_SPEECH=1
    """
    if not private:
        return True
    return (os.getenv("OPERATOR_SPEECH", "0") or "0").strip().lower() in ("1", "true", "yes")


def operator_input_enabled() -> bool:
    """操作者輸入通道（麥克風 STT / 鍵盤 / chat_input.txt / Web 打字）是否啟用。

    預設**關閉**：直播輸入只接受 Twitch / YouTube Live 聊天室的觀眾留言。
    要恢復操作者輸入：.env 設 OPERATOR_INPUT=1。
    VTuber 模式（MODE=vtuber）強制關閉：只與觀眾互動，不理電腦前的人。
    """
    try:
        from core.identity import is_vtuber
        if is_vtuber():
            return False
    except Exception:
        pass
    return (os.getenv("OPERATOR_INPUT", "0") or "0").strip().lower() in ("1", "true", "yes")

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

# 吞錯節流表：(呼叫端檔案, 行號) -> [上次記錄時間, 期間被壓下的次數]
_SWALLOWED = {}
SWALLOW_LOG_INTERVAL = 60.0

def log_swallowed(where: str = "", interval: float = SWALLOW_LOG_INTERVAL):
    """取代 except Exception: pass —— 在 except 區塊裡呼叫，例外照吞、控制流程不變，
    但同一位置（呼叫端 檔名:行號）每 interval 秒最多記一行，期間壓下的次數併在下一行報。
    本身絕不拋錯。"""
    try:
        exc = sys.exc_info()[1]
        f = sys._getframe(1)
        key = (f.f_code.co_filename, f.f_lineno)
        now = time.monotonic()
        rec = _SWALLOWED.get(key)
        if rec is not None and now - rec[0] < interval:
            rec[1] += 1
            return
        suppressed = rec[1] if rec else 0
        _SWALLOWED[key] = [now, 0]
        name = where or f.f_code.co_name
        extra = f"（前 {interval:.0f}s 另壓下 {suppressed} 次）" if suppressed else ""
        log_print(f"🔇 [吞錯] {name} @ {os.path.basename(key[0])}:{key[1]} "
                  f"{type(exc).__name__ if exc else '?'}: {str(exc)[:200]}{extra}")
    except Exception:
        pass


# 背景任務：asyncio 只對任務留弱參考，沒人存的任務可能跑到一半被回收；
# 例外也沒人 await，只會在回收時印一句 never retrieved（2026-10-25 實機：點曲任務無聲消失）
_BG_TASKS = set()
_BG_FAIL_LOG = {}   # 協程名 -> [上次記錄時間, 期間壓下次數]


def spawn(coro, label: str = ""):
    """丟背景跑的唯一出口（取代 asyncio.create_task(...) 不存結果）：留強參考到跑完，出錯記一筆日誌。"""
    import asyncio
    task = asyncio.create_task(coro)
    task._7l_label = label or getattr(coro, "__qualname__", "") or repr(coro)[:60]
    _BG_TASKS.add(task)
    task.add_done_callback(_bg_done)
    return task


def _bg_done(task):
    _BG_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    try:
        import traceback
        label = getattr(task, "_7l_label", "") or task.get_name()
        key = getattr(task.get_coro(), "__qualname__", label)
        now = time.monotonic()
        rec = _BG_FAIL_LOG.get(key)
        if rec is not None and now - rec[0] < SWALLOW_LOG_INTERVAL:
            rec[1] += 1
            return
        suppressed = rec[1] if rec else 0
        _BG_FAIL_LOG[key] = [now, 0]
        extra = f"（前 {SWALLOW_LOG_INTERVAL:.0f}s 另壓下 {suppressed} 次）" if suppressed else ""
        log_print(f"⚠️ [背景任務失敗] {label}: {type(exc).__name__}: {str(exc)[:200]}{extra}\n"
                  + "".join(traceback.format_exception(exc))[-1500:])
    except Exception:
        pass

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
  * 長期安靜（> 600 Ticks / 10分鐘以上）：老爸已專注很久，開口或自主搭話時可自然帶有時間流逝感（例如：「老爸忙完啦？」、「剛剛專注了好久呢～」），表現出對時間陪伴的真實感知。"""


_S2TWP_CONVERTER = None


def to_tw(text: str) -> str:
    """簡轉繁（台灣用語）。OpenCC 建構要載字典檔，整個程式只建一次重複用；轉不了就原樣回傳。"""
    global _S2TWP_CONVERTER
    if not text:
        return text
    try:
        if _S2TWP_CONVERTER is None:
            import opencc
            _S2TWP_CONVERTER = opencc.OpenCC('s2twp')
        return _S2TWP_CONVERTER.convert(text)
    except Exception:
        return text
