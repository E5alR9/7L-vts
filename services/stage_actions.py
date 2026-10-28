# -*- coding: utf-8 -*-
"""舞台動作：句中表情／走位時間軸的解析與執行、說話時的表情動作標籤、表情守護（2026-10-25 從主程式搬出來）。

parse_action_timeline：把 [0.0s: 表情] 這類標籤＋句子長度排成時間軸；execute_action_timeline 照時間軸下達。
execute_speech_visual_actions：處理回覆裡的 [EXPRESSION]／[MOVE]／WINK 等標籤。
expression_keeper_worker：VTS 偶爾把表情吃掉，定時補回去。
"""
import asyncio
import re
import time

import services.piano_engine as pe
import services.vts_client as vc
from services.vts_client import apply_spatial_position, set_vts_expression
from core.utils import log_print, log_swallowed, spawn


def parse_action_timeline(raw_text: str, total_duration: float) -> list:
    """從原始模型回覆字串中，按字元進度精確計算每個表情/動作標籤在語音播放期間的觸發時間點。
    支援句中隨時切換表情（例如上半句 [EXPRESSION: 生氣]，下半句 [EXPRESSION: 臉紅]）。
    回傳: [(fire_time_sec, action_type, action_val), ...]
    """
    if not raw_text:
        return []

    clean_raw = re.sub(r'\[THOUGHT:[^\]]*\]', '', raw_text, flags=re.IGNORECASE).strip()
    tag_pattern = re.compile(
        r'\[(EXPRESSION|MOVE|LOOK|SPATIAL|POSITION|WINDOW|WINK|FROWN|SHOCK|眨眼|皺眉|震驚)(?:[：:]\s*([^\]\[]*))?\]',
        re.IGNORECASE
    )

    tags_with_pos = []
    for m in tag_pattern.finditer(clean_raw):
        raw_type = m.group(1).upper()
        tag_val = m.group(2).strip() if m.group(2) else ''

        if raw_type in ['SPATIAL', 'POSITION', 'WINDOW']:
            tag_type = 'MOVE'
        elif raw_type in ['WINK', '眨眼']:
            tag_type = 'WINK'
            tag_val = ''
        elif raw_type in ['FROWN', '皺眉']:
            tag_type = 'EXPRESSION'
            tag_val = '皺眉'
        elif raw_type in ['SHOCK', '震驚']:
            tag_type = 'EXPRESSION'
            tag_val = '震驚'
        else:
            tag_type = raw_type

        tags_with_pos.append((m.start(), tag_type, tag_val))

    clean_spoken = tag_pattern.sub('', clean_raw).strip()
    clean_spoken = re.sub(r'\[[A-Z_]+[：:][^\]]*\]', '', clean_spoken).strip()
    clean_spoken = re.sub(r'\[[A-Z_]+[：:]?[^\]]*$', '', clean_spoken).strip()
    total_chars = max(1, len(clean_spoken))

    timeline = []
    for start_idx, tag_type, tag_val in tags_with_pos:
        prefix = clean_raw[:start_idx]
        prefix_clean = tag_pattern.sub('', prefix)
        prefix_clean = re.sub(r'\[[A-Z_]+[：:][^\]]*\]', '', prefix_clean).strip()
        prefix_clean = re.sub(r'\[[A-Z_]+[：:]?[^\]]*$', '', prefix_clean).strip()
        char_offset = len(prefix_clean)
        ratio = min(1.0, max(0.0, char_offset / total_chars))
        fire_time = round(ratio * total_duration, 2)
        timeline.append((fire_time, tag_type, tag_val))

    timeline.sort(key=lambda x: x[0])
    return timeline


async def execute_action_timeline(vts, timeline: list, cancel_event: asyncio.Event = None):
    """ 語音時間軸動態表情與動作執行器：
    隨語音發音進度精確在毫秒級時間點觸發表情轉換，實現上半句到下半句想換就換的生動神態！
    """
    
    if not timeline or not vts:
        return
    start_t = time.time()
    for fire_time, action_type, action_val in sorted(timeline, key=lambda x: x[0]):
        if cancel_event and cancel_event.is_set():
            break
        now_offset = time.time() - start_t
        delay = fire_time - now_offset
        if delay > 0:
            try:
                if cancel_event:
                    await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                    break
                else:
                    await asyncio.sleep(delay)
            except asyncio.TimeoutError:
                pass

        if cancel_event and cancel_event.is_set():
            break

        try:
            if action_type == "EXPRESSION":
                log_print(f"🎭 [句中即時換表情 ({fire_time:.1f}s)]: 切換至「{action_val}」")
                await set_vts_expression(vts, action_val)
            elif action_type == "WINK":
                log_print(f"😉 [句中即時動作 ({fire_time:.1f}s)]: 眨眼 WINK")
                await vc.trigger_wink()
            elif action_type == "MOVE":
                log_print(f"🚶 [句中即時走位 ({fire_time:.1f}s)]: 移動至「{action_val}」")
                await apply_spatial_position(action_val)
            elif action_type == "LOOK":
                u_act = action_val.upper()
                if "ROLL" in u_act:
                    await vc.trigger_eye_roll()
                elif "MOUSE" in u_act:
                    await vc.set_tracking_mouse(True)
                elif "LEFT" in u_act:
                    await vc.set_target_look(-25.0, 0.0)
                elif "RIGHT" in u_act:
                    await vc.set_target_look(25.0, 0.0)
                elif "UP" in u_act:
                    await vc.set_target_look(0.0, 20.0)
                elif "DOWN" in u_act:
                    await vc.set_target_look(0.0, -20.0)
                elif "CENTER" in u_act:
                    await vc.set_target_look(0.0, 0.0)
        except Exception as e:
            log_print(f"⚠️ [即時時間軸執行異常]: {e}")


async def execute_speech_visual_actions(vts, text: str):
    """ 語音同步專用 Live2D 演出控制器：
    精準在語音【真正開口發話播放】的瞬間觸發本句專屬的表情、走位、眨眼、視線與身體動作，
    杜絕連續說話時下一句還在排隊、動作卻提前偷跑的脫節問題！
    """
    
    if not text:
        return
        
    # 她偶爾寫成複數 [EXPRESSIONS: 吐舌]（2026-10-29 後台對話紀錄），以前整個沒認到、表情沒做
    exp_match = re.search(r'\[EXPRESSIONS?[：:]\s*([^\]\[]+)\]', text, re.IGNORECASE)
    if exp_match:
        exp_tag = exp_match.group(1).strip()
        kind = vc.action_kind(exp_tag)   # 眨眼／驚訝／皺眉的關鍵字跟 vts_client 同一份
        if kind == "wink":
            spawn(vc.trigger_wink())
            log_print("😉 [Live2D 動作] 標籤觸發 Wink 單眼眨一下眼")
        elif kind == "shock":
            spawn(vc.trigger_shock())
            log_print("😱 [Live2D 動作] 標籤觸發驚訝縮瞳與瞪大雙眼微顫")
        elif kind == "frown":
            spawn(vc.trigger_frown())
            log_print("🥺 [Live2D 動作] 標籤觸發八字皺眉/委屈表情")
        else:
            log_print(f"🎭 [Live2D 表情] 標籤觸發表情: 「{exp_tag}」")
            spawn(set_vts_expression(vts, exp_tag))

    move_match = re.search(r'\[(?:MOVE|SPATIAL|WINDOW|POSITION)[：:]\s*([^\]\[]+)\]', text, re.IGNORECASE)
    if move_match:
        pos_tag = move_match.group(1).strip()
        if not pe.is_piano_active or any(k in pos_tag for k in ["鋼琴", "原本", "大小", "視窗"]):
            log_print(f"🚶 [Live2D 走位] 標籤觸發模型移動至: 「{pos_tag}」")
            spawn(apply_spatial_position(pos_tag))

    try:
        upper_text = text.upper()
        if "WINK" in upper_text and not exp_match:
            spawn(vc.trigger_wink())
            log_print("😉 [Live2D 動作] 動作觸發 Wink 單眼眨一下眼")
        elif any(k in upper_text for k in ["SHOCK", "SHOCKED", "SURPRISE", "PUPIL", "驚訝", "惊讶", "震驚", "震惊", "瞳孔", "嚇到"]) and not exp_match:
            spawn(vc.trigger_shock())
            log_print("😱 [Live2D 動作] 動作觸發驚訝縮瞳與瞪大雙眼微顫")
        elif any(k in upper_text for k in ["FROWN", "FROWNING", "皺眉", "皱眉", "八字眉", "困擾", "委屈"]) and not exp_match:
            spawn(vc.trigger_frown())
            log_print("🥺 [Live2D 動作] 動作觸發八字皺眉/委屈神態")
        elif any(k in upper_text for k in ["ROLL", "AROUND", "WANDER", "轉眼", "環視"]):
            spawn(vc.trigger_eye_roll())
            log_print("🌀 [Live2D 動作] 動作觸發招牌靈動轉眼珠環視四周")
        elif "MOUSE" in upper_text and "LOOK" in upper_text:
            spawn(vc.set_tracking_mouse(True))
            log_print("👀 [Live2D 視線] 視線切換為鎖定追蹤滑鼠游標")
        elif "LEFT" in upper_text and "LOOK" in upper_text:
            spawn(vc.set_target_look(-25.0, 0.0))
            log_print("👀 [Live2D 視線] 視線轉向【左邊】")
        elif "RIGHT" in upper_text and "LOOK" in upper_text:
            spawn(vc.set_target_look(25.0, 0.0))
            log_print("👀 [Live2D 視線] 視線轉向【右邊】")
        elif "UP" in upper_text and "LOOK" in upper_text:
            spawn(vc.set_target_look(0.0, 25.0))
            log_print("👀 [Live2D 視線] 視線轉向【上方】")
        elif "DOWN" in upper_text and "LOOK" in upper_text:
            spawn(vc.set_target_look(0.0, -25.0))
            log_print("👀 [Live2D 視線] 視線轉向【下方】")
        elif "CENTER" in upper_text and "LOOK" in upper_text:
            spawn(vc.set_target_look(0.0, 0.0))
            log_print("👀 [Live2D 視線] 視線回正【正前方】")

        if "EARS" in upper_text:
            vc.force_blink_trigger = 1
            log_print("🐰 [Live2D 動作] 動作觸發耳朵抖動/眨眼")
    except Exception:
        pass


async def expression_keeper_worker(vts):
    
    while True:
        await asyncio.sleep(12.0)
        try:
            active_exps = getattr(vc, "CURRENT_ACTIVE_EXPS", None)
            if active_exps:
                msg_state = {
                    "apiName": "VTubeStudioPublicAPI", 
                    "apiVersion": "1.0", 
                    "requestID": "GetState", 
                    "messageType": "ExpressionStateRequest", 
                    "data": {"details": True}
                }
                async with vc.vts_lock:
                    resp_state = await asyncio.wait_for(vts.request(msg_state), timeout=1.0)
                
                expressions = resp_state.get("data", {}).get("expressions", [])
                vts_active_files = [exp.get("file") for exp in expressions if exp.get("active")]
                
                for exp_file in list(active_exps):
                    if exp_file not in vts_active_files:
                        async with vc.vts_lock:
                            await asyncio.wait_for(vts.request({
                                "apiName": "VTubeStudioPublicAPI",
                                "apiVersion": "1.0",
                                "requestID": "ForceActivate",
                                "messageType": "ExpressionActivationRequest",
                                "data": {"expressionFile": exp_file, "active": True}
                            }), timeout=0.8)
        except Exception:
            log_swallowed()
