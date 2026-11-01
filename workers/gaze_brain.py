# -*- coding: utf-8 -*-
"""視線副腦：用 Live 看螢幕，決定她現在「想看什麼」（老爸 2026-10-31：用 api live 真的就是她想看的位置，不是單純規則）。

實測（同日）：直接叫 Live 回座標不可靠——她的臉在 (611, 860) 它回 (850, 850)，好幾次回畫面正中央。
後來改成挑視窗＋九宮格，臉部追蹤再在那附近隨機抖，看起來還是亂晃（老爸 2026-11-01：給她網格，讓她選要看哪格）。
現在截圖畫 8x6 網格（每格寫格名），提示詞列每個視窗佔哪幾格、滑鼠在哪格、剛變化的格；Live 回 1～3 個格名
（依序看）、「滑鼠」或「鏡頭」，臉部追蹤就看那格的中心，不再隨機抖。之前不準其實是圖走即時影像串流、解析度太低，
看不清楚；改成跟問題同一則訊息＋高解析度後，紅圈測試 8x6 六次全對（core.llm_engine.live_one_shot）。

結果放在 vc.gaze_intent，臉部追蹤交給 core.gaze 當注視目標（反射——滑鼠突然動、畫面跳通知——照樣會打斷）。
只在餘光視覺開著、臉部追蹤開著、沒睡著時跑；截圖走 services.screen_capture（測試包裝擋截圖時拿到 None，自動不跑）。
主程式的狀態經 host.<名稱> 即時讀（host＝主程式模組，主程式 import 本檔後 bind()）。
"""
import asyncio
import io
import json
import random
import re
import time

import services.vts_client as vc
import workers.gaze_cursor as gaze_cursor
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
GAZE_BRAIN_BACKOFF_MAX = 60.0  # 連續問不到（Live 壞了、key 都被限流）最多隔這麼久再問
MAX_WINDOWS = 8
# 截圖上畫的網格（老爸 2026-11-01：給她網格，讓她選要看畫面上哪一格，不是函數亂晃）。
# 實測（同日紅圈測試，圖跟問題同一則訊息＋高解析度）：8x6 六次全對、12x8 只對一半，所以用 8x6
GRID_COLS, GRID_ROWS = 8, 6
GRID_LETTERS = "ABCDEFGH"
GRID_FONT_PX = 34
MAX_LOOKS = 3                  # 一次最多挑幾格（依序看）
_CELL_RE = re.compile(r"(?<![A-Za-z])([A-Ha-h])\s*([1-6])(?!\d)")   # 「C3」「c 3」；不認「A12」「Chrome1」
GRID_LINE_RGBA = (0, 200, 255, 170)   # 青色格線：不跟她的桃紅色視線游標同色（Fable）

SYSTEM = ("妳是 7L 的眼睛：7L 是坐在老爸電腦旁的虛擬女兒，看得到老爸的螢幕。截圖上畫了 8x6 的青色格線，"
          "每格左上角的黃字是格名（字母 A～H 是直行、由左到右，數字 1～6 是橫列、由上到下）；格線和黃字是程式畫的，不是畫面內容。"
          "看截圖，挑妳現在最想看的地方（老爸正在做的事、剛出現的東西、有趣的東西；她在講話時多半看鏡頭）："
          "回 1～3 個格名（會依序看過去，像在看一段內容），或「滑鼠」（跟著老爸的滑鼠看），"
          "或「鏡頭」（看正前方、看著跟她說話的人：平常就是老爸，沒開直播就沒有觀眾，不要寫成在看觀眾）。只回一行 JSON。")
# （老爸 2026-11-01：實機副腦理由寫「講話時要專注看著觀眾」，其實只有老爸在——平時她就是女兒，不是在直播）


def cell_name(x: float, y: float) -> str:
    """比例座標 → 格名（A1 是左上角）。"""
    c = min(GRID_COLS - 1, max(0, int(x * GRID_COLS)))
    r = min(GRID_ROWS - 1, max(0, int(y * GRID_ROWS)))
    return f"{GRID_LETTERS[c]}{r + 1}"


def cell_center(name: str):
    """格名 → 那格中心的比例座標；不是格名回 None。"""
    m = _CELL_RE.fullmatch((name or "").strip())
    if not m:
        return None
    c, r = GRID_LETTERS.index(m.group(1).upper()), int(m.group(2)) - 1
    return ((c + 0.5) / GRID_COLS, (r + 0.5) / GRID_ROWS)


def cell_span(rect) -> str:
    """範圍 → 「C1～H4」這樣的格子範圍（一格就只寫一格）。"""
    l, t, r, b = rect
    a, z = cell_name(l, t), cell_name(max(l, r - 1e-6), max(t, b - 1e-6))
    return a if a == z else f"{a}～{z}"


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


def build_prompt(windows: list, mouse, hotspot, talking: bool = False) -> str:
    """給 Live 的文字：每個視窗佔哪幾格、滑鼠在哪格、剛有變化的格、她是不是在講話。"""
    lines = ["她現在正在講話。"] if talking else []
    if windows:
        lines.append("畫面上的視窗（上面的蓋住下面的）：")
        lines += [f"- {title}（{cell_span(rect)}）" for title, rect in windows]
    if mouse is not None:
        lines.append(f"老爸的滑鼠在 {cell_name(*mouse)}。")
    if hotspot is not None:
        lines.append(f"畫面剛有變化的地方在 {cell_name(*hotspot)}。")
    lines.append('回 {"look": ["C3", "D3"] 或 "滑鼠" 或 "鏡頭", "what": "那裡在顯示什麼", "why": "為什麼想看"}')
    return "\n".join(lines)


def parse_look(text: str):
    """Live 的回答 → (種類, [看的點], [格名], 理由)；種類是 grid／mouse／camera。看不懂回 None。"""
    d = None
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            d = json.loads(m.group(0))
        except ValueError:
            d = None
    if isinstance(d, dict):
        look = d.get("look")
        why = str(d.get("why") or d.get("what") or "")[:60]
        words = [str(w or "") for w in (look if isinstance(look, list) else [look])]
    else:
        # 轉寫偶爾掉大括號、或只回一句話：在「look」後面那段找（沒有就整句）
        tail = re.split(r"look", text or "", maxsplit=1, flags=re.I)
        seg = re.split(r"what|why", tail[-1], maxsplit=1, flags=re.I)[0]
        words, why = [seg], ""
    # 照第一個說的算（「C3 再看滑鼠」是看 C3）；格名在字裡任何地方都認（「E1～H3」「C3, D3」）
    cells = []
    for w in words:
        hits = [(mm.start(), f"{mm.group(1).upper()}{mm.group(2)}") for mm in _CELL_RE.finditer(w)]
        firsts = [(w.find(k), kind) for k, kind in (("鏡頭", "camera"), ("滑鼠", "mouse")) if k in w]
        if not cells and firsts and (not hits or min(firsts)[0] < hits[0][0]):
            return min(firsts)[1], [], [], why
        for _, name in hits:
            if name not in cells:
                cells.append(name)
    if not cells:
        return None
    cells = cells[:MAX_LOOKS]
    return "grid", [cell_center(c) for c in cells], cells, why


def _font(px: int):
    from PIL import ImageFont
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def grid_jpeg(img) -> bytes:
    """截圖縮成 1280 寬、畫上 8x6 格線，每格左上角寫格名（黃字黑邊，跟紅圈測試同一套）。"""
    from PIL import Image, ImageDraw
    img = img.convert("RGB")
    w, h = 1280, max(1, int(1280 * img.height / img.width))
    img = img.resize((w, h))
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for c in range(1, GRID_COLS):
        d.line([(w * c / GRID_COLS, 0), (w * c / GRID_COLS, h)], fill=GRID_LINE_RGBA, width=3)
    for r in range(1, GRID_ROWS):
        d.line([(0, h * r / GRID_ROWS), (w, h * r / GRID_ROWS)], fill=GRID_LINE_RGBA, width=3)
    f = _font(GRID_FONT_PX)
    for c in range(GRID_COLS):
        for r in range(GRID_ROWS):
            d.text((w * c / GRID_COLS + 4, h * r / GRID_ROWS + 3), f"{GRID_LETTERS[c]}{r + 1}", font=f,
                   fill=(255, 255, 0, 255), stroke_width=4, stroke_fill=(0, 0, 0, 255))
    out = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def gaze_brain_worker() -> None:
    import pyautogui
    import core.llm_engine as le
    import core.stage_state as stage
    import core.usage as usage
    import services.screen_capture as screen_capture
    last_pick = None
    misses = 0
    bad_logged = 0.0
    while True:
        try:
            # 連續問不到就拉長間隔（3→6→12…最多 60 秒）：以前每 3 秒照樣試兩把 key，Live 壞掉時一直燒、也沒日誌（Fable 審查）
            await asyncio.sleep(min(GAZE_BRAIN_BACKOFF_MAX, GAZE_BRAIN_SEC * (2 ** min(misses, 5))))
            if not (host.IS_PERIPHERAL_VISION_ENABLED and host.IS_FACE_TRACKING_ENABLED) or host.IS_SLEEPING:
                continue
            img = await asyncio.to_thread(screen_capture.grab_screen)
            if img is None:
                continue
            sw, sh = pyautogui.size()
            mx, my = pyautogui.position()
            hs = vc.screen_hotspot
            hotspot = (hs[0], hs[1]) if hs and time.time() - hs[2] < 6 else None
            talking = stage.voice_out() or stage.ai_state() == "TALKING"   # 跟臉部追蹤同一個「在講話」
            mouse = (mx / sw, my / sh)
            if not (0.0 <= mouse[0] < 1.0 and 0.0 <= mouse[1] < 1.0):
                mouse = None   # 滑鼠在別的螢幕：截圖（只有主螢幕）上沒有，不要跟她說在 A 欄／H 欄（Fable）
            wins = await asyncio.to_thread(visible_windows, sw, sh)
            prompt = build_prompt(wins, mouse, hotspot, talking)
            jpg = await asyncio.to_thread(grid_jpeg, img)
            # key 每次隨機排（挑 key 是穩定排序，以前永遠打全池第一把空著的，負載全壓在同一把；Fable 審查），一次只試一把
            with usage.as_role("視線副腦"):   # 後台模型用量表才分得出來（以前算在「Live 單次」）
                text = await le.live_one_shot(
                    SYSTEM + gaze_cursor.capture_note(), prompt,
                    random.sample(le.GEMINI_KEYS, len(le.GEMINI_KEYS)), image_jpeg=jpg,
                    timeout=GAZE_BRAIN_TIMEOUT, max_keys=1)
            if not text:   # Live 沒回（連不上、限流）：才拉長間隔
                misses += 1
                continue
            misses = 0
            picked = parse_look(text)
            if picked is None:   # 有回但看不懂：不拉長間隔（以前跟連不上一起退避，偶爾答成一句話就被節流到 60 秒；Fable）
                if time.time() - bad_logged > 60:
                    bad_logged = time.time()
                    log_print(f"⚠️ [視線副腦] 看不懂這次的回答：{text[:60]}")
                continue
            kind, points, cells, why = picked
            if kind == "mouse" and mouse is None:
                continue
            vc.gaze_intent = {"kind": kind, "points": points, "cells": cells, "why": why, "ts": time.time(),
                              "talking": talking}
            name = "→".join(cells) if cells else ("老爸的滑鼠" if kind == "mouse" else "鏡頭")
            if name != last_pick:   # 換了想看的地方才記一筆
                last_pick = name
                log_print(f"👀 [視線副腦] 想看：{name}｜{why}")
        except asyncio.CancelledError:
            raise
        except Exception:
            log_swallowed()
            await asyncio.sleep(5)
