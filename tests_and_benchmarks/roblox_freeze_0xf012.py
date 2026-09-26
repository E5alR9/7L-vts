"""
=============================================================================
Roblox / 視窗 0xF012 白邊拖曳凍結模擬腳本
- 使用 Win32 SC_DRAGMOVE (0xF012) 模擬滑鼠在標題列按住的拖曳凍結狀態
- 支援「鍵盤按鍵」或「滑鼠按鍵（如側鍵 X1/X2、中鍵）」自選綁定
- 預設模式：【按住熱鍵凍結，放開熱鍵解除】（亦可切換為按一下開關模式）
=============================================================================
"""

import ctypes
import time
import sys
from pynput import keyboard, mouse

user32 = ctypes.windll.user32

# =========================== ⚙️ 預設參數設定 ===========================
# 模式: 'HOLD' (按住凍結/放開解凍，推薦跑酷使用) 或 'TOGGLE' (按一下凍結/再按一下解凍)
TRIGGER_MODE = 'HOLD'

# 預設熱鍵設定 (若啟動時未重新錄製，將使用此設定)
# 類型: 'keyboard' 或 'mouse'
DEFAULT_HOTKEY_TYPE = 'keyboard' 
DEFAULT_KEY = 'f'                # 鍵盤預設: 'f', 'caps_lock', 'c', 'v', 'space' 等
DEFAULT_MOUSE_BTN = 'x1'         # 滑鼠預設: 'x1' (側鍵下/後退), 'x2' (側鍵上/前進), 'middle' (中鍵)
# =====================================================================

# Win32 常數
WM_SYSCOMMAND = 0x0112
SC_DRAGMOVE   = 0xF012   # SC_MOVE (0xF010) | HTCAPTION (2)
WM_KEYDOWN    = 0x0100
WM_KEYUP      = 0x0101
VK_ESCAPE     = 0x1B

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

def get_target_window():
    """優先尋找 Roblox 視窗，若無則鎖定當前作用中視窗"""
    hwnd = user32.FindWindowW("WINDOWSCLIENT", "Roblox")
    if not hwnd:
        hwnd = user32.FindWindowW(None, "Roblox")
    if not hwnd:
        hwnd = user32.GetForegroundWindow()
    return hwnd

def get_window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value

is_frozen = False

def do_freeze():
    global is_frozen
    if is_frozen:
        return
    hwnd = get_target_window()
    if not hwnd:
        print("[!] 找不到可作用的視窗！")
        return
    
    title = get_window_title(hwnd)
    # 發送 0xF012 系統移動訊息
    user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_DRAGMOVE, 0)
    is_frozen = True
    print(f"[❄️ 凍結生效] 目標視窗: 《{title}》 | 訊息: WM_SYSCOMMAND (0xF012)")

def do_unfreeze():
    global is_frozen
    if not is_frozen:
        return
    hwnd = get_target_window()
    if hwnd:
        # 發送 ESC 取消移動模式，解除凍結
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0)
        # 雙重保險：硬體級 ESC 訊號
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        user32.keybd_event(VK_ESCAPE, 0, 2, 0)
    is_frozen = False
    print("[☀️ 凍結解除] 已發送 ESC 取消移動模式，視窗恢復運作！")

# =========================== 🎧 按鍵監聽與綁定 ===========================

active_hotkey_type = DEFAULT_HOTKEY_TYPE
active_hotkey_value = DEFAULT_KEY if DEFAULT_HOTKEY_TYPE == 'keyboard' else DEFAULT_MOUSE_BTN

def match_keyboard(key):
    if active_hotkey_type != 'keyboard':
        return False
    target = str(active_hotkey_value).lower()
    # 單一字符 (如 'f', 'c')
    if hasattr(key, 'char') and key.char:
        return key.char.lower() == target
    # 特殊按鍵 (如 'caps_lock', 'space', 'shift_r')
    if hasattr(key, 'name') and key.name:
        return key.name.lower() == target
    return False

def match_mouse(button):
    if active_hotkey_type != 'mouse':
        return False
    target = str(active_hotkey_value).lower()
    return button.name.lower() == target

def on_key_press(key):
    global is_frozen
    if match_keyboard(key):
        if TRIGGER_MODE == 'HOLD':
            do_freeze()
        elif TRIGGER_MODE == 'TOGGLE':
            if is_frozen:
                do_unfreeze()
            else:
                do_freeze()

def on_key_release(key):
    if match_keyboard(key):
        if TRIGGER_MODE == 'HOLD':
            do_unfreeze()

def on_mouse_click(x, y, button, pressed):
    global is_frozen
    if match_mouse(button):
        if pressed:
            if TRIGGER_MODE == 'HOLD':
                do_freeze()
            elif TRIGGER_MODE == 'TOGGLE':
                if is_frozen:
                    do_unfreeze()
                else:
                    do_freeze()
        else:
            if TRIGGER_MODE == 'HOLD':
                do_unfreeze()

def record_custom_hotkey():
    """啟動時讓使用者直接按一下鍵盤或滑鼠鍵進行自動綁定"""
    print("\n---------------------------------------------------------")
    print("👉 請直接按下你想設定的【鍵盤按鍵】或【滑鼠按鍵】...")
    print("   (例如: 按一下鍵盤 F、Caps Lock，或點一下滑鼠側鍵 X1/中鍵)")
    print("---------------------------------------------------------")

    captured = []

    def _rec_k_press(key):
        val = key.char if (hasattr(key, 'char') and key.char) else key.name
        captured.append(('keyboard', val))
        return False

    def _rec_m_click(x, y, button, pressed):
        if pressed:
            # 避免抓到一般日常左鍵，但如果使用者特意點左鍵也可以
            captured.append(('mouse', button.name))
            return False

    kl = keyboard.Listener(on_press=_rec_k_press)
    ml = mouse.Listener(on_click=_rec_m_click)
    kl.start()
    ml.start()

    while not captured:
        time.sleep(0.02)

    kl.stop()
    ml.stop()

    return captured[0]

def main():
    global active_hotkey_type, active_hotkey_value

    print("=========================================================")
    print("       🎮 Roblox 視窗 0xF012 白邊拖曳凍結測試工具")
    print("=========================================================")
    print("【模式說明】: 預設為【按住熱鍵凍結，放開熱鍵恢復】")
    print(f"目前預設熱鍵: [{DEFAULT_HOTKEY_TYPE.upper()}] -> {active_hotkey_value}")
    print("---------------------------------------------------------")
    print("請選擇啟動方式:")
    print("  [1] 使用預設鍵盤按鍵 (F 鍵)")
    print("  [2] 使用預設滑鼠側鍵 (X1 側鍵下 / 後退鍵)")
    print("  [3] 自選錄製 (直接按一下任意鍵盤或滑鼠鍵進行綁定)")
    print("---------------------------------------------------------")

    choice = input("請輸入選項 (1 / 2 / 3，預設直接按 Enter 為 1): ").strip()
    if choice == '2':
        active_hotkey_type = 'mouse'
        active_hotkey_value = 'x1'
    elif choice == '3':
        h_type, h_val = record_custom_hotkey()
        active_hotkey_type = h_type
        active_hotkey_value = h_val
    else:
        active_hotkey_type = 'keyboard'
        active_hotkey_value = 'f'

    print("---------------------------------------------------------")
    print(f"✅ 設定成功！當前熱鍵已綁定為: 【{active_hotkey_type.upper()} : {active_hotkey_value}】")
    print(f"✅ 觸發命令: WM_SYSCOMMAND (0xF012)")
    print("💡 提醒: Roblox 必須處於「視窗化 (Windowed)」狀態，不要按 F11 全螢幕。")
    print("💡 結束請按 Ctrl + C。現在即可切換到遊戲測試！")
    print("=========================================================\n")

    # 啟動鍵盤與滑鼠全域監聽器
    k_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)
    m_listener = mouse.Listener(on_click=on_mouse_click)

    k_listener.start()
    m_listener.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n腳本已停止。")
    finally:
        do_unfreeze()
        k_listener.stop()
        m_listener.stop()

if __name__ == "__main__":
    main()
