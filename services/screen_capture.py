# -*- coding: utf-8 -*-
"""全螢幕截圖（主程式的視覺、後台縮圖、run_dashboard 共用）。

以前三個地方各有一份 GDI 截圖程式。2026-10-25 主程式那份修了 64 位元 handle 溢位，
後台那份還是舊的、畫面靜止時照樣失敗——重複的程式碼讓 bug 只修一半，所以收成這一份。
"""
import threading

_DXCAM_CAM = None
_DXCAM_FAILED = False
_DXCAM_LAST_FRAME = None
_DXCAM_LOCK = threading.Lock()


def get_dxcam_cam():
    """DXGI 顯存截圖（1~3ms）；建不起來（被遊戲反作弊擋、沒有 dxcam）就記住失敗，之後都走 GDI。"""
    global _DXCAM_CAM, _DXCAM_FAILED
    if _DXCAM_FAILED:
        return None
    if _DXCAM_CAM is not None:
        return _DXCAM_CAM
    try:
        import dxcam
        _DXCAM_CAM = dxcam.create(output_color="RGB")
        return _DXCAM_CAM
    except Exception:
        _DXCAM_FAILED = True
        return None


def grab_screen():
    """全螢幕截圖，回 PIL RGB 圖或 None：先 dxcam，dxcam 沒新畫面就沿用上一張，都不行才走 GDI。"""
    global _DXCAM_LAST_FRAME
    from PIL import Image
    cam = get_dxcam_cam()
    if cam is not None:
        try:
            with _DXCAM_LOCK:
                frame = cam.grab()
                if frame is not None:
                    _DXCAM_LAST_FRAME = frame
                # dxcam 在畫面沒變時回 None：沒變就代表上一張還是現在的畫面
                frame = frame if frame is not None else _DXCAM_LAST_FRAME
            if frame is not None:
                return Image.fromarray(frame)
        except Exception:
            pass
    return gdi_capture_screen()


def gdi_capture_screen():
    """GDI BitBlt 全螢幕截圖（dxcam 不能用時的備援）。回 PIL RGB 圖。

    用自己的 WinDLL 物件並宣告參數／回傳型別：預設 c_int 會把 64 位元的 handle 截斷或溢位，
    舊碼在畫面靜止（dxcam 回 None）時一走這裡就 OverflowError（2026-10-25 實機一小時 6 次）。
    另開 WinDLL 不會動到 ctypes.windll，其他套件照舊。"""
    from PIL import Image
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    H = ctypes.c_void_p
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetDesktopWindow.restype = H
    user32.GetWindowDC.argtypes, user32.GetWindowDC.restype = [H], H
    user32.ReleaseDC.argtypes = [H, H]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [H], H
    gdi32.CreateCompatibleBitmap.argtypes, gdi32.CreateCompatibleBitmap.restype = [H, ctypes.c_int, ctypes.c_int], H
    gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = [H, H], H
    gdi32.BitBlt.argtypes = [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H, ctypes.c_int, ctypes.c_int, wt.DWORD]
    gdi32.GetDIBits.argtypes = [H, H, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    gdi32.DeleteObject.argtypes = [H]
    gdi32.DeleteDC.argtypes = [H]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_int32), ('biHeight', ctypes.c_int32),
            ('biPlanes', ctypes.c_uint16), ('biBitCount', ctypes.c_uint16), ('biCompression', ctypes.c_uint32),
            ('biSizeImage', ctypes.c_uint32), ('biXPelsPerMeter', ctypes.c_int32), ('biYPelsPerMeter', ctypes.c_int32),
            ('biClrUsed', ctypes.c_uint32), ('biClrImportant', ctypes.c_uint32)
        ]

    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    hdesk = user32.GetDesktopWindow()
    desk_dc = user32.GetWindowDC(hdesk)
    img_dc = gdi32.CreateCompatibleDC(desk_dc)
    mem_bmp = gdi32.CreateCompatibleBitmap(desk_dc, w, h)
    try:
        gdi32.SelectObject(img_dc, mem_bmp)
        gdi32.BitBlt(img_dc, 0, 0, w, h, desk_dc, 0, 0, 0x00CC0020)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(img_dc, mem_bmp, 0, h, buf, ctypes.byref(bmi), 0)
        return Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    finally:
        gdi32.DeleteObject(mem_bmp)
        gdi32.DeleteDC(img_dc)
        user32.ReleaseDC(hdesk, desk_dc)
