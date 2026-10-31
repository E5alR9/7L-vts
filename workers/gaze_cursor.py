# -*- coding: utf-8 -*-
"""視線游標（老爸 2026-10-31：用一個開關顯示她看的位置，用成滑鼠圖標）。

她的視線不是螢幕座標，是眼睛的角度（vc.gaze_eye_x／y，-1～1，臉部追蹤每一格寫進去）。
看滑鼠時眼睛角度是從滑鼠位置換算的（以 VTS 視窗中心為 0 點），這裡照同一套換算反推回螢幕上的點，
畫一個桃紅色的箭頭游標；看滑鼠時它會疊在真的滑鼠上，彈琴時往下看琴鍵、想事情時往左上飄。

游標是一個置頂、點不到（滑鼠穿透）的小視窗，不會擋到操作；也設成不被截圖：
她自己的餘光截圖、OBS 擷取都看不到它，觀眾也看不到。
主程式的狀態經 host.<名稱> 即時讀（host＝主程式模組，主程式 import 本檔後 bind()）。
"""
import asyncio
import threading

import pyautogui

import services.vts_client as vc
from core.utils import log_print, log_swallowed

HOST_ATTRS = (
    "IS_GAZE_CURSOR_ENABLED",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


# 跟 workers/face_tracking.py 看滑鼠那段同一套比例：look = 偏移 × (28, -20)，眼睛 = look ÷ (20, 15)
LOOK_X_PER_SCREEN, LOOK_Y_PER_SCREEN = 28.0, -20.0
EYE_X_DEG, EYE_Y_DEG = 20.0, 15.0


def gaze_screen_point(eye_x: float, eye_y: float, cx: float, cy: float, sw: int, sh: int) -> tuple:
    """眼睛角度 → 螢幕座標（像素，夾在螢幕內）。cx、cy：VTS 視窗中心佔螢幕的比例。"""
    nx = eye_x * EYE_X_DEG / LOOK_X_PER_SCREEN
    ny = eye_y * EYE_Y_DEG / LOOK_Y_PER_SCREEN
    x = int(round((nx + cx) * sw))
    y = int(round((ny + cy) * sh))
    return max(0, min(sw - 1, x)), max(0, min(sh - 1, y))


# 箭頭游標（尖端在 (1, 1)）
_ARROW = [1, 1, 1, 22, 6, 17, 10, 26, 14, 24, 10, 16, 17, 16]
_KEY = "#010203"   # 透明色

_STATE = {"center": (0.5, 0.5), "screen": (1920, 1080), "stop": None, "thread": None}


def _overlay_thread(stop: threading.Event) -> None:
    import ctypes
    import tkinter as tk
    user32 = ctypes.windll.user32
    prev_fg = user32.GetForegroundWindow()   # 建立視窗會搶走焦點：記下來，弄好再還回去
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", _KEY)
    root.configure(bg=_KEY)
    cv = tk.Canvas(root, width=28, height=30, bg=_KEY, highlightthickness=0)
    cv.pack()
    cv.create_polygon(*_ARROW, fill="#ff4fa3", outline="#ffffff", width=2)
    root.geometry("28x30+0+0")
    root.update_idletasks()
    try:
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = -20, 0x80000, 0x20, 0x80
        WS_EX_NOACTIVATE = 0x08000000   # 永遠不拿焦點（2026-10-31 實機：一打開游標，前景視窗就變成它，老爸打字會被打斷）
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        user32.SetWindowDisplayAffinity(hwnd, 0x11)   # WDA_EXCLUDEFROMCAPTURE：截圖、直播擷取都看不到
        if prev_fg and user32.GetForegroundWindow() != prev_fg:
            user32.SetForegroundWindow(prev_fg)
    except Exception:
        log_swallowed()

    def tick():
        if stop.is_set():
            root.destroy()
            return
        try:
            cx, cy = _STATE["center"]
            sw, sh = _STATE["screen"]
            x, y = gaze_screen_point(vc.gaze_eye_x, vc.gaze_eye_y, cx, cy, sw, sh)
            root.geometry(f"+{x - 1}+{y - 1}")
        except Exception:
            log_swallowed()
        root.after(33, tick)

    tick()
    root.mainloop()


def _start() -> None:
    stop = threading.Event()
    t = threading.Thread(target=_overlay_thread, args=(stop,), name="gaze_cursor", daemon=True)
    _STATE.update(stop=stop, thread=t)
    t.start()
    log_print("👁️ [視線游標] 開啟：桃紅色箭頭是她現在看的位置")


def _stop() -> None:
    if _STATE["stop"] is not None:
        _STATE["stop"].set()
    _STATE.update(stop=None, thread=None)
    log_print("👁️ [視線游標] 關閉")


async def gaze_cursor_worker() -> None:
    """跟著開關開關游標；開著時每幾秒更新一次螢幕大小和 VTS 視窗中心（她挪視窗、換螢幕解析度也跟得上）。"""
    while True:
        try:
            on = bool(host.IS_GAZE_CURSOR_ENABLED)
            running = _STATE["thread"] is not None and _STATE["thread"].is_alive()
            if on:
                sw, sh = pyautogui.size()
                _STATE["screen"] = (sw, sh)
                _STATE["center"] = await vc.update_vts_window_center(sw, sh)
                if not running:
                    _start()
            elif running:
                _stop()
        except Exception:
            log_swallowed()
        await asyncio.sleep(1.0)
