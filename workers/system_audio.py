# -*- coding: utf-8 -*-
"""系統聲音感知：聽電腦正在放的聲音（音量、有沒有人聲、在放什麼歌），給她當背景知識。

主程式的狀態經 host.<名稱> 即時讀寫（host＝主程式模組，主程式 import 本檔後 bind()）。
用到的名稱列在 HOST_ATTRS，tests/test_workers_host.py 核對主程式真的都有定義。
"""
import asyncio
import difflib
import io
import re
import time
import wave
from collections import deque

import numpy as np
import pygame
import soundcard as sc
from google import genai
from google.genai import types

import core.stage_state as stage
import services.piano_engine as pe
from core.llm_engine import AUDIO_MODEL, UNRESTRICTED_SAFETY_SETTINGS, GEMINI_KEYS, KEYS_VISION, get_dynamic_live_key_candidates, report_gemini_key_error
from core.utils import log_print, log_swallowed, spawn

HOST_ATTRS = (
    "CURRENT_SYSTEM_AUDIO_VOL_PERCENT",
    "GLOBAL_SPEECH_AUDIO_BUFFER",
    "LAST_TTS_END_TIME",
    "LATEST_SYSTEM_AUDIO_RMS",
    "LATEST_SYSTEM_AUDIO_TEXT",
    "LATEST_SYSTEM_AUDIO_TEXT_TIME",
    "LATEST_SYSTEM_MUSIC_INFO",
    "LATEST_SYSTEM_MUSIC_TIME",
    "current_system_audio_context",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


LAST_MUSIC_IDENTIFY_TIME = 0.0


GLOBAL_SYSTEM_WAV_BYTES = None


async def identify_system_music_and_sound(wav_bytes: bytes) -> str:
    """ 7L 智能電腦音樂與音效多模態感知中樞：
    當電腦播放音樂、歌曲、動漫OST或遊戲音效（無人聲語音）時，
    結合 10~11 秒長音訊、桌面視窗標題線索、畫面視覺線索與 Gemini 音訊感知模型，精準聽出具體曲名、作者或風格特徵。
    """
    global LAST_MUSIC_IDENTIFY_TIME
    now = time.time()

    #  0. 若 7L 自身正在彈鋼琴或播放 MP3，電腦聲音即為 7L 自身聲音，直接同步當前鋼琴曲目，請勿調用 AI 瞎猜
    if (hasattr(pe, "is_piano_active_and_alive") and pe.is_piano_active_and_alive()) or getattr(pe, "is_piano_active", False) or stage.ai_state() == "PIANO":
        song_t = getattr(pe, "current_piano_song_title", "") or "鋼琴曲"
        host.current_system_audio_context = f"7L 正在為老爸演奏鋼琴：《{song_t}》"
        host.LATEST_SYSTEM_MUSIC_INFO = f"《{song_t}》"
        host.LATEST_SYSTEM_MUSIC_TIME = now
        return host.LATEST_SYSTEM_MUSIC_INFO

    if stage.IS_MP3_PLAYING:
        return host.LATEST_SYSTEM_MUSIC_INFO

    if now - LAST_MUSIC_IDENTIFY_TIME < 15.0:
        return host.LATEST_SYSTEM_MUSIC_INFO
    LAST_MUSIC_IDENTIFY_TIME = now

    #  1. Windows 原生硬體級 GSMTC 媒體播放器底層情報提取 (嚴格排除已暫停或無視訊狀態)
    media_clues = []
    try:
        from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
        # 僅提取當前焦點操作視窗作為輔助線索（並嚴格標註可能處於暫停）
        fg = os_desktop_sensor.get_foreground_window()
        if fg and fg.get("window_title"):
            fg_title = fg["window_title"]
            fg_pname = fg.get("process_name", "")
            if any(k in fg_title.lower() or k in fg_pname.lower() for k in ["spotify", "music", "foobar", "potplayer", "vlc", "aimp"]):
                media_clues.append(f"焦點播放器視窗: [{fg_pname}] {fg_title} (注意：若未播放請勿採信)")
    except Exception:
        log_swallowed()

    target_key = ""
    try:
        candidate_keys = get_dynamic_live_key_candidates(KEYS_VISION if KEYS_VISION else GEMINI_KEYS)
        if not candidate_keys:
            candidate_keys = GEMINI_KEYS
        
        target_key = candidate_keys[0] if candidate_keys else None
        if not target_key:
            return ""

        client = genai.Client(api_key=target_key)
        audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")

        prompt_text = (
            "妳是 7L 的全雙工聽覺與音樂感知神經。\n"
            "這是一段從老爸電腦喇叭內錄擷取的 10 秒真實即時音訊。\n"
            "【最高核心原則——以妳聽到的真實音訊旋律為 100% 唯一依據，絕不可瞎猜網頁標題】：\n"
            "1. 妳必須『親耳聽出音訊中的真實旋律、節奏與樂器』！\n"
            "2. 【嚴厲警惕背景未播放的分頁】：老爸經常在瀏覽器開著多個【處於暫停、未播放、靜音】的 YouTube 或網頁分頁！\n"
            "   若音訊中的旋律與演奏樂器與任何網頁或視窗標題不符，代表該網頁目前【根本沒有發出聲音】！絕對不能把未在播放的網頁標題當作辨識結果！\n"
            "3. 只有當音訊中的音樂旋律，妳 100% 確實聽出並確認具體曲名時，才輸出具體曲名（例如：李斯特《鐘》、周杰倫《晴天》等）。\n"
            "4. 若音訊旋律無法明確指認具體曲名，或聽到的音樂與參考線索不符，請【務必僅輸出單詞】：UNKNOWN\n"
            "5. 請準確辨識曲目，避免使用『電子舞曲』、『古典鋼琴曲』、『純音樂』等空泛形容詞！\n"
            "請直接輸出結果（25 字以內）："
        )

        # 同步 SDK 丟執行緒跑；加逾時，API 卡住時系統音監聽才不會永遠等下去
        resp = await asyncio.wait_for(asyncio.to_thread(
            client.models.generate_content,
            model=AUDIO_MODEL,
            contents=[audio_part, prompt_text],
            config=types.GenerateContentConfig(safety_settings=UNRESTRICTED_SAFETY_SETTINGS)
        ), timeout=12.0)

        res_text = resp.text.strip() if resp and resp.text else ""
        res_text = re.sub(r"^(這段音訊是|電腦正在播放|這聽起來是|這是一首|這是)\s*", "", res_text)
        res_text = res_text.replace("\n", " ").replace("「", "").replace("」", "").strip()

        #  嚴格校驗：確保確實指認出具體曲名/作品，杜絕 generic 模糊風格瞎猜
        def _check_is_music_valid(s: str) -> bool:
            if not s or "UNKNOWN" in s.upper() or s in ["未知", "無法識別", "無音樂", "無特別音樂", "None", "None."]:
                return False
            has_title_marker = (
                ("《" in s and "》" in s) or
                ("「" in s and "」" in s) or
                any(sep in s for sep in [" - ", "－", " / ", " by ", "：", ":"])
            )
            generic_style_keywords = [
                "breakcore", "電子舞曲", "電子音樂", "電子樂", "碎拍", "drum & bass", "dnb",
                "lo-fi", "純音樂", "鋼琴", "獨奏", "演奏", "背景音樂", "bgm", "節奏",
                "流行", "古典", "動漫", "音效", "抒情", "旋律", "舞曲", "輕快", "激昂"
            ]
            if not has_title_marker:
                lower_s = s.lower()
                if any(kw in lower_s for kw in generic_style_keywords):
                    return False
            return True

        if not _check_is_music_valid(res_text):
            # 未確實聽出具體曲名，保持靜默，不通報終端機，不污染思緒
            return ""

        if res_text and len(res_text) >= 2:
            # 比對與上一輪辨識相似度，若只是細微詞彙變動則靜默更新，避免終端機洗版
            is_duplicate = False
            if host.LATEST_SYSTEM_MUSIC_INFO:
                sim = difflib.SequenceMatcher(None, res_text.lower(), host.LATEST_SYSTEM_MUSIC_INFO.lower()).ratio()
                if sim > 0.72:
                    is_duplicate = True

            host.LATEST_SYSTEM_MUSIC_INFO = res_text
            host.LATEST_SYSTEM_MUSIC_TIME = time.time()
            host.current_system_audio_context = f"電腦正在播放音樂/音效：{res_text}"
            if not is_duplicate:
                log_print(f"🎵 [電腦音樂感知] 7L 聽出電腦正在播放: 「{res_text}」")
            return res_text
    except Exception as e:
        report_gemini_key_error(target_key, e, AUDIO_MODEL)
        # 若 API 短暫異常，由 GSMTC 底層精確線索保底
        try:
            from mic_live_plugin.os_desktop_sensor import os_desktop_sensor
            # 這支會同步跑 PowerShell（最多 2 秒）：以前直接在主迴圈呼叫，整個 7L 每十幾秒凍一下（2026-10-30 健檢）
            sessions = await asyncio.to_thread(os_desktop_sensor.get_windows_media_info)
            if sessions and sessions[0].get("title"):
                first_m = sessions[0]
                t = first_m["title"]
                a = first_m.get("artist", "")
                fallback_info = f"《{t}》" + (f" ({a})" if a else "")
                host.LATEST_SYSTEM_MUSIC_INFO = fallback_info[:25]
                host.LATEST_SYSTEM_MUSIC_TIME = time.time()
                host.current_system_audio_context = f"電腦正在播放音樂/音效：{host.LATEST_SYSTEM_MUSIC_INFO}"
                return host.LATEST_SYSTEM_MUSIC_INFO
        except Exception:
            log_swallowed()
    return ""


async def system_audio_worker():
    """ 即時電腦內部全系統聲音感知與內錄協程 (WASAPI Loopback 實時耳目)"""
    global LAST_MUSIC_IDENTIFY_TIME
    
    log_print("🎧 [聲音感知] 7L 電腦內部全系統聲音監聽系統 (WASAPI Loopback) 已就緒！")
    
    speech_audio_buffer = deque(maxlen=35)   # ~2.8 秒語音滑動緩衝區 (35 * 0.08s)，專供即時 STT 人聲辨識
    music_audio_buffer = deque(maxlen=135)   # ~10.8 秒深度音樂滑動緩衝區 (135 * 0.08s)，專供 Gemini 聆聽旋律曲名
    last_transcribe_time = 0.0
    is_transcribing = False

    def _convert_buffer_to_wav(chunks):
        try:
            if not chunks:
                return None
            data = np.concatenate(chunks, axis=0)
            if len(data.shape) > 1 and data.shape[1] > 1:
                data_mono = np.mean(data, axis=1)
            else:
                data_mono = data.flatten()
            audio_int16 = (np.clip(data_mono, -1.0, 1.0) * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())
            return buf.getvalue()
        except Exception:
            return None

    def _sync_capture_step(recorder):
        data = recorder.record(numframes=1280)
        rms = float(np.sqrt(np.mean(np.square(data))))
        return data, rms

    while True:
        try:
            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            with loopback_mic.recorder(samplerate=16000, blocksize=1280) as recorder:
                while True:
                    data, rms = await asyncio.to_thread(_sync_capture_step, recorder)
                    host.LATEST_SYSTEM_AUDIO_RMS = rms
                    # 依據 RMS 計算 0 ~ 100% 全系統即時音量 (RMS 0.16 約為 100%)
                    vol_pct = min(100, int((rms / 0.16) * 100)) if rms > 0.003 else 0
                    host.CURRENT_SYSTEM_AUDIO_VOL_PERCENT = vol_pct
                    speech_audio_buffer.append(data)
                    music_audio_buffer.append(data)
                    
                    host.GLOBAL_SPEECH_AUDIO_BUFFER.append(data)

                    #  若 7L 自身正在唱歌，電腦聲音為 7L 歌聲，略過 STT 與音樂猜測，防止自己被自己打斷
                    if stage.singing():
                        host.current_system_audio_context = "7L 本人正在演唱翻唱歌曲（Live2D 舞台開唱中；演唱者是 7L，不是老爸也不是觀眾）"
                        host.LATEST_SYSTEM_MUSIC_INFO = "7L 本人翻唱歌曲"
                        host.LATEST_SYSTEM_MUSIC_TIME = time.time()
                        await asyncio.sleep(0.08)
                        continue

                    #  若 7L 自身正在彈鋼琴，電腦聲音為 7L 琴聲，直接同步曲目，略過 STT 與音樂猜測
                    if (hasattr(pe, "is_piano_active_and_alive") and pe.is_piano_active_and_alive()) or getattr(pe, "is_piano_active", False) or stage.ai_state() == "PIANO":
                        song_t = getattr(pe, "current_piano_song_title", "") or "鋼琴曲"
                        host.current_system_audio_context = f"7L 正在為老爸演奏鋼琴：《{song_t}》"
                        host.LATEST_SYSTEM_MUSIC_INFO = f"《{song_t}》"
                        host.LATEST_SYSTEM_MUSIC_TIME = time.time()
                        await asyncio.sleep(0.08)
                        continue

                    # 若有聲音 (RMS > 0.007) 且未在進行 TTS 發話
                    is_tts = False
                    try:
                        is_tts = pygame.mixer.music.get_busy()
                    except Exception:
                        log_swallowed()

                    now = time.time()
                    if rms > 0.007 and not is_tts and not is_transcribing:
                        # 累積至少 1.5 秒語音且距離上次轉錄 > 2.5 秒
                        if len(speech_audio_buffer) >= 20 and (now - last_transcribe_time > 2.5):
                            is_transcribing = True
                            last_transcribe_time = now
                            speech_chunks = list(speech_audio_buffer)
                            # 若音樂緩衝區已累積足夠長度 (>= 80 塊，約 6.4s~10.8s) 且已過冷卻 (>= 18s)
                            music_chunks = list(music_audio_buffer) if (len(music_audio_buffer) >= 80 and (now - LAST_MUSIC_IDENTIFY_TIME >= 18.0)) else None

                            async def _do_bg_transcribe(s_chunks, m_chunks):
                                nonlocal is_transcribing
                                try:
                                    global GLOBAL_SYSTEM_WAV_BYTES
                                    wav_bytes = await asyncio.to_thread(_convert_buffer_to_wav, s_chunks)
                                    if wav_bytes:
                                        # 遵照老爸指示，完全不使用 STT 辨識系統音訊，避免幻覺產生「字幕by索兰娅」
                                        # 僅將最純淨的波形資料保存下來，供麥克風做「純 wav 音頻對比 (AEC)」
                                        GLOBAL_SYSTEM_WAV_BYTES = wav_bytes
                                        
                                        # 若有累積足夠長的音樂緩衝，則交給 Gemini 音樂感知分析
                                        if m_chunks:
                                            #  STT 未辨識到語音，且音樂緩衝區已累積 7~11 秒高品質長音訊，由音樂感知核心深度聆聽
                                            m_wav_bytes = await asyncio.to_thread(_convert_buffer_to_wav, m_chunks)
                                            if m_wav_bytes:
                                                await identify_system_music_and_sound(m_wav_bytes)
                                except Exception:
                                    log_swallowed()
                                finally:
                                    is_transcribing = False

                            spawn(_do_bg_transcribe(speech_chunks, music_chunks))
                    elif rms <= 0.003:
                        if now - last_transcribe_time > 3.0 and (now - host.LAST_TTS_END_TIME > 2.0):
                            if now - host.LATEST_SYSTEM_AUDIO_TEXT_TIME > 10.0 and now - host.LATEST_SYSTEM_MUSIC_TIME > 10.0:
                                host.LATEST_SYSTEM_AUDIO_TEXT = ""
                                host.LATEST_SYSTEM_MUSIC_INFO = ""
                                LAST_MUSIC_IDENTIFY_TIME = 0.0  # 靜音後重置冷卻，下一首新歌進來能迅速感知
                                host.current_system_audio_context = "電腦目前沒有播放特別的聲音。"
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1.0)
