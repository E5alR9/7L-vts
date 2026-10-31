"""她看哪裡（老爸 2026-10-31：視線看起來像亂晃，不像真的看見桌面）。

以前待命、說話時的眼睛照兩條正弦波飄、頭照正弦波擺，跟螢幕上有什麼無關；只有平均每 10 秒看滑鼠 2～4 秒。
現在照真人的看法：盯住一個地方（注視）一會兒，再快速跳到下一個（跳視），要看的地方從桌面上真的發生的事挑——
- 滑鼠在動：老爸在操作，最常看滑鼠，滑鼠一直動就跟著看；
- 剛換前景視窗、或老爸在那個視窗裡做事：看那個視窗（在視窗裡跳幾個點，像在看內容）；
- 畫面上剛有變化的地方（影片、跳出來的通知；餘光比對截圖時找出來的，已遮掉她自己的 VTS 視窗）：瞄一下；
- 她在講話、或沒什麼好看的：看鏡頭（觀眾）。
另外「她想看什麼」由視線副腦決定（workers/gaze_brain：Live 看截圖，從視窗、滑鼠、鏡頭、畫面變化裡挑；同日老爸要的），
有挑就大多照它看，上面這些規則當反射和備援（副腦還沒回、斷線、餘光視覺關著時照規則）。這個模組本身不呼叫 AI。座標一律是「佔主螢幕的比例」（0～1），None 代表看鏡頭（正前方）。
"""
import random
import time
from typing import Optional, Tuple

Point = Optional[Tuple[float, float]]

# 每種注視盯多久（秒）
FIX_SEC = {"camera": (1.8, 4.0), "mouse": (0.8, 2.0), "window": (1.0, 2.5), "hotspot": (0.6, 1.4), "wander": (1.0, 2.5),
           "intent": (1.5, 3.5)}   # 實機 20 秒跳 27 次太忙（2026-10-31），盯久一點
INTENT_FRESH_SEC = 7.0      # 視線副腦（Live 看螢幕挑的）多久內算數
MOUSE_RECENT_SEC = 5.0      # 滑鼠這麼久內動過，才算「老爸在操作」
MOUSE_ONSET_STILL_SEC = 1.0  # 滑鼠停了這麼久又開始動：馬上看過去
WINDOW_RECENT_SEC = 3.0     # 剛換前景視窗
HOTSPOT_RECENT_SEC = 2.5    # 剛有變化的地方
HOTSPOT_REFLEX_GAP_SEC = 6.0   # 畫面變化的反射最多這麼久一次（實機每 2～3 秒被拉走一次，跟副腦挑的輪流搶）


class GazeDirector:
    """每格呼叫 update()，回她現在看的點（比例座標）或 None（看鏡頭）。"""

    def __init__(self, rng: random.Random = None):
        self.rng = rng or random.Random()
        self.kind = "camera"
        self.target: Point = None
        self.until = 0.0
        self.mouse: Point = None
        self.mouse_moved_ts = 0.0
        self._mouse_onset = False   # 滑鼠停了一陣子（或第一次）開始動：update() 會馬上看過去
        self.window = None          # (左, 上, 右, 下) 比例
        self.window_changed_ts = 0.0
        self.hotspot: Point = None
        self.hotspot_ts = 0.0
        self._seen_hotspot_ts = 0.0
        self._seen_window_ts = 0.0
        self.intent = None          # 視線副腦挑的：{"kind", "point", "rect", "ts"}
        self._seen_intent_ts = 0.0
        self._last_hotspot_reflex = -1e9

    # ── 外面餵進來的事 ──
    def note_mouse(self, pt: Point, now: float, moved_px: float = 0.0) -> None:
        if pt is None:
            return
        if moved_px > 6:
            if now - self.mouse_moved_ts > MOUSE_ONSET_STILL_SEC:
                self._mouse_onset = True
            self.mouse_moved_ts = now
        self.mouse = pt

    def note_window(self, rect, now: float) -> None:
        """前景視窗（比例座標）；換了視窗才記時間。"""
        if rect is None:
            self.window = None
            return
        if self.window is None or max(abs(a - b) for a, b in zip(rect, self.window)) > 0.02:
            self.window_changed_ts = now
        self.window = rect

    def note_hotspot(self, pt: Point, now: float) -> None:
        if pt is None:
            return
        # 同一個地方一直在變（播著的影片、跑著的進度條）：不算新的，不再拉她過去瞄（實機：左上角影片一直播，
        # 每次截圖都被當成新變化，20 秒跳 20 幾次）。只更新時間，讓副腦知道那裡還在動
        old = self.hotspot
        if old is not None and now - self.hotspot_ts < 8.0 and abs(pt[0] - old[0]) < 0.12 and abs(pt[1] - old[1]) < 0.12:
            self.hotspot_ts = self._seen_hotspot_ts = now
            return
        self.hotspot, self.hotspot_ts = pt, now

    def note_intent(self, kind: str, point: Point, rect, ts: float) -> None:
        """視線副腦（workers/gaze_brain，Live 看螢幕）挑的「她想看的東西」。
        跟上次挑的一樣就只更新時間、不重新跳過去（副腦每 3 秒回一次，以前每次都跳，實機 20 秒跳 22 次太忙）。"""
        it = self.intent
        same = it is not None and it["kind"] == kind and it.get("rect") == rect and (
            kind != "hotspot" or it.get("point") == point)
        self.intent = {"kind": kind, "point": point if not same else it["point"], "rect": rect, "ts": ts}
        if same:
            self._seen_intent_ts = ts

    def _intent_point(self, now: float) -> Point:
        """照副腦挑的看一眼：視窗就在挑的那一塊附近跳（像在看內容），滑鼠看現在的滑鼠，鏡頭回 None。"""
        it = self.intent
        if it["kind"] == "camera":
            return None
        if it["kind"] == "mouse":
            return self.mouse or it["point"]
        if it["kind"] == "window" and it.get("rect") and it.get("point"):
            l, t, r, b = it["rect"]
            x, y = it["point"]
            return (min(r, max(l, x + self.rng.uniform(-0.12, 0.12) * (r - l))),
                    min(b, max(t, y + self.rng.uniform(-0.1, 0.1) * (b - t))))
        return it["point"]

    def _intent_fresh(self, now: float) -> bool:
        return self.intent is not None and now - self.intent["ts"] < INTENT_FRESH_SEC

    # ── 決定看哪裡 ──
    def _fix(self, kind: str, target: Point, now: float) -> Point:
        lo, hi = FIX_SEC[kind]
        self.kind, self.target, self.until = kind, target, now + self.rng.uniform(lo, hi)
        return target

    def _window_point(self) -> Point:
        """視窗裡的一個點：偏上半部（標題、內容開頭），像在看內容。"""
        l, t, r, b = self.window
        return (self.rng.uniform(l + (r - l) * 0.15, r - (r - l) * 0.15),
                self.rng.uniform(t + (b - t) * 0.1, t + (b - t) * 0.6))

    def update(self, now: float = None, talking: bool = False) -> Point:
        now = time.time() if now is None else now
        mouse_active = self.mouse is not None and now - self.mouse_moved_ts < 0.6
        # 1. 突然的事：馬上跳過去（跳視）
        if mouse_active and self._mouse_onset:
            self._mouse_onset = False
            if self.kind != "mouse":
                return self._fix("mouse", self.mouse, now)
        if self.hotspot is not None and self.hotspot_ts > self._seen_hotspot_ts and now - self.hotspot_ts < HOTSPOT_RECENT_SEC:
            self._seen_hotspot_ts = self.hotspot_ts
            # 講話時、副腦正在挑的時候比較少被分心（副腦自己也看得到「剛有變化的地方」，要看它會挑）
            chance = 0.3 if self._intent_fresh(now) else (0.4 if talking else 1.0)
            if now - self._last_hotspot_reflex >= HOTSPOT_REFLEX_GAP_SEC and self.rng.random() < chance:
                self._last_hotspot_reflex = now
                return self._fix("hotspot", self.hotspot, now)
        if self.window is not None and self.window_changed_ts > self._seen_window_ts \
                and now - self.window_changed_ts < WINDOW_RECENT_SEC:
            self._seen_window_ts = self.window_changed_ts
            return self._fix("window", self._window_point(), now)
        # 1b. 副腦剛挑了新的東西：看過去
        if self._intent_fresh(now) and self.intent["ts"] > self._seen_intent_ts:
            self._seen_intent_ts = self.intent["ts"]
            return self._fix("intent", self._intent_point(now), now)
        # 2. 正在看滑鼠、滑鼠還在動：跟著看
        if self.kind == "mouse" and mouse_active:
            self.target = self.mouse
            self.until = max(self.until, now + 0.5)
            return self.target
        # 3. 這一眼還沒看完
        if now < self.until:
            return self.target
        # 4. 挑下一個地方：副腦有挑就大多照它（講話時一半看鏡頭），其他照規則
        if self._intent_fresh(now) and self.rng.random() < (0.5 if talking else 0.75):
            return self._fix("intent", self._intent_point(now), now)
        choices = []
        mouse_recent = self.mouse is not None and now - self.mouse_moved_ts < MOUSE_RECENT_SEC
        if talking:
            choices.append(("camera", 0.65))
            if mouse_recent:
                choices.append(("mouse", 0.15))
            if self.window is not None:
                choices.append(("window", 0.2))
        else:
            if mouse_recent:
                choices.append(("mouse", 0.4))
            if self.window is not None:
                choices.append(("window", 0.35))
            if self.hotspot is not None and now - self.hotspot_ts < 10.0:
                choices.append(("hotspot", 0.1))
            choices.append(("camera", 0.15))
            choices.append(("wander", 0.1))
        kinds, weights = zip(*choices)
        kind = self.rng.choices(kinds, weights)[0]
        if kind == "mouse":
            return self._fix("mouse", self.mouse, now)
        if kind == "window":
            return self._fix("window", self._window_point(), now)
        if kind == "hotspot":
            return self._fix("hotspot", self.hotspot, now)
        if kind == "wander":   # 發呆：隨便看一個不遠的地方
            base = self.target or (0.5, 0.5)
            return self._fix("wander", (min(1.0, max(0.0, base[0] + self.rng.uniform(-0.15, 0.15))),
                                        min(1.0, max(0.0, base[1] + self.rng.uniform(-0.1, 0.1)))), now)
        return self._fix("camera", None, now)


def look_angles(target: Point, cx: float, cy: float) -> Tuple[float, float]:
    """看的點 → 頭／眼睛的角度（跟看滑鼠同一套：以她 VTS 視窗中心為 0，左右 ×28、上下 ×-20）；看鏡頭是 (0, 0)。"""
    if target is None:
        return 0.0, 0.0
    return (target[0] - cx) * 28.0, (target[1] - cy) * -20.0


def hotspot_from_diff(diff_gray, mask=None, min_mean: float = 14.0) -> Point:
    """兩張縮圖的差（灰階二維陣列，0～255）→ 變化最大那一塊的中心（比例座標）；沒什麼變化回 None。
    mask：同大小的布林陣列，True 的地方不算（她自己的 VTS 視窗）。"""
    import numpy as np
    d = np.asarray(diff_gray, dtype=np.float32)
    if d.ndim != 2 or d.size == 0:
        return None
    if mask is not None:
        d = np.where(np.asarray(mask, dtype=bool), 0.0, d)
    h, w = d.shape
    k = 3   # 3x3 加總，找一整塊在變的，不是單一雜點
    padded = np.pad(d, 1)
    s = sum(padded[i:i + h, j:j + w] for i in range(k) for j in range(k)) / (k * k)
    y, x = np.unravel_index(int(np.argmax(s)), s.shape)
    if s[y, x] < min_mean:
        return None
    return ((x + 0.5) / w, (y + 0.5) / h)
