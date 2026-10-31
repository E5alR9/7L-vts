# -*- coding: utf-8 -*-
"""視線副腦：用 Live 看螢幕，決定她現在「想看什麼」（老爸 2026-10-31：用 api live 真的就是她想看的位置，不是單純規則）。

實測（同日）：直接叫 Live 回座標不可靠——她的臉在 (611, 860) 它回 (850, 850)，好幾次回畫面正中央。
改成程式列出螢幕上看得到的視窗（標題、在螢幕哪一區）、滑鼠、鏡頭、剛有變化的地方，Live 看截圖從裡面挑一個，
再說看那一塊（上中下、左中右）；準的座標由程式照視窗位置算。實測連問三次都挑老爸正在用的 Claude 視窗、
理由「好奇老爸在讓 AI 幫忙做什麼」，約 3 秒一次。

結果放在 vc.gaze_intent，臉部追蹤交給 core.gaze 當注視目標（反射——滑鼠突然動、畫面跳通知——照樣會打斷）。
只在餘光視覺開著、臉部追蹤開著、沒睡著時跑；截圖走 services.screen_capture（測試包裝擋截圖時拿到 None，自動不跑）。
主程式的狀態經 host.<名稱> 即時讀（host＝主程式模組，主程式 import 本檔後 bind()）。
"""
import asyncio
import io
import json
import re
import time

import services.vts_client as vc
from core.utils import log_print, log_swallowed

HOST_ATTRS = (
    "IS_PERIPHERAL_VISION_ENABLED",
    "IS_FACE_TRACKING_ENABLED",
    "IS_SLEEPING",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


GAZE_BRAIN_SEC = 3.0          # 多久問一次（Live 回一次約 3 秒，等於一直有一題在問）
GAZE_BRAIN_TIMEOUT = 8.0
MAX_WINDOWS = 8
_PARTS_Y = {"上": 0.2, "中": 0.5, "下": 0.8}
_PARTS_X = {"左": 0.2, "中": 0.5, "右": 0.8}

SYSTEM = ("妳是 7L 的眼睛：7L 是坐在老爸電腦旁的虛擬女兒，看得到老爸的螢幕。看截圖，從候選清單挑一個妳現在最想看的"
          "（老爸正在做的事、剛出現的東西、有趣的東西；她在講話時多半看鏡頭跟觀眾說），"
          "再說看那個視窗的哪一塊（上中下＋左中右，例如「上中」）。只回一行 JSON。")


def region_word(rect) -> str:
    l, t, r, b = rect
    cx, cy = (l + r) / 2, (t + b) / 2
    return ("上" if cy < 0.4 else "下" if cy > 0.6 else "中") + ("左" if cx < 0.4 else "右" if cx > 0.6 else "中")


def visible_windows(sw: int, sh: int) -> list:
    """螢幕上看得到的視窗 [(標題, (左, 上, 右, 下) 比例)]，由上往下疊的順序；她自己的 VTS、太小的、藏起來的不算。"""
    out = []
    try:
        import ctypes
        import ctypes.wintypes as wt
        u = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        Proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

        def cb(h, _):
            if not u.IsWindowVisible(h) or u.IsIconic(h):
                return True
            cloaked = ctypes.c_int(0)
            dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4)   # DWMWA_CLOAKED：別的桌面、藏起來的 UWP
            if cloaked.value:
                return True
            buf = ctypes.create_unicode_buffer(120)
            u.GetWindowTextW(h, buf, 120)
            title = (buf.value or "").strip()
            r = wt.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            if (not title or title == "Program Manager" or "vtube studio" in title.lower()
                    or r.right - r.left < 300 or r.bottom - r.top < 200):
                return True
            rect = (max(0, r.left) / sw, max(0, r.top) / sh, min(sw, r.right) / sw, min(sh, r.bottom) / sh)
            if rect[2] - rect[0] > 0.05 and rect[3] - rect[1] > 0.05:
                out.append((title[:40], rect))
            return len(out) < MAX_WINDOWS
        u.EnumWindows(Proc(cb), 0)
    except Exception:
        log_swallowed()
    return out


def build_menu(windows: list, mouse, hotspot, talking: bool = False) -> tuple:
    """候選清單 → (給 Live 的文字, [(種類, 範圍或點)])。"""
    items, lines = [], []
    for title, rect in windows:
        items.append(("window", rect))
        lines.append(f"{len(items)}：{title}（螢幕{region_word(rect)}）")
    if mouse is not None:
        items.append(("mouse", mouse))
        lines.append(f"{len(items)}：老爸的滑鼠游標（螢幕{region_word((*mouse, *mouse))}）")
    if hotspot is not None:
        items.append(("hotspot", hotspot))
        lines.append(f"{len(items)}：畫面剛有變化的地方（螢幕{region_word((*hotspot, *hotspot))}）")
    items.append(("camera", None))
    lines.append(f"{len(items)}：鏡頭（看觀眾）")
    head = "她現在正在講話。\n" if talking else ""
    return head + "候選：\n" + "\n".join(lines), items


def parse_pick(text: str, items: list):
    """Live 的回答 → (編號, 種類, 看的點或 None, 範圍或 None, 理由)；看不懂回 None。"""
    m = re.search(r"\{.*?\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        idx = int(d.get("pick")) - 1
    except (ValueError, TypeError):
        return None
    if not 0 <= idx < len(items):
        return None
    kind, geo = items[idx]
    why = str(d.get("why") or d.get("what") or "")[:60]
    if kind == "camera":
        return idx, "camera", None, None, why
    if kind in ("mouse", "hotspot"):
        return idx, kind, tuple(geo), None, why
    part = str(d.get("part") or "中中")
    fy = next((v for k, v in _PARTS_Y.items() if part[:1] == k), 0.5)
    fx = next((v for k, v in _PARTS_X.items() if part[1:2] == k), 0.5)
    l, t, r, b = geo
    return idx, "window", (l + (r - l) * fx, t + (b - t) * fy), geo, why


def _jpeg(img) -> bytes:
    img = img.convert("RGB")
    w, h = img.size
    img = img.resize((1280, max(1, int(1280 * h / w))))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


async def gaze_brain_worker() -> None:
    import pyautogui
    import core.llm_engine as le
    import core.stage_state as stage
    import core.usage as usage
    import services.screen_capture as screen_capture
    last_pick = None
    while True:
        try:
            await asyncio.sleep(GAZE_BRAIN_SEC)
            if not (host.IS_PERIPHERAL_VISION_ENABLED and host.IS_FACE_TRACKING_ENABLED) or host.IS_SLEEPING:
                continue
            img = await asyncio.to_thread(screen_capture.grab_screen)
            if img is None:
                continue
            sw, sh = pyautogui.size()
            mx, my = pyautogui.position()
            hs = vc.screen_hotspot
            hotspot = (hs[0], hs[1]) if hs and time.time() - hs[2] < 6 else None
            talking = stage.ai_state() == "TALKING"
            wins = await asyncio.to_thread(visible_windows, sw, sh)
            menu, items = build_menu(wins, (mx / sw, my / sh), hotspot, talking)
            jpg = await asyncio.to_thread(_jpeg, img)
            with usage.as_role("視線副腦"):   # 後台模型用量表才分得出來（以前算在「Live 單次」）
                text = await le.live_one_shot(
                    SYSTEM, f"{menu}\n回 {{\"pick\": 編號, \"part\": \"上中\", \"what\": \"那裡在顯示什麼\", \"why\": \"為什麼想看\"}}",
                    le.GEMINI_KEYS, image_jpeg=jpg, timeout=GAZE_BRAIN_TIMEOUT, max_keys=2)
            picked = parse_pick(text, items)
            if picked is None:
                continue
            idx, kind, point, rect, why = picked
            vc.gaze_intent = {"kind": kind, "point": point, "rect": rect, "why": why, "ts": time.time()}
            name = next((ln.split("：", 1)[1] for ln in menu.splitlines() if ln.startswith(f"{idx + 1}：")), kind)
            if name != last_pick:   # 換了想看的東西才記一筆
                last_pick = name
                log_print(f"👀 [視線副腦] 想看：{name}｜{why}")
        except asyncio.CancelledError:
            raise
        except Exception:
            log_swallowed()
            await asyncio.sleep(5)
