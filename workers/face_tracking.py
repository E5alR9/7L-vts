# -*- coding: utf-8 -*-
"""臉部追蹤：沒有真人臉部追蹤時，讓 7L 的頭、眼睛、身體自己動（呼吸、眨眼、看滑鼠、彈琴時看琴鍵）。

主程式的狀態經 host.<名稱> 即時讀寫（host＝主程式模組，主程式 import 本檔後 bind()）。
用到的名稱列在 HOST_ATTRS，tests/test_workers_host.py 核對主程式真的都有定義。
"""
import asyncio
import math
import random
import time

import pyautogui

import core.stage_state as stage
import services.piano_engine as pe
import services.vts_client as vc
from core.gaze import GazeDirector, look_angles
from core.utils import log_print, log_swallowed

HOST_ATTRS = (
    "CURRENT_PLAYING_VOICE_TASK",
    "IS_FACE_TRACKING_ENABLED",
    "IS_SLEEPING",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


AI_FACE_TRACKING_RUNNING = False


def _foreground_rect(sw: int, sh: int):
    """前景視窗的範圍（比例座標）；是她自己的 VTS、桌面、最小化、太小、拿不到就回 None。
    桌面（Program Manager）以前也算：整個螢幕都是「前景視窗」，她在全螢幕隨機挑點看，像亂晃（2026-10-31 實機）。"""
    try:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd or user32.IsIconic(hwnd):
            return None
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if "vtube studio" in (buf.value or "").lower() or cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return None
        r = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)) or r.right - r.left < 150 or r.bottom - r.top < 100:
            return None
        return (max(0.0, r.left / sw), max(0.0, r.top / sh), min(1.0, r.right / sw), min(1.0, r.bottom / sh))
    except Exception:
        return None


async def ai_face_tracking_loop(vts):
    global AI_FACE_TRACKING_RUNNING
    if AI_FACE_TRACKING_RUNNING:
        log_print("⚠️ [VTS 追蹤] 檢測到已存在運行的 ai_face_tracking_loop 實例，略過重複啟動以杜絕抖動衝突。")
        return
    AI_FACE_TRACKING_RUNNING = True
    try:
        await _ai_face_tracking_loop_impl(vts)
    finally:
        AI_FACE_TRACKING_RUNNING = False


async def _ai_face_tracking_loop_impl(vts):
    t = 0.0
    blink_timer = time.time() + random.uniform(3.5, 6.0)
    blink_start_time = 0.0
    is_blinking = False
    smooth_sleep_eye = 1.0  #  休眠閉眼平滑過渡因子 (1.0 清醒睜眼 -> 0.0 閉眼安睡)

    curr_x, curr_y, curr_z = 0.0, 0.0, 0.0
    curr_eye_x, curr_eye_y = 0.0, 0.0
    smooth_piano_focus_x = 0.0
    # 待命、說話時看哪裡：盯住一個地方一會兒再跳到下一個，從滑鼠、前景視窗、畫面變化、鏡頭裡挑（core/gaze；老爸 2026-10-31：
    # 以前眼睛照正弦波飄、平均每 10 秒才看一次滑鼠，看起來像亂晃，不像真的看見桌面）
    gaze = GazeDirector()
    last_mouse = None
    last_win_poll = 0.0
    seen_hotspot_ts = 0.0
    seen_intent_ts = 0.0
    micro_x = micro_y = micro_until = 0.0

    while True:
        try:
            if not host.IS_FACE_TRACKING_ENABLED:
                await asyncio.sleep(0.5)
                continue
            now = time.time()
            is_playing = False
            try:
                is_playing = stage.voice_out()
            except Exception:
                log_swallowed()

            sw, sh = pyautogui.size()
            px, py = pyautogui.position()
            #  以 7L 的 VTS 視窗中心為基準（每 3 秒查一次），看的點都換算成相對她的角度
            vc._vts_win_cx, vc._vts_win_cy = await vc.update_vts_window_center(sw, sh)
            moved = 0.0 if last_mouse is None else math.hypot(px - last_mouse[0], py - last_mouse[1])
            last_mouse = (px, py)
            gaze.note_mouse((px / sw, py / sh), now, moved)
            if now - last_win_poll > 0.3:
                last_win_poll = now
                gaze.note_window(_foreground_rect(sw, sh), now)
            hs = vc.screen_hotspot
            if hs and hs[2] > seen_hotspot_ts:
                seen_hotspot_ts = hs[2]
                gaze.note_hotspot((hs[0], hs[1]), hs[2])
            gi = vc.gaze_intent   # 視線副腦（Live 看螢幕）挑的
            if gi and gi["ts"] > seen_intent_ts:
                seen_intent_ts = gi["ts"]
                gaze.note_intent(gi["kind"], gi["point"], gi["rect"], gi["ts"])

            state = stage.ai_state()
            gaze_mode = (not vc.is_tracking_mouse and not host.IS_SLEEPING and not pe.is_piano_active_and_alive()
                         and state in ("IDLE", "TALKING"))
            is_currently_tracking = vc.is_tracking_mouse
            if vc.is_tracking_mouse:   # [LOOK: MOUSE]：一直盯著滑鼠
                vc.target_look_x, vc.target_look_y = look_angles((px / sw, py / sh), vc._vts_win_cx, vc._vts_win_cy)
            elif gaze_mode:
                vc.target_look_x, vc.target_look_y = look_angles(
                    gaze.update(now, talking=is_playing or state == "TALKING"), vc._vts_win_cx, vc._vts_win_cy)
                vc.gaze_kind = gaze.kind   # 她現在為什麼看那裡（後台、除錯看）
            else:
                vc.target_look_x, vc.target_look_y = 0.0, 0.0

            vc.current_look_x += (vc.target_look_x - vc.current_look_x) * 0.08
            vc.current_look_y += (vc.target_look_y - vc.current_look_y) * 0.08

            #  檢測休眠狀態：若休眠則眼睛平滑閉合為 0.0；若喚醒則平滑睜眼至 1.0
            if host.IS_SLEEPING:
                smooth_sleep_eye = max(0.0, smooth_sleep_eye - 0.08)
            else:
                smooth_sleep_eye = min(1.0, smooth_sleep_eye + 0.12)

            #  眼睛開合計算 (休眠模式強制閉眼 0.0；清醒模式正常眨眼)
            if host.IS_SLEEPING:
                eye_open_left = smooth_sleep_eye
                eye_open_right = smooth_sleep_eye
                is_blinking = False
            else:
                #  自然真實眨眼機制 (每 3.5~6.5 秒眨眼一次，閉眼時間精確為 0.14 秒，徹底杜絕快速連眨)
                eye_open_left = smooth_sleep_eye
                eye_open_right = smooth_sleep_eye
                if vc.force_blink_trigger > 0:
                    if not is_blinking:
                        is_blinking = True
                        blink_start_time = now
                        vc.force_blink_trigger = 0
                elif not is_blinking and now > blink_timer:
                    is_blinking = True
                    blink_start_time = now

                if is_blinking:
                    if now - blink_start_time < 0.14:
                        eye_open_left = 0.0
                        eye_open_right = 0.0
                    else:
                        eye_open_left = smooth_sleep_eye
                        eye_open_right = smooth_sleep_eye
                        is_blinking = False
                        blink_timer = now + random.uniform(3.5, 6.5)
                else:
                    eye_open_left = smooth_sleep_eye
                    eye_open_right = smooth_sleep_eye

            #  靈動眼珠與鋼琴音符密集處視線追蹤計算
            if vc.eye_roll_timer > now:
                #  招牌靈動大轉眼珠 / 大圈環視四周 (俐落 360° 滿幅滿力道 1.0 大圓周軌跡)
                target_eye_x = math.sin(t * 4.2) * 1.0
                target_eye_y = math.cos(t * 4.2) * 1.0
                curr_eye_x = target_eye_x
                curr_eye_y = target_eye_y
            elif pe.is_piano_active_and_alive():
                #  只要處於鋼琴彈奏狀態中：眼神永遠精準朝下追蹤琴鍵音符密集重心
                smooth_piano_focus_x += (pe.PIANO_NOTE_FOCUS_X - smooth_piano_focus_x) * 0.25
                target_eye_x = max(-0.85, min(0.85, smooth_piano_focus_x / 16.0))
                target_eye_y = -0.75
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            elif is_currently_tracking:
                # 滑鼠游標注視
                target_eye_x = max(-0.85, min(0.85, vc.current_look_x / 20.0))
                target_eye_y = max(-0.85, min(0.85, vc.current_look_y / 15.0))
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            elif stage.ai_state() == "THINKING":
                # 思考中視線往斜上方
                target_eye_x = -0.38
                target_eye_y = 0.55
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            elif gaze_mode:
                # 待命/說話時：眼睛快速跳到要看的點（頭比較慢才跟上）。盯著的時候不晃，偶爾偏一點點（微跳視）。
                # 以前用兩條正弦波做微顫，合起來是一個小橢圓，視線游標繞著焦點轉圈（2026-10-31 老爸實機看到）
                if now >= micro_until:
                    micro_x, micro_y = random.uniform(-0.006, 0.006), random.uniform(-0.005, 0.005)
                    micro_until = now + random.uniform(0.6, 1.6)
                target_eye_x = max(-0.85, min(0.85, vc.target_look_x / 20.0 + micro_x))
                target_eye_y = max(-0.85, min(0.85, vc.target_look_y / 15.0 + micro_y))
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.35
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.35
            else:
                target_eye_x = math.sin(t * 0.9) * 0.3
                target_eye_y = math.cos(t * 0.65) * 0.15
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.13
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.13

            target_angle_x = 0.0
            target_angle_y = 0.0
            target_angle_z = 0.0
            target_mouth = 0.0

            #  真實音訊波形精準對嘴：完全根據音訊逐幀 RMS 振幅與快開慢合物理平滑決定！
            if is_playing:
                if stage.CURRENT_MOUTH_ENVELOPE and stage.CURRENT_SPEECH_START_TIME > 0:
                    elapsed = now - stage.CURRENT_SPEECH_START_TIME
                    frame_idx = int(elapsed * 25.0)
                    if 0 <= frame_idx < len(stage.CURRENT_MOUTH_ENVELOPE):
                        raw_target = stage.CURRENT_MOUTH_ENVELOPE[frame_idx]
                    else:
                        raw_target = 0.0

                    #  快開慢合 (Fast Attack 0.65, Gentle Release 0.35) 物理濾波，徹底告別卡頓與僵硬
                    if raw_target > stage.CURRENT_SMOOTH_MOUTH:
                        stage.CURRENT_SMOOTH_MOUTH += (raw_target - stage.CURRENT_SMOOTH_MOUTH) * 0.65
                    else:
                        stage.CURRENT_SMOOTH_MOUTH += (raw_target - stage.CURRENT_SMOOTH_MOUTH) * 0.35
                    target_mouth = round(stage.CURRENT_SMOOTH_MOUTH, 3)
                else:
                    #  若無真實音訊波形包絡 (如生成等待、句間分段間隙)，自然平滑閉合嘴巴，避免無聲時空動嘴！
                    stage.CURRENT_SMOOTH_MOUTH *= 0.35
                    target_mouth = round(stage.CURRENT_SMOOTH_MOUTH, 3)
            else:
                stage.CURRENT_SMOOTH_MOUTH = 0.0
                target_mouth = 0.0

            # 姿態與頭部運動計算
            if pe.is_piano_active_and_alive():
                #  鋼琴彈奏中：頭部與身體重心專注在鍵盤，隨音符高低音律動傾斜（說話時僅動嘴，姿態不變）
                smooth_piano_focus_x += (pe.PIANO_NOTE_FOCUS_X - smooth_piano_focus_x) * 0.25
                target_angle_x = smooth_piano_focus_x * 0.65 + math.sin(t * 1.2) * 2.5
                target_angle_y = -10.0 + math.cos(t * 1.5) * 1.5
                target_angle_z = smooth_piano_focus_x * 0.30 + math.sin(t * 1.0) * 2.0
            elif is_playing:
                #  MP3 播放中：頭部溫和自然微幅呼吸點頭
                target_angle_x = math.sin(t * 1.0) * 1.5 + vc.current_look_x * 0.45
                target_angle_y = math.cos(t * 0.8) * 0.8 + vc.current_look_y * 0.35
                target_angle_z = math.sin(t * 0.7) * 1.0
            elif is_currently_tracking:
                target_angle_x = vc.current_look_x
                target_angle_y = vc.current_look_y
                target_angle_z = 0.0
            else:
                if host.IS_SLEEPING:
                    #  沉睡休眠安詳姿態：頭微低下垂 (-8.5度)，伴隨均勻舒緩的深層呼吸起伏
                    sleep_breath = math.sin(t * 0.45)
                    target_angle_x = math.sin(t * 0.25) * 1.0
                    target_angle_y = -8.5 + sleep_breath * 0.8
                    target_angle_z = 1.5 + math.sin(t * 0.3) * 0.8
                elif stage.ai_state() == "IDLE":
                    # 待命時：頭跟著看的方向轉一半，只留一點自然擺動（以前大幅正弦擺頭，看起來像亂晃）
                    target_angle_x = math.sin(t * 0.42) * 1.2 + vc.current_look_x * 0.5
                    target_angle_y = math.cos(t * 0.32) * 0.6 + vc.current_look_y * 0.4
                    target_angle_z = math.sin(t * 0.3) * 1.5
                elif stage.ai_state() == "THINKING":
                    target_angle_x = -2.0 + vc.current_look_x * 0.2
                    target_angle_y = 2.0 + vc.current_look_y * 0.2
                    target_angle_z = 4.5
                elif stage.ai_state() == "TALKING":
                    # 說話時：加入自然語感搖頭韻律（像說話時帶的肢體動作），幅度不誇張但明顯活潑
                    target_angle_x = math.sin(t * 1.1) * 2.5 + vc.current_look_x * 0.55
                    target_angle_y = math.cos(t * 0.75) * 1.2 + vc.current_look_y * 0.35
                    target_angle_z = math.sin(t * 0.85) * 1.8

            if vc.eye_roll_timer > now:
                target_angle_z += math.sin(t * 4.2) * 3.5
                target_angle_y += math.cos(t * 4.2) * 2.0

            #  純物理動力學縮小瞳孔與震驚 (EyeOpen=2.0 瞪大縮瞳 + 自然呼吸微顫抖)
            #  發話期間若有物理表情，持續延長鎖定，確保說話全程不中途褪去
            if host.CURRENT_PLAYING_VOICE_TASK is not None:
                if vc.shock_timer > now:
                    vc.shock_timer = max(vc.shock_timer, now + 1.0)
                if vc.frown_timer > now:
                    vc.frown_timer = max(vc.frown_timer, now + 1.0)

            is_in_shock = (vc.shock_timer > now)
            is_frowning = (vc.frown_timer > now)

            #  徹底防呆：時效結束時立即歸零重置，絕不殘留！
            if not is_in_shock and vc.shock_timer > 0:
                vc.shock_timer = 0.0
            if not is_frowning and vc.frown_timer > 0:
                vc.frown_timer = 0.0

            if is_in_shock:
                eye_open_left = 2.0
                eye_open_right = 2.0
                target_brows = 0.85
                target_mouth_smile = 0.35
                if not is_playing:
                    target_mouth = 0.20  # 震驚未發話時微張嘴 (呆滯/倒抽氣)；發話時保持正常對嘴開合
                target_angle_x += math.sin(t * 12.0) * 0.20
                target_angle_y += math.sin(t * 10.0) * 0.15
                target_angle_z += math.cos(t * 11.0) * 0.20
                curr_eye_x += math.sin(t * 8.0) * 0.02
                curr_eye_y += math.cos(t * 7.0) * 0.02
            elif is_frowning:
                #  困擾/委屈 皺眉表情 (Brows = 0.0 壓低眉毛形成八字皺眉 + 微撇嘴/微嘟嘴)
                eye_open_left = 0.95
                eye_open_right = 0.95
                target_brows = 0.0
                target_mouth_smile = 0.25
                target_angle_z += math.sin(t * 1.5) * 2.0
                target_angle_y += -1.5
            elif vc.wink_timer > now:
                #  俏皮靈動單邊眨一下眼 (Wink: 總時長 0.55 秒，眨一下立即順暢張開)
                elapsed_wink = 0.55 - (vc.wink_timer - now)
                if elapsed_wink < 0.10:
                    wink_eye_open = max(0.0, 1.0 - (elapsed_wink / 0.10))
                elif elapsed_wink <= 0.32:
                    wink_eye_open = 0.0
                else:
                    wink_eye_open = min(1.0, (elapsed_wink - 0.32) / 0.23)

                if vc.wink_side == "left":
                    eye_open_left = wink_eye_open
                    eye_open_right = 1.0
                    target_angle_z += 3.5 * (1.0 - wink_eye_open)
                else:
                    eye_open_left = 1.0
                    eye_open_right = wink_eye_open
                    target_angle_z += -3.5 * (1.0 - wink_eye_open)
                target_brows = 0.50
                target_mouth_smile = 0.50 + 0.35 * (1.0 - wink_eye_open)
            else:
                #  平時自然溫和中性眉毛 (0.50) 與自然微笑 (0.50，發話時隨開口度靈動上揚)
                target_brows = 0.50
                target_mouth_smile = min(1.0, 0.50 + 0.20 * target_mouth) if is_playing else 0.50

            curr_x += (target_angle_x - curr_x) * 0.10
            curr_y += (target_angle_y - curr_y) * 0.10
            curr_z += (target_angle_z - curr_z) * 0.10

            vc.gaze_eye_x, vc.gaze_eye_y = curr_eye_x, curr_eye_y   # 視線游標（workers/gaze_cursor.py）看這個
            param_values = [
                {"id": "FaceAngleX", "value": curr_x, "weight": 1.0},
                {"id": "FaceAngleY", "value": curr_y, "weight": 1.0},
                {"id": "FaceAngleZ", "value": curr_z, "weight": 1.0},
                {"id": "EyeLeftX", "value": -curr_eye_x, "weight": 1.0},  # Invert X for correct eye tracking relative to head
                {"id": "EyeLeftY", "value": curr_eye_y, "weight": 1.0},
                {"id": "EyeRightX", "value": -curr_eye_x, "weight": 1.0}, # Invert X for correct eye tracking relative to head
                {"id": "EyeRightY", "value": curr_eye_y, "weight": 1.0},
                {"id": "EyeOpenLeft", "value": eye_open_left, "weight": 1.0},
                {"id": "EyeOpenRight", "value": eye_open_right, "weight": 1.0},
                {"id": "Brows", "value": target_brows, "weight": 1.0},
                {"id": "MouthSmile", "value": target_mouth_smile, "weight": 1.0},
                {"id": "MouthOpen", "value": target_mouth, "weight": 1.0}
            ]

            if hasattr(vts, 'inject_parameters'):
                await vts.inject_parameters(param_values)
            else:
                vts_data = {
                    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "AIStateTracking",
                    "messageType": "InjectParameterDataRequest",
                    "data": {
                        "faceFound": True,
                        "mode": "set",
                        "parameterValues": param_values
                    }
                }
                async with vc.vts_lock:
                    await asyncio.wait_for(vts.request(vts_data), timeout=0.5)

            t = (t if isinstance(t, (int, float)) else 0.0) + 0.08
        except Exception:
            t = 0.0

        await asyncio.sleep(0.04)
