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
    assert len(targets) >= 2                                        # 副腦沒回應時照規則：視窗、鏡頭輪流看
    assert targets <= {None, (0.35, 0.1 + 0.7 * 0.35)}              # 看視窗是固定一點，不隨機亂飄（2026-11-01）


def test_moving_the_mouse_does_not_always_pull_her_eyes():
    """老爸 2026-10-31：不要我一動滑鼠她就看滑鼠。滑鼠開始動只是有時候瞄過去。"""
    grabbed = 0
    for seed in range(200):
        g = _g(seed)
        g.note_window((0.5, 0.0, 1.0, 0.5), -100.0)
        g.note_mouse((0.2, 0.3), 0.0)
        g.update(0.0)
        g.note_mouse((0.25, 0.3), 5.0, moved_px=40)
        grabbed += g.update(5.0) == (0.25, 0.3)
    assert 0 < grabbed / 200 < 0.45


def test_when_she_does_look_at_the_mouse_she_follows_it_for_a_while_not_forever():
    g = _g()
    g.note_mouse((0.2, 0.3), 0.0)
    g._fix_mouse(0.0)
    g.note_mouse((0.4, 0.35), 0.2, moved_px=60)                     # 繼續動：跟著看
    assert g.update(0.2) == (0.4, 0.35)
    t, seen_other = 0.2, False
    while t < 8.0:                                                  # 一直動也不會永遠盯著
        t += 0.1
        g.note_mouse((0.4 + (t % 1) * 0.1, 0.35), t, moved_px=30)
        g.update(t)
        seen_other |= g.kind != "mouse"
    assert seen_other


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


def test_grid_cells_map_to_exact_points():
    """老爸 2026-11-01：給她網格，選要看畫面上哪一格。8x6：A～H 直行由左到右、1～6 橫列由上到下。"""
    import workers.gaze_brain as gb
    assert gb.cell_name(0.0, 0.0) == "A1" and gb.cell_name(0.999, 0.999) == "H6" and gb.cell_name(1.0, 1.0) == "H6"
    assert gb.cell_center("A1") == (1 / 16, 1 / 12) and gb.cell_center("h6") == (15 / 16, 11 / 12)
    for name in ("C3", "F5", "B6"):
        assert gb.cell_name(*gb.cell_center(name)) == name
    assert gb.cell_center("I1") is None and gb.cell_center("A7") is None and gb.cell_center("鏡頭") is None
    assert gb.cell_span((0.5, 0.0, 1.0, 0.5)) == "E1～H3" and gb.cell_span((0.1, 0.1, 0.12, 0.12)) == "A1"


def test_gaze_brain_prompt_lists_cells_and_answers_become_points():
    import workers.gaze_brain as gb
    wins = [("Claude", (0.5, 0.0, 1.0, 0.5)), ("檔案總管", (0.1, 0.5, 0.6, 0.95))]
    prompt = gb.build_prompt(wins, (0.62, 0.37), (0.9, 0.1), talking=True)
    assert prompt.startswith("她現在正在講話。") and "- Claude（E1～H3）" in prompt and "- 檔案總管（A4～E6）" in prompt
    assert "滑鼠在 E3" in prompt and "剛有變化的地方在 H1" in prompt and '"look"' in prompt
    kind, pts, cells, why = gb.parse_look('好～ {"look": ["F2", "g2", "F2", "H3", "A1"], "why": "好奇老爸在問什麼"}')
    assert kind == "grid" and cells == ["F2", "G2", "H3"] and pts[0] == gb.cell_center("F2") and why == "好奇老爸在問什麼"
    assert gb.parse_look('{"look": "C4"}')[2] == ["C4"]
    assert gb.parse_look('{"look": "鏡頭"}')[:2] == ("camera", [])
    assert gb.parse_look('{"look": ["滑鼠"]}')[:2] == ("mouse", [])
    assert gb.parse_look('{"look": ["Z9"]}') is None and gb.parse_look("我看看～") is None and gb.parse_look("[1]") is None
    # Fable：照抄提示詞的格式、或寫在同一個字串裡也要認；A12、Chrome1 這種不是格名
    assert gb.parse_look('{"look": "E1～H3"}')[2] == ["E1", "H3"]
    assert gb.parse_look('{"look": "C3, d 4。"}')[2] == ["C3", "D4"]
    assert gb.parse_look('{"look": ["A12", "Chrome1", "B2"]}')[2] == ["B2"]
    # 照第一個說的算
    assert gb.parse_look('{"look": ["C3", "滑鼠"]}')[:1] == ("grid",)
    assert gb.parse_look('{"look": ["滑鼠", "C3"]}')[:1] == ("mouse",)
    assert gb.parse_look('{"look": "先看鏡頭再看 C3"}')[:1] == ("camera",)
    # 轉寫掉了大括號
    assert gb.parse_look('"look": ["F2"], "why": "看 A1 那邊"')[2] == ["F2"]
    assert gb.parse_look('{"look": ["F2"], "why": "裡面有 } 括號"}')[2] == ["F2"]


def test_grid_is_drawn_on_the_screenshot():
    import io
    from PIL import Image
    import workers.gaze_brain as gb
    jpg = gb.grid_jpeg(Image.new("RGB", (3840, 2160), (20, 20, 20)))
    img = Image.open(io.BytesIO(jpg)).convert("RGB")
    assert img.size == (1280, 720)
    r, g, b = img.getpixel((160, 400))                               # A、B 之間的直線：青色（不跟桃紅的視線游標同色）
    assert r < 80 and g > 120 and b > 150
    r, g, b = img.getpixel((14, 20))                                  # A1 的黃字（或它的黑邊）
    assert (r > 150 and g > 150 and b < 120) or (r < 40 and g < 40)


def test_director_looks_exactly_at_the_picked_cells_in_order_without_jitter():
    """副腦挑了格子：照順序看那幾格的中心，看完停在最後一格；不隨機抖、也不會 25% 機率改看別的（老爸 2026-11-01）。"""
    import workers.gaze_brain as gb
    pts = [gb.cell_center(c) for c in ("F2", "G2", "G3")]
    for seed in range(30):
        g = _g(seed)
        g.note_window((0.5, 0.0, 1.0, 0.5), -100.0)
        g.note_mouse((0.2, 0.8), -100.0)
        g.note_intent("grid", pts, 10.0)
        seen = []
        t = 10.0
        while t < 16.9:
            q = g.update(t)
            if not seen or seen[-1] != q:
                seen.append(q)
            t += 0.1
        assert seen == pts, seed


def test_reflexes_still_win_over_the_brains_pick():
    import workers.gaze_brain as gb
    g = _g(5)
    g.note_intent("grid", [gb.cell_center("F2")], 10.0)
    assert g.update(10.0) == gb.cell_center("F2") and g.kind == "intent"
    g.note_hotspot((0.1, 0.9), 11.0)                                  # 畫面突然跳東西：反射照樣能把她拉過去
    g._last_hotspot_reflex = -1e9
    g.rng.random = lambda: 0.0
    assert g.update(11.0) == (0.1, 0.9)


def test_a_pick_made_while_quiet_does_not_hold_her_eyes_once_she_talks():
    """Fable：副腦挑的時候她沒在講話，之後開口了：照講話的規則（多看鏡頭），不是盯著格子講 12 秒。"""
    import workers.gaze_brain as gb
    looks = []
    for seed in range(20):
        g = _g(seed)
        g.note_intent("grid", [gb.cell_center("F2")], 10.0, talking=False)
        assert g.update(10.0) == gb.cell_center("F2")
        g.until = 0.0
        t = 10.5
        while t < 20.0:
            looks.append(g.update(t, talking=True) is None)
            t += 0.1
    assert sum(looks) / len(looks) > 0.5
    g = _g(1)
    g.note_intent("grid", [gb.cell_center("F2")], 10.0, talking=True)   # 講話中挑的：照它看
    g.update(10.0, talking=True)
    g.until = 0.0
    assert g.update(11.0, talking=True) == gb.cell_center("F2")


def test_picking_the_mouse_follows_the_moving_mouse():
    g = _g(6)
    g.note_mouse((0.3, 0.3), 9.0)
    g.note_intent("mouse", [], 10.0)
    assert g.update(10.0) == (0.3, 0.3) and g.kind == "mouse"
    g.note_mouse((0.4, 0.35), 10.3, moved_px=50)
    assert g.update(10.3) == (0.4, 0.35)


def test_gaze_brain_only_runs_with_peripheral_vision_and_uses_the_blockable_capture():
    import inspect
    import workers.gaze_brain as gb
    src = inspect.getsource(gb.gaze_brain_worker)
    assert "host.IS_PERIPHERAL_VISION_ENABLED" in src and "screen_capture.grab_screen" in src and "if img is None:" in src
    assert "vtube studio" in inspect.getsource(gb.visible_windows)   # 不看自己


def test_same_pick_again_does_not_make_her_start_over():
    import workers.gaze_brain as gb
    pts = [gb.cell_center("F2"), gb.cell_center("G2")]
    g = _g(2)
    g.note_intent("grid", pts, 10.0)
    assert g.update(10.0) == pts[0]
    g.until = 0.0
    assert g.update(11.0) == pts[1]                                   # 看到第二格
    g.until = 99.0
    g.note_intent("grid", list(pts), 13.0)                            # 副腦又挑一樣的：不從第一格重看
    assert g.update(13.0) == pts[1]
    g.note_intent("camera", [], 16.0)                                 # 換成看鏡頭：才跳
    assert g.update(16.0) is None and g.kind == "intent"
    g.note_intent("grid", [], 17.0)                                   # 空的格子清單不算數
    assert g.intent["kind"] == "camera"


def test_a_video_that_keeps_playing_stops_pulling_her_eyes():
    g = _g(4)
    g.note_hotspot((0.15, 0.2), 10.0)
    assert g.update(10.0) == (0.15, 0.2)                               # 第一次：瞄過去
    g.until = 0.0
    g.kind = "camera"
    g.note_hotspot((0.17, 0.22), 12.0)                                 # 同一個地方繼續在動：不再拉過去
    assert g.update(12.0) != (0.17, 0.22) or g.kind != "hotspot"
    g.until = 99.0                                                     # 正盯著別處：只有反射能拉走她
    g.note_hotspot((0.8, 0.9), 13.0)                                   # 別的地方跳出新東西，但才 3 秒：反射最多 6 秒一次
    assert g.update(13.0) != (0.8, 0.9) or g.kind != "hotspot"
    g.until = 0.0
    g.note_hotspot((0.5, 0.1), 17.0)                                   # 再過幾秒又有新東西：瞄過去
    assert g.update(17.0) == (0.5, 0.1)


def test_gaze_brain_spreads_keys_and_backs_off_when_live_keeps_failing():
    """Fable 審查：副腦以前永遠打全池第一把空著的 key、每次試兩把；Live 壞掉時每 3 秒照樣燒、沒日誌。"""
    import inspect
    import workers.gaze_brain as gb
    src = inspect.getsource(gb.gaze_brain_worker)
    assert "random.sample(le.GEMINI_KEYS, len(le.GEMINI_KEYS))" in src and "max_keys=1" in src
    assert "GAZE_BRAIN_SEC * (2 ** min(misses, 5))" in src and "misses += 1" in src and "misses = 0" in src
    assert min(gb.GAZE_BRAIN_BACKOFF_MAX, gb.GAZE_BRAIN_SEC * 2 ** 5) == 60.0
