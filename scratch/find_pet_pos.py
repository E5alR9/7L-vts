import ctypes
from ctypes import wintypes
ctypes.windll.user32.SetProcessDPIAware()
user32 = ctypes.windll.user32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

wins = []
def cb(hwnd, _):
    if user32.IsWindowVisible(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        wins.append((hwnd, pid.value, cls_buf.value, buf.value, rect.left, rect.top, rect.right, rect.bottom))
    return True

proc = WNDENUMPROC(cb)
user32.EnumWindows(proc, 0)

for hwnd, pid, cls, title, l, t, r, b in wins:
    w = r - l
    h = b - t
    if pid == 3532 or 'cross' in title.lower() or 'pet' in title.lower() or 'HwndWrapper' in cls:
        print(f"HWND={hwnd}, PID={pid}, Class={cls}, Title='{title}', Rect=({l},{t},{r},{b}), size={w}x{h}")
