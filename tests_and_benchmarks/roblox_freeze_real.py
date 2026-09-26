
"""
=============================================================================
Roblox 真正的實體白邊按住凍結模擬器 (Physical Titlebar Hold)
- 解決純發送 0xF012 訊息被 Windows/DWM 判定實體滑鼠未按下而失效的問題
- 按下熱鍵：記憶當前游標 -> 瞬移到 Roblox 白邊 -> 硬體級按住 (Down) -> 觸發真實定格！
- 放開熱鍵：硬體級放開 (Up) -> 瞬間彈回原本游標位置 -> 視角完全不跑掉！
- 支援鍵盤 (F/Caps/其他) 與滑鼠 (側鍵 X1/X2/中鍵) 自選
=============================================================================
"""

import ctypes
import time
import sys
from pynput import keyboard, mouse

user32 = ctypes.windll.user32

# =========================== ⚙️ 參數設定 ===========================
# 點擊白邊的方式:
# 'LEFT'  : 左鍵按住白邊 (最經典的白邊移動按住)
# 'RIGHT' : 右鍵按住白邊 (不移動視窗，放開時自動關閉右鍵選單)
CLICK_MODE = 'LEFT'

# 預設熱鍵
DEFAULT_HOTKEY_TYPE = 'mouse'   # 'mouse' 或 'keyboard'
DEFAULT_MOUSE_BTN   = 'x1'      # 'x1' (側鍵下), 'x2' (側鍵上), 'middle' (滾輪)
DEFAULT_KEY         = 'f'       # 若用鍵盤預設為 'f'
# ===================================================================

# Win32 滑鼠/鍵盤/視窗常數
MOUSEEVENTF_LEFTDOWN  = 0x0002
MOUSEEVENTF_LEFTUP    = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP   = 0x0010
VK_ESCAPE             = 0x1B
SWP_NOSIZE            = 0x0001
SWP_NOZORDER          = 0x0004
SWP_NOACTIVATE        = 0x0010

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

def get_roblox_hwnd():
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

def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def get_titlebar_pos(hwnd):
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    # 標題列安全白邊位置: 避開左上角圖示與右上角關閉按鈕，取視窗偏左處
    title_x = rect.left + 250
    title_y = rect.top + 15
    return title_x, title_y

original_pos = (0, 0)
original_win_pos = (0, 0)
frozen_hwnd = None
is_frozen = False

def start_freeze():
    global original_pos, original_win_pos, frozen_hwnd, is_frozen
    if is_frozen:
        return
    
    hwnd = get_roblox_hwnd()
    if not hwnd:
        print("[!] 找不到目標視窗！")
        return

    # 1. 記憶目前玩家的滑鼠位置 (維持瞄準/視角)
    original_pos = get_cursor_pos()
    
    # 2. 記憶視窗原始座標，供放開時雙重校驗
    frozen_hwnd = hwnd
    win_rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win_rect))
    original_win_pos = (win_rect.left, win_rect.top)

    # 3. 取得 Roblox 標題列 (白邊) 的絕對螢幕座標
    tb_x, tb_y = get_titlebar_pos(hwnd)

    # 4. 先解除可能存在的視窗滑鼠拘束 (如 Shift-Lock / 第一人稱鎖定)
    user32.ClipCursor(None)

    # 5. 瞬間移動游標到白邊
    user32.SetCursorPos(tb_x, tb_y)

    # 6. 【核心防拖曳】將游標硬體級錨定在白邊 1x1 像素點！
    # 即使玩家在凍結期間晃動、移動滑鼠，游標也無法位移，Windows 絕對不會觸發視窗拖曳！
    clip_rect = RECT(tb_x, tb_y, tb_x + 1, tb_y + 1)
    user32.ClipCursor(ctypes.byref(clip_rect))

    # 7. 硬體級觸發按下 (Down)，啟動真正的非客戶區凍結！
    if CLICK_MODE == 'LEFT':
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    else:
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)

    is_frozen = True
    print(f"[❄️ 實體白邊按住] 游標已錨定白邊 ({tb_x}, {tb_y}) 並按住！視窗定格中 (防移動鎖定生效)...")

def stop_freeze():
    global original_pos, original_win_pos, frozen_hwnd, is_frozen
    if not is_frozen:
        return

    # 8. 硬體級觸發放開 (Up)
    try:
        if CLICK_MODE == 'LEFT':
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        else:
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            # 若是右鍵，發送 ESC 取消可能彈出的右鍵選單
            user32.keybd_event(VK_ESCAPE, 0, 0, 0)
            user32.keybd_event(VK_ESCAPE, 0, 2, 0)
    finally:
        # 9. 釋放游標錨定限制
        user32.ClipCursor(None)

    # 10. 雙重保險：檢查並還原視窗原本位置 (若有任何微小位移立即復原)
    if frozen_hwnd and original_win_pos:
        try:
            curr_rect = RECT()
            user32.GetWindowRect(frozen_hwnd, ctypes.byref(curr_rect))
            if curr_rect.left != original_win_pos[0] or curr_rect.top != original_win_pos[1]:
                user32.SetWindowPos(
                    frozen_hwnd, 0,
                    original_win_pos[0], original_win_pos[1], 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                )
        except Exception:
            pass

    # 11. 瞬間將游標歸位回原本位置 (視角/準星復原)
    user32.SetCursorPos(original_pos[0], original_pos[1])

    is_frozen = False
    print(f"[☀️ 白邊放開解除] 游標已歸位至原本位置 ({original_pos[0]}, {original_pos[1]})，視窗保持原位，遊戲恢復！")

# =========================== 🎧 按鍵監聽與綁定 ===========================

active_hotkey_type = DEFAULT_HOTKEY_TYPE
active_hotkey_value = DEFAULT_MOUSE_BTN if DEFAULT_HOTKEY_TYPE == 'mouse' else DEFAULT_KEY

def match_keyboard(key):
    if active_hotkey_type != 'keyboard':
        return False
    target = str(active_hotkey_value).lower()
    if hasattr(key, 'char') and key.char:
        return key.char.lower() == target
    if hasattr(key, 'name') and key.name:
        return key.name.lower() == target
    return False

def match_mouse(button):
    if active_hotkey_type != 'mouse':
        return False
    target = str(active_hotkey_value).lower()
    return button.name.lower() == target

def on_key_press(key):
    if match_keyboard(key):
        start_freeze()

def on_key_release(key):
    if match_keyboard(key):
        stop_freeze()

def on_mouse_click(x, y, button, pressed):
    if match_mouse(button):
        if pressed:
            start_freeze()
        else:
            stop_freeze()

def record_custom_hotkey():
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
    global active_hotkey_type, active_hotkey_value, CLICK_MODE

    print("=========================================================")
    print("      🎮 Roblox 真正的實體白邊按住凍結模擬器")
    print("=========================================================")
    print(f"【點擊模式】: {CLICK_MODE} (左鍵按住白邊)")
    print("---------------------------------------------------------")
    print("請選擇熱鍵設定:")
    print("  [1] 使用滑鼠側鍵 (X1 側鍵下 / 後退鍵) [推薦]")
    print("  [2] 使用鍵盤按鍵 (F 鍵)")
    print("  [3] 自選錄製 (直接按一下任意鍵盤或滑鼠鍵進行綁定)")
    print("---------------------------------------------------------")

    choice = input("請輸入選項 (1 / 2 / 3，預設直接按 Enter 為 1): ").strip()
    if choice == '2':
        active_hotkey_type = 'keyboard'
        active_hotkey_value = 'f'
    elif choice == '3':
        h_type, h_val = record_custom_hotkey()
        active_hotkey_type = h_type
        active_hotkey_value = h_val
    else:
        active_hotkey_type = 'mouse'
        active_hotkey_value = 'x1'

    print("---------------------------------------------------------")
    print(f"✅ 設定完成！當前熱鍵: 【{active_hotkey_type.upper()} : {active_hotkey_value}】")
    print(f"✅ 凍結方式: 【硬體級瞬移至白邊按住 + 放開自動歸位】")
    print("💡 提醒: Roblox 必須處於「視窗化 (Windowed)」狀態！")
    print("💡 操作: 按住熱鍵 = 手按住白邊定格；放開熱鍵 = 遊戲恢復並還原游標。")
    print("💡 結束請按 Ctrl + C。現在即可切換到遊戲測試！")
    print("=========================================================\n")

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
        stop_freeze()
        user32.ClipCursor(None)
        k_listener.stop()
        m_listener.stop()

if __name__ == "__main__":
    main()
