            if current_ai_state == "IDLE" and not is_playing and not vc.is_tracking_mouse:
                if auto_mouse_track_timer > 0:
                    auto_mouse_track_timer -= 0.05
                    if auto_mouse_track_timer <= 0:
                        vc.target_look_x = 0.0
                        vc.target_look_y = 0.0
                else:
                    if random.random() < 0.005:  
                        auto_mouse_track_timer = random.uniform(2.0, 4.0)  
            else:
                if auto_mouse_track_timer > 0:
                    auto_mouse_track_timer = 0.0
                    if not vc.is_tracking_mouse:
                        vc.target_look_x = 0.0
                        vc.target_look_y = 0.0

            is_currently_tracking = vc.is_tracking_mouse or auto_mouse_track_timer > 0

            if is_currently_tracking:
                sw, sh = pyautogui.size()
                px, py = pyautogui.position()
                
                #  以 7L 的 VTS 視窗中心為基準，修正視線相對於螢幕中心的偏差
                # 自動偵測 VTube Studio 視窗位置（每 3 秒更新一次）
                if not hasattr(vc, '_vts_win_cx') or now - getattr(vc, '_vts_win_last_update', 0) > 3.0:
                    found_win = None
                    try:
                        import pygetwindow as gw
                        for w in gw.getAllWindows():
                            if w.visible and w.width > 150 and w.height > 150:
                                win_t = (w.title or "").lower()
                                if 'vtube' in win_t or 'vts' in win_t:
                                    found_win = (w.left + w.width / 2, w.top + w.height / 2)
                                    break
                    except Exception:
                        pass
                    
                    if not found_win:
                        try:
                            import ctypes, ctypes.wintypes
                            user32 = ctypes.windll.user32
                            found = []
                            def enum_cb(hwnd, _):
                                if user32.IsWindowVisible(hwnd):
                                    buf = ctypes.create_unicode_buffer(256)
                                    user32.GetWindowTextW(hwnd, buf, 256)
                                    title = (buf.value or "").lower()
                                    if 'vtube' in title or 'vts' in title:
                                        rect = ctypes.wintypes.RECT()
                                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                                        w = rect.right - rect.left
                                        h = rect.bottom - rect.top
                                        if w > 150 and h > 150:
                                            cx = (rect.left + rect.right) / 2
                                            cy = (rect.top + rect.bottom) / 2
                                            found.append((cx, cy))
                                return 1
                            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
                            if found:
                                found_win = found[0]
                        except Exception:
                            pass

                    if found_win:
                        vc._vts_win_cx = found_win[0] / sw  # 0.0~1.0 normalized
                        vc._vts_win_cy = found_win[1] / sh
                    elif not hasattr(vc, '_vts_win_cx'):
                        vc._vts_win_cx = 0.5
                        vc._vts_win_cy = 0.5
                    vc._vts_win_last_update = now
                
                # 以 7L 的視窗中心為參考點，計算滑鼠相對位置（往左為負，往右為正）
                nx = (px / sw) - vc._vts_win_cx  # 以 VTS 視窗 X 為 0 點
                ny = (py / sh) - vc._vts_win_cy
                vc.target_look_x, vc.target_look_y = nx * 28.0, ny * -20.0

            vc.current_look_x += (vc.target_look_x - vc.current_look_x) * 0.08
            vc.current_look_y += (vc.target_look_y - vc.current_look_y) * 0.08

            #  檢測休眠狀態：若休眠則眼睛平滑閉合為 0.0；若喚醒則平滑睜眼至 1.0
            if IS_SLEEPING:
                smooth_sleep_eye = max(0.0, smooth_sleep_eye - 0.08)
            else:
                smooth_sleep_eye = min(1.0, smooth_sleep_eye + 0.12)

            #  眼睛開合計算 (休眠模式強制閉眼 0.0；清醒模式正常眨眼)
            if IS_SLEEPING:
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
            elif current_ai_state == "THINKING":
                # 思考中視線往斜上方
                target_eye_x = -0.38
                target_eye_y = 0.55
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.15
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.15
            else:
                # 待命/說話時：更自然靈動的左右眼神飄移（幅度加大，像真正說話時的眼神流動）
                target_eye_x = math.sin(t * 0.9) * 0.55 + (vc.current_look_x / 28.0) * 0.55
                target_eye_y = math.cos(t * 0.65) * 0.28 + (vc.current_look_y / 20.0) * 0.4
                curr_eye_x += (target_eye_x - curr_eye_x) * 0.13
                curr_eye_y += (target_eye_y - curr_eye_y) * 0.13

            target_angle_x = 0.0
            target_angle_y = 0.0
            target_angle_z = 0.0
            target_mouth = 0.0

            #  真實音訊波形精準對嘴：完全根據音訊逐幀 RMS 振幅與快開慢合物理平滑決定！
            if is_playing:
                global CURRENT_SMOOTH_MOUTH
                if CURRENT_MOUTH_ENVELOPE and CURRENT_SPEECH_START_TIME > 0:
                    elapsed = now - CURRENT_SPEECH_START_TIME
                    frame_idx = int(elapsed * 25.0)
                    if 0 <= frame_idx < len(CURRENT_MOUTH_ENVELOPE):
                        raw_target = CURRENT_MOUTH_ENVELOPE[frame_idx]
                    else:
                        raw_target = 0.0
                    
                    #  快開慢合 (Fast Attack 0.65, Gentle Release 0.35) 物理濾波，徹底告別卡頓與僵硬
                    if raw_target > CURRENT_SMOOTH_MOUTH:
                        CURRENT_SMOOTH_MOUTH += (raw_target - CURRENT_SMOOTH_MOUTH) * 0.65
                    else:
                        CURRENT_SMOOTH_MOUTH += (raw_target - CURRENT_SMOOTH_MOUTH) * 0.35
                    target_mouth = round(CURRENT_SMOOTH_MOUTH, 3)
                else:
                    #  若無真實音訊波形包絡 (如生成等待、句間分段間隙)，自然平滑閉合嘴巴，嚴禁無聲時空動嘴！
                    CURRENT_SMOOTH_MOUTH *= 0.35
                    target_mouth = round(CURRENT_SMOOTH_MOUTH, 3)
            else:
                CURRENT_SMOOTH_MOUTH = 0.0
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
                target_angle_x = math.sin(t * 1.0) * 1.5 + vc.current_look_x * 0.25
                target_angle_y = math.cos(t * 0.8) * 0.8 + vc.current_look_y * 0.25
                target_angle_z = math.sin(t * 0.7) * 1.0
            elif is_currently_tracking:
                target_angle_x = vc.current_look_x
                target_angle_y = vc.current_look_y
                target_angle_z = 0.0
            else:
                if IS_SLEEPING:
                    #  沉睡休眠安詳姿態：頭微低下垂 (-8.5度)，伴隨均勻舒緩的深層呼吸起伏
                    sleep_breath = math.sin(t * 0.45)
                    target_angle_x = math.sin(t * 0.25) * 1.0
                    target_angle_y = -8.5 + sleep_breath * 0.8
                    target_angle_z = 1.5 + math.sin(t * 0.3) * 0.8
                elif current_ai_state == "IDLE":
                    # 待命時：更自然有幅度的漫遊擺頭，像真人靜待時的自然晃動
                    target_angle_x = math.sin(t * 0.42) * 4.0 + vc.current_look_x * 0.45
                    target_angle_y = math.cos(t * 0.32) * 1.5 + vc.current_look_y * 0.35
                    target_angle_z = math.sin(t * 0.3) * 1.5
                elif current_ai_state == "THINKING":
                    target_angle_x = -2.0 + vc.current_look_x * 0.2
                    target_angle_y = 2.0 + vc.current_look_y * 0.2
                    target_angle_z = 4.5
                elif current_ai_state == "TALKING":
                    # 說話時：加入自然語感搖頭韻律（像說話時帶的肢體動作），幅度不誇張但明顯活潑
                    target_angle_x = math.sin(t * 1.1) * 3.5 + vc.current_look_x * 0.55
                    target_angle_y = math.cos(t * 0.75) * 1.2 + vc.current_look_y * 0.35
                    target_angle_z = math.sin(t * 0.85) * 1.8

            if vc.eye_roll_timer > now:
                target_angle_z += math.sin(t * 4.2) * 3.5
                target_angle_y += math.cos(t * 4.2) * 2.0

            #  純物理動力學縮小瞳孔與震驚 (EyeOpen=2.0 瞪大縮瞳 + 自然呼吸微顫抖)
            #  發話期間若有物理表情，持續延長鎖定，確保說話全程不中途褪去
            if CURRENT_PLAYING_VOICE_TASK is not None:
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

            param_values = [
                {"id": "FaceAngleX", "value": curr_x, "weight": 1.0},
                {"id": "FaceAngleY", "value": curr_y, "weight": 1.0},
                {"id": "FaceAngleZ", "value": curr_z, "weight": 1.0},
                {"id": "EyeLeftX", "value": curr_eye_x, "weight": 1.0},
                {"id": "EyeLeftY", "value": curr_eye_y, "weight": 1.0},
                {"id": "EyeRightX", "value": curr_eye_x, "weight": 1.0},
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
        except Exception as loop_err:
            t = 0.0

        await asyncio.sleep(0.04)
