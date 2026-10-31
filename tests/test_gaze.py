"""她看哪裡（core/gaze；老爸 2026-10-31：視線像亂晃，不像真的看見桌面）。"""
import random

import numpy as np

from core.gaze import GazeDirector, hotspot_from_diff, look_angles


def _g(seed=1):
    return GazeDirector(random.Random(seed))


def test_she_holds_a_look_then_jumps_instead_of_drifting():
    g = _g()
    g.note_window((0.1, 0.1, 0.6, 0.8), 0.0)
    first = g.update(0.0)
    assert g.update(0.1) == first and g.update(0.3) == first          # 盯住，不是每格都飄
    targets = {g.update(t / 10) for t in range(0, 600)}
    assert len(targets) > 5                                         # 一分鐘內會換好幾個地方看


def test_mouse_starting_to_move_grabs_her_eyes_and_she_follows_it():
    g = _g()
    g.note_mouse((0.2, 0.3), 0.0)
    g.update(0.0)
    g.note_mouse((0.25, 0.3), 5.0, moved_px=40)                     # 停了 5 秒又動：馬上看過去
    assert g.update(5.0) == (0.25, 0.3) and g.kind == "mouse"
    g.note_mouse((0.4, 0.35), 5.2, moved_px=60)                     # 繼續動：跟著看
    assert g.update(5.2) == (0.4, 0.35)


def test_new_window_and_screen_change_draw_a_glance():
    g = _g()
    g.update(0.0)
    g.note_window((0.5, 0.0, 1.0, 0.5), 10.0)
    p = g.update(10.0)
    assert g.kind == "window" and 0.5 <= p[0] <= 1.0 and 0.0 <= p[1] <= 0.5
    g.note_hotspot((0.9, 0.9), 12.0)
    assert g.update(12.0) == (0.9, 0.9) and g.kind == "hotspot"
    assert g.update(12.1) == (0.9, 0.9)                             # 同一個變化只瞄一次，盯完才換


def test_when_talking_she_mostly_looks_at_the_camera():
    g = _g(3)
    g.note_window((0.1, 0.1, 0.6, 0.8), -100.0)
    looks = []
    t = 0.0
    while t < 120:
        p = g.update(t, talking=True)
        looks.append(p is None)
        t += 0.1
    assert sum(looks) / len(looks) > 0.5


def test_angles_match_the_mouse_mapping_and_camera_is_straight_ahead():
    assert look_angles(None, 0.7, 0.5) == (0.0, 0.0)
    x, y = look_angles((0.8, 0.4), 0.7, 0.5)
    assert abs(x - 2.8) < 1e-9 and abs(y - 2.0) < 1e-9


def test_screen_change_hotspot_ignores_her_own_window():
    d = np.zeros((36, 64), dtype=np.float32)
    d[10:14, 50:54] = 120.0            # 她自己的 VTS 視窗在動
    d[25:29, 5:9] = 60.0               # 老爸那邊跳出通知
    mask = np.zeros_like(d, dtype=bool)
    mask[:, 45:] = True
    x, y = hotspot_from_diff(d, mask)
    assert x < 0.2 and y > 0.6
    assert hotspot_from_diff(np.zeros((36, 64)), None) is None      # 沒變化不看
