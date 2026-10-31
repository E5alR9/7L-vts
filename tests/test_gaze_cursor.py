"""視線游標（老爸 2026-10-31）：眼睛角度反推螢幕上的點，跟臉部追蹤看滑鼠那段用同一套換算。"""
import ast
import os

import workers.gaze_cursor as gc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _eyes_for_mouse(px, py, cx, cy, sw, sh):
    """照 workers/face_tracking.py 看滑鼠那段：滑鼠位置 → look → 眼睛角度（不夾 ±0.85 的範圍內）。"""
    look_x = ((px / sw) - cx) * 28.0
    look_y = ((py / sh) - cy) * -20.0
    return look_x / 20.0, look_y / 15.0


def test_looking_at_the_mouse_points_back_at_the_mouse():
    sw, sh, cx, cy = 2560, 1440, 0.7, 0.55
    for px, py in [(1792, 792), (1500, 600), (2100, 1000), (1800, 400)]:
        ex, ey = _eyes_for_mouse(px, py, cx, cy, sw, sh)
        x, y = gc.gaze_screen_point(ex, ey, cx, cy, sw, sh)
        assert abs(x - px) <= 1 and abs(y - py) <= 1


def test_straight_ahead_is_her_window_center_and_points_stay_on_screen():
    assert gc.gaze_screen_point(0.0, 0.0, 0.5, 0.5, 1920, 1080) == (960, 540)
    x, y = gc.gaze_screen_point(-0.85, 0.85, 0.05, 0.05, 1920, 1080)   # 往左上看到螢幕外：夾在邊上
    assert (x, y) == (0, 0)
    _, y = gc.gaze_screen_point(0.0, -0.75, 0.5, 0.5, 1920, 1080)      # 彈琴往下看琴鍵
    assert y > 540


def test_face_tracking_publishes_the_eye_angles_and_the_switch_is_wired():
    ft = open(os.path.join(ROOT, "workers", "face_tracking.py"), encoding="utf-8").read()
    assert "vc.gaze_eye_x, vc.gaze_eye_y = curr_eye_x, curr_eye_y" in ft
    bridge = open(os.path.join(ROOT, "services", "dashboard_bridge.py"), encoding="utf-8").read()
    assert bridge.count('"IS_GAZE_CURSOR_ENABLED"') >= 3 and "c.IS_GAZE_CURSOR_ENABLED = target_val" in bridge
    from conftest import MAIN_SRC
    assert "spawn(gaze_cursor.gaze_cursor_worker())" in MAIN_SRC and "\nIS_GAZE_CURSOR_ENABLED = False" in MAIN_SRC
    # 游標視窗點不到、不被截圖
    src = open(gc.__file__, encoding="utf-8").read()
    assert "WS_EX_TRANSPARENT" in src and "SetWindowDisplayAffinity(hwnd, 0x11)" in src
