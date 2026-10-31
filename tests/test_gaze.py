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


def test_gaze_brain_turns_the_pick_into_an_exact_point():
    """Live 只挑「看哪個、哪一塊」，準的座標由程式照視窗位置算（直接要座標實測不準）。"""
    import workers.gaze_brain as gb
    wins = [("Claude", (0.5, 0.0, 1.0, 0.5)), ("檔案總管", (0.1, 0.5, 0.6, 0.95))]
    menu, items = gb.build_menu(wins, (0.62, 0.37), (0.9, 0.1), talking=True)
    assert menu.startswith("她現在正在講話。") and "1：Claude（螢幕上右）" in menu and "5：鏡頭（看觀眾）" in menu
    idx, kind, point, rect, why = gb.parse_pick('{"pick": 1, "part": "上中", "why": "好奇老爸在問什麼"}', items)
    assert (idx, kind, rect) == (0, "window", (0.5, 0.0, 1.0, 0.5)) and point == (0.75, 0.1) and why == "好奇老爸在問什麼"
    assert gb.parse_pick('{"pick": 5}', items)[1:3] == ("camera", None)
    assert gb.parse_pick('{"pick": 3}', items)[1:3] == ("mouse", (0.62, 0.37))
    assert gb.parse_pick('{"pick": 9}', items) is None and gb.parse_pick("我看看～", items) is None


def test_director_follows_the_brains_pick_but_reflexes_still_win():
    g = _g(5)
    g.note_window((0.5, 0.0, 1.0, 0.5), -100.0)
    g.note_intent("window", (0.75, 0.1), (0.5, 0.0, 1.0, 0.5), 10.0)
    p = g.update(10.0)
    assert g.kind == "intent" and 0.5 <= p[0] <= 1.0 and 0.0 <= p[1] <= 0.5
    inside = n = 0
    for seed in range(30):                                            # 副腦說看 Claude 那幾秒，大多在看那一塊
        h = _g(seed)
        h.note_window((0.5, 0.0, 1.0, 0.5), -100.0)
        h.note_intent("window", (0.75, 0.1), (0.5, 0.0, 1.0, 0.5), 10.0)
        t = 10.0
        while t < 16.0:
            q = h.update(t)
            inside += q is not None and 0.5 <= q[0] <= 1.0 and q[1] <= 0.5
            n += 1
            t += 0.1
    assert inside / n > 0.8
    g.note_mouse((0.1, 0.9), 16.0, moved_px=50)                       # 滑鼠突然動：反射照樣看過去
    assert g.update(16.0) == (0.1, 0.9)


def test_gaze_brain_only_runs_with_peripheral_vision_and_uses_the_blockable_capture():
    import inspect
    import workers.gaze_brain as gb
    src = inspect.getsource(gb.gaze_brain_worker)
    assert "host.IS_PERIPHERAL_VISION_ENABLED" in src and "screen_capture.grab_screen" in src and "if img is None:" in src
    assert "vtube studio" in inspect.getsource(gb.visible_windows)   # 不看自己


def test_same_pick_again_does_not_make_her_jump():
    g = _g(2)
    g.note_intent("window", (0.75, 0.1), (0.5, 0.0, 1.0, 0.5), 10.0)
    g.update(10.0)
    g.until = 99.0                                                    # 正盯著
    g.note_intent("window", (0.7, 0.2), (0.5, 0.0, 1.0, 0.5), 13.0)  # 副腦又挑同一個視窗
    before = g.target
    assert g.update(13.0) == before
    g.note_intent("camera", None, None, 16.0)                         # 換成看鏡頭：才跳
    assert g.update(16.0) is None and g.kind == "intent"


def test_a_video_that_keeps_playing_stops_pulling_her_eyes():
    g = _g(4)
    g.note_hotspot((0.15, 0.2), 10.0)
    assert g.update(10.0) == (0.15, 0.2)                               # 第一次：瞄過去
    g.until = 0.0
    g.kind = "camera"
    g.note_hotspot((0.17, 0.22), 12.0)                                 # 同一個地方繼續在動：不再拉過去
    assert g.update(12.0) != (0.17, 0.22) or g.kind != "hotspot"
    g.note_hotspot((0.8, 0.9), 13.0)                                   # 別的地方跳出新東西，但才 3 秒：反射最多 6 秒一次
    assert g.update(13.0) != (0.8, 0.9) or g.kind != "hotspot"
    g.until = 0.0
    g.note_hotspot((0.5, 0.1), 17.0)                                   # 再過幾秒又有新東西：瞄過去
    assert g.update(17.0) == (0.5, 0.1)
