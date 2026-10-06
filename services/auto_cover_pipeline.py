"""
🎤 7L 全自動 AI 翻唱與伴奏混音管線 (7L Auto AI-Cover Pipeline)
流程：
1. yt-dlp 向 YouTube 抓取高音質音訊
2. Demucs / UVR5 AI 人聲伴奏分離 (RTX 3080 Ti 顯卡加速)
3. 歌唱旋律保持 + 男聲轉少女音高 (+12 半音) 與音色濾波
4. ffmpeg 專業伴奏 + 歌聲立體聲混音
5. 存入 songs_library/ 本地曲庫秒播 + Live2D 舞台開唱
"""

import os
import sys
import re
import asyncio
import subprocess
import shutil
import time
import pygame

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SONGS_DIR = os.path.join(BASE_DIR, "songs_library")
CACHE_DIR = os.path.join(SONGS_DIR, "cover_cache")
os.makedirs(SONGS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

FFMPEG_EXE = os.getenv("FFMPEG_EXE") or (r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe") else "ffmpeg")
YT_DLP_EXE = shutil.which("yt-dlp") or "yt-dlp"

def get_safe_filename(name: str) -> str:
    return re.sub(r'[^\w\u4e00-\u9fa5]', '_', name).strip('_')

CURATED_SEARCH_MAP = {
    "never gonna give you up": "Never Gonna Give You Up Cateek female cover",
    "never_gonna_give_you_up": "Never Gonna Give You Up Cateek female cover",
    "erika": "Erika German song",
}

def download_youtube_audio(song_query: str, output_wav: str) -> bool:
    """
    使用 yt-dlp 智慧搜尋頂級女性翻唱 (Female Cover) 或高品質音軌：
    - 優先抓取真實優秀女歌手的翻唱版本，從根本上徹底根除男聲變調的花栗鼠怪音與神經破音
    - 保留 100% 真人歌手的換氣、轉音、顫音與細膩情感
    """
    print(f"🔍 [YT-DLP 智慧搜歌中] 正在向 YouTube 搜尋《{song_query}》原版高音質音軌...")
    if os.path.exists(output_wav) and os.path.getsize(output_wav) > 100000:
        print(f"💾 [快取命中] 已存在高品質音訊: {output_wav}")
        return True

    clean_q = song_query.lower().strip().replace("-", " ").replace("_", " ")
    candidates = []
    if clean_q in CURATED_SEARCH_MAP:
        candidates.append(f"ytsearch1:{CURATED_SEARCH_MAP[clean_q]}")
    candidates.extend([
        f"ytsearch1:{song_query}",
        f"ytsearch1:{song_query} song",
        f"ytsearch1:{song_query} audio",
        f"ytsearch1:{song_query} female cover"
    ])
    
    for q_str in candidates:
        temp_template = os.path.join(CACHE_DIR, "temp_dl_%(id)s.%(ext)s")
        cmd = [
            YT_DLP_EXE,
            q_str,
            "-x",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "--postprocessor-args", "ffmpeg:-ar 44100 -ac 2",
            "-o", temp_template,
            "--no-playlist",
            "--max-filesize", "50M"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            for f in os.listdir(CACHE_DIR):
                if f.startswith("temp_dl_") and f.endswith(".wav"):
                    src = os.path.join(CACHE_DIR, f)
                    shutil.move(src, output_wav)
                    print(f"✅ [YT-DLP 下載成功] 成功獲取高音質母帶: {output_wav}")
                    return True
        except Exception:
            continue
    return False

def separate_stems_gpu(input_wav: str, song_name: str) -> tuple[str, str]:
    """
    使用 Demucs / UVR 進行人聲與伴奏分離
    回傳: (vocals_path, instrumental_path)
    """
    safe_name = get_safe_filename(song_name)
    vocals_out = os.path.join(CACHE_DIR, f"{safe_name}_vocals.wav")
    inst_out = os.path.join(CACHE_DIR, f"{safe_name}_instrumental.wav")

    if os.path.exists(vocals_out) and os.path.exists(inst_out):
        print(f"💾 [快取命中] 已存在人聲與伴奏分軌檔案！")
        return vocals_out, inst_out

    print(f"⚡ [AI 人聲分離] 正在啟用 GPU 分離人聲與伴奏 (約需 5~15 秒)...")
    
    # 嘗試呼叫 demucs 命令
    demucs_cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", "htdemucs_ft",
        "--shifts", "2",
        "-d", "cuda",
        "-o", CACHE_DIR,
        input_wav
    ]
    try:
        ret = subprocess.run(demucs_cmd, capture_output=True, text=True, timeout=180)
        if ret.returncode == 0:
            # 尋找 htdemucs_ft/{track_name}/vocals.wav & no_vocals.wav
            base_name = os.path.splitext(os.path.basename(input_wav))[0]
            demucs_dir = os.path.join(CACHE_DIR, "htdemucs_ft", base_name)
            d_voc = os.path.join(demucs_dir, "vocals.wav")
            d_inst = os.path.join(demucs_dir, "no_vocals.wav")
            if os.path.exists(d_voc) and os.path.exists(d_inst):
                shutil.copy2(d_voc, vocals_out)
                shutil.copy2(d_inst, inst_out)
                print(f"✨ [AI 人聲分離成功] 伴奏與原唱已精準獨立拆解！")
                return vocals_out, inst_out
    except Exception as e:
        print(f"⚠️ [Demucs 執行異常，切換至備用人聲分離模式]: {e}")

    # 備用方案：使用 ffmpeg 立體聲相位抵消分離 (Center Channel Extraction)
    print(f"🔄 [備用分離] 使用專業立體聲中置通道演算法提取人聲與伴奏...")
    cmd_inst = [
        FFMPEG_EXE, "-y", "-i", input_wav,
        "-af", "stereotools=mlev=0.01:slev=1.0",
        "-ar", "44100", inst_out
    ]
    cmd_voc = [
        FFMPEG_EXE, "-y", "-i", input_wav,
        "-af", "stereotools=mlev=1.2:slev=0.05,highpass=f=120,lowpass=f=7500",
        "-ar", "44100", vocals_out
    ]
    subprocess.run(cmd_inst, capture_output=True)
    subprocess.run(cmd_voc, capture_output=True)
    return vocals_out, inst_out

def pitch_shift_vocal_to_female(vocal_in: str, vocal_out: str, semitones: float = 0.0, auto_pitch: bool = True) -> bool:
    """
    7L 官方專屬歌聲音色：曉伊（Xiaoyi）甜美少女原生音色
    - auto_pitch=True (預設): 啟用樂句級男女聲基頻自動辨識
      * 男聲樂句 (Median f0 < 195Hz) → 自動升八度 +12 半音 (進入 7L 甜美音域)
      * 女聲樂句 (Median f0 >= 195Hz) → 維持原調 0 半音 (自然甜美不尖叫)
      * 男女混唱 → 逐句獨立自適應，完全解決男女混唱兩難問題！
    - semitones: 額外偏移量 (一般保持 0.0)
    - 採用官方 ContentVec + RMVPE 高精度聲學神經引擎
    """
    try:
        from services.neural_voice_converter import convert_vocal_to_xiaoyi
        mode_str = "自適應男女聲智慧辨識" if auto_pitch else f"固定 key={semitones:+0.1f}"
        print(f"👑 [7L 專屬曉伊原聲音色轉換] 啟用曉伊原生歌聲神經轉換 ({mode_str})...")
        ok = convert_vocal_to_xiaoyi(vocal_in, vocal_out, key=semitones, 
            model_pth=r"C:\Users\qiwai\RVC-WebUI\assets\weights\7L_v2.pth",
            index_file=r"C:\Users\qiwai\RVC-WebUI\assets\indices\7L_v2_added_IVF256_Flat_nprobe_1_7L_v2_v2.index",
            index_rate=0.88, auto_pitch=auto_pitch)
        if ok and os.path.exists(vocal_out) and os.path.getsize(vocal_out) > 10000:
            print("🎉 [7L 曉伊原聲翻唱成功] 成功統一 7L 專屬甜妹歌聲！")
            return True
        else:
            print("❌ [RVC 神經轉換失敗] 未產出有效 RVC 音訊，拒絕回退直出原唱！")
            return False
    except Exception as e:
        print(f"⚠️ [RVC 神經轉換異常]: {e}")
        return False


_IS_PRODUCING_COVER = False
IS_SINGING_ACTIVE = False

def get_core_vts():
    """動態取得當前運行的主核心模組，杜絕重複 import 導致 .env 與全域狀態衝突"""
    return sys.modules.get("vts_7L_test") or sys.modules.get("__main__")

def stop_singing():
    """立即中斷當前 7L 翻唱演奏並恢復狀態"""
    global IS_SINGING_ACTIVE
    IS_SINGING_ACTIVE = False
    try:
        if pygame.mixer.get_init():
            pygame.mixer.Channel(6).stop()
            pygame.mixer.Channel(7).stop()
            pygame.mixer.music.stop()
    except Exception:
        pass
    core_vts = get_core_vts()
    if core_vts:
        setattr(core_vts, "IS_SINGING_ACTIVE", False)
        setattr(core_vts, "IS_MP3_PLAYING", False)
        if getattr(core_vts, "current_ai_state", "") == "SINGING":
            setattr(core_vts, "current_ai_state", "IDLE")
        setattr(core_vts, "CURRENT_MOUTH_ENVELOPE", [])
        setattr(core_vts, "CURRENT_SMOOTH_MOUTH", 0.0)
        setattr(core_vts, "CURRENT_SPEECH_START_TIME", 0.0)
    print("🛑 [7L 翻唱] 已成功手動停止歌聲與伴奏播放。")

async def wait_for_intro_speech_complete():
    """等候 7L 大腦完成開場白發話，再銜接翻唱開唱"""
    core_vts = get_core_vts()
    if not core_vts:
        return
    # 1. 若大腦還在深度思考中 (THINKING)，先等候大腦產出台詞 (最多等 8 秒)
    t0 = time.time()
    while getattr(core_vts, "current_ai_state", "") == "THINKING" and time.time() - t0 < 8.0:
        await asyncio.sleep(0.2)
    # 2. 緩衝等候語音進入 speech_queue 或開始播話
    await asyncio.sleep(0.5)
    # 3. 等候開場白說完 (佇列清空且發話完畢)
    while True:
        sq = getattr(core_vts, "speech_queue", None)
        has_queued = sq and not sq.empty()
        is_talking = getattr(core_vts, "current_ai_state", "") == "TALKING"
        is_music = pygame.mixer.get_init() and pygame.mixer.music.get_busy() and not IS_SINGING_ACTIVE
        
        last_tts_end = getattr(core_vts, "LAST_TTS_END_TIME", 0.0)
        recent_speech = (time.time() - last_tts_end) < 2.5
        
        if has_queued or is_talking or is_music or recent_speech:
            await asyncio.sleep(0.3)
        else:
            break

async def produce_and_sing_cover(song_name: str) -> str:
    """
    全自動雙軌即時舞台總控流程：
    1. 查快取 (若已有 7L 純歌聲 7l_vocal.wav 與純伴奏 instrumental.wav 則秒開唱)
    2. 若已有人聲與伴奏分軌但未 RVC，直接極速 12s 置換 7L 甜妹聲線開唱
    3. 若無分軌，下載 YouTube 高音質音軌並以 Demucs GPU 拆解人聲與伴奏
    4. 7L 官方曉伊 (Xiaoyi) 神經聲帶音色轉換
    5. 雙軌獨立同步放音（軌道 6: 7L 純歌聲對嘴 + 軌道 7: 純伴奏立體聲，零混音延遲與零伴奏干擾對嘴）
    6. 演唱完畢後自動向 speech_queue 發送謝幕詞
    """
    global _IS_PRODUCING_COVER
    if _IS_PRODUCING_COVER:
        print(f"⚠️ [翻唱流水線] 當前已有歌曲正在處理中，略過雙軌並發重複調用！")
        return f"老爸，我已經在準備為大家唱這首歌囉！"
    _IS_PRODUCING_COVER = True
    try:
        # 清理歌名引數中的多餘字樣
        song_name = re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', song_name.strip())
        song_name = re.sub(r'[\'"]?$', '', song_name.strip()).strip()

        safe_name = get_safe_filename(song_name)
        cached_vocal = os.path.join(CACHE_DIR, f"{safe_name}_7l_vocal.wav")
        cached_inst = os.path.join(CACHE_DIR, f"{safe_name}_instrumental.wav")

        # 1. 檢查 7L 純人聲快取 (若已有 7L 歌聲則秒開唱)
        play_vocal = None
        if os.path.exists(cached_vocal) and os.path.getsize(cached_vocal) > 100000:
            # 🛡️ 雙重安全驗證：確保為真實 RVC 產出之單聲道 48kHz (舊版未置換的原唱為雙聲道 44.1kHz)
            vocal_raw = os.path.join(CACHE_DIR, f"{safe_name}_vocals.wav")
            is_fake = False
            try:
                import soundfile as sf
                info_7l = sf.info(cached_vocal)
                if info_7l.channels > 1 and os.path.exists(vocal_raw):
                    info_v = sf.info(vocal_raw)
                    if info_7l.channels == info_v.channels and abs(os.path.getsize(cached_vocal) - os.path.getsize(vocal_raw)) < 1000:
                        is_fake = True
            except Exception:
                pass
            if is_fake:
                print(f"🧹 [清除無效假快取] 檢測到《{song_name}》為未經 RVC 置換之舊版原唱快取，立即刪除！")
                try:
                    os.remove(cached_vocal)
                except Exception:
                    pass
            else:
                play_vocal = cached_vocal

        # 2. 若人聲與伴奏已拆解但尚未轉換 7L 聲線，直接極速啟用 RVC (省去下載與分離的數十秒)
        if not play_vocal:
            vocal_raw = os.path.join(CACHE_DIR, f"{safe_name}_vocals.wav")
            if os.path.exists(vocal_raw) and os.path.exists(cached_inst) and os.path.getsize(vocal_raw) > 100000:
                print(f"⚡ [人聲伴奏已分離] 直接啟動 7L 曉伊 RVC 少女歌聲置換 (自適應男女聲音高): 《{song_name}》...")
                rvc_ok = await asyncio.to_thread(pitch_shift_vocal_to_female, vocal_raw, cached_vocal, 0.0)
                if rvc_ok and os.path.exists(cached_vocal) and os.path.getsize(cached_vocal) > 10000:
                    play_vocal = cached_vocal

        # 若命中快取或已極速轉換完畢，立即開唱！
        if play_vocal:
            play_inst = cached_inst if (os.path.exists(cached_inst) and os.path.getsize(cached_inst) > 100000) else None
            print(f"💾 [7L 專屬翻唱庫] 命中已就緒之獨立人聲與伴奏: 《{song_name}》 (雙軌同步即時放音)")
            # 等候 7L 當前開場白講完
            await wait_for_intro_speech_complete()
            await play_cover_audio(play_vocal, song_name, inst_path=play_inst)
            
            # 演唱完畢後，化作紙條塞給 Live 主腦，由主腦動態謝幕（不再使用罐頭回覆）
            try:
                from vts_7L_test import GLOBAL_LIVE_SESSION
                if GLOBAL_LIVE_SESSION:
                    slip_text = f"[系統提示：妳剛才演唱完畢了歌曲《{song_name}》，請自然地向老爸與觀眾謝幕，可以順便問問他們覺得好不好聽！]"
                    print(f"🚨 [翻唱引擎] 已將謝幕指示塞給 Live 主腦，由主腦動態接管發言！")
                    asyncio.create_task(GLOBAL_LIVE_SESSION.send_realtime_input(text=slip_text))
            except Exception as e:
                print(f"⚠️ [翻唱引擎] 轉交謝幕紙條失敗 ({e})")
            return f"謝謝大家～剛才為老爸帶來的是翻唱歌曲《{song_name}》！希望老爸喜歡～"

        print(f"🚀 [7L 全自動翻唱引擎啟動] 目標曲目: 《{song_name}》")
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("tts_progress", {
                "active": True, "mode": "rvc", "stage": "下載 YouTube 高音質音軌", "percent": 10, "detail": song_name
            })
        except Exception: pass
        
        raw_wav = os.path.join(CACHE_DIR, f"{safe_name}_raw.wav")
        
        # 步驟 1: 下載
        success = await asyncio.to_thread(download_youtube_audio, song_name, raw_wav)
        if not success or not os.path.exists(raw_wav):
            try:
                web_dash.broadcast_event("tts_progress", {"active": False, "stage": "下載失敗", "percent": 0})
            except Exception: pass
            return f"老爸，在 YouTube 找《{song_name}》時麥克風卡了一下，待會再試試！"

        try:
            web_dash.broadcast_event("tts_progress", {
                "active": True, "mode": "rvc", "stage": "Demucs GPU 拆解人聲與伴奏", "percent": 30, "detail": song_name
            })
        except Exception: pass

        # 步驟 2: 分離伴奏與人聲
        vocal_wav, inst_wav = await asyncio.to_thread(separate_stems_gpu, raw_wav, song_name)

        try:
            web_dash.broadcast_event("tts_progress", {
                "active": True, "mode": "rvc", "stage": "準備進行 RVC 聲線置換", "percent": 50, "detail": song_name
            })
        except Exception: pass

        # 步驟 3: RVC 原生少女歌聲轉換 (自適應男女聲智慧升八度：男聲+12半音，女聲0半音，男女混唱逐句自適應)
        trans_vocal = os.path.join(CACHE_DIR, f"{safe_name}_7l_vocal.wav")
        rvc_ok = await asyncio.to_thread(pitch_shift_vocal_to_female, vocal_wav, trans_vocal, 0.0)
        if not rvc_ok or not os.path.exists(trans_vocal) or os.path.getsize(trans_vocal) < 10000:
            print("❌ [翻唱管線中斷] RVC 神經歌聲置換未成功，終止播放避免直出原唱！")
            return f"老爸，7L 剛才嗓子被電阻卡了一下，沒能成功換上我的聲線，待會再為大家唱這首喔！"

        # 步驟 4: 等候 7L 當前開場白講完，無縫銜接開唱
        await wait_for_intro_speech_complete()

        # 步驟 5: 本地雙軌獨立同步放音（軌道 6: 7L 歌聲 + 軌道 7: 純伴奏，免去合成 MP3 延遲）
        await play_cover_audio(trans_vocal, song_name, inst_path=inst_wav)

        # 步驟 6: 演唱完畢後，化作紙條塞給 Live 主腦，由主腦動態謝幕（不再使用罐頭回覆）
        try:
            from vts_7L_test import GLOBAL_LIVE_SESSION
            if GLOBAL_LIVE_SESSION:
                slip_text = f"[系統提示：妳剛才演唱完畢了歌曲《{song_name}》，請自然地向老爸與觀眾謝幕，可以順便問問他們覺得好不好聽！]"
                print(f"🚨 [翻唱引擎] 已將謝幕指示塞給 Live 主腦，由主腦動態接管發言！")
                asyncio.create_task(GLOBAL_LIVE_SESSION.send_realtime_input(text=slip_text))
        except Exception as e:
            print(f"⚠️ [翻唱引擎] 轉交謝幕紙條失敗 ({e})")

        return f"剛才播放了《{song_name}》。"
    finally:
        _IS_PRODUCING_COVER = False

async def play_cover_audio(vocal_path: str, song_name: str, inst_path: str = None):
    """
    雙軌同步極致舞台放音：
    - 軌道 6 (Vocal Track): 7L 純淨人聲，專門連動 Live2D 對嘴包絡（0 伴奏鼓點干擾）
    - 軌道 7 (Instrumental Track): 獨立伴奏立體聲同步齊發（無需混音壓制成同一個 MP3）
    """
    global IS_SINGING_ACTIVE
    try:
        IS_SINGING_ACTIVE = True
        core_vts = get_core_vts()
        if core_vts:
            setattr(core_vts, "IS_SINGING_ACTIVE", True)
            setattr(core_vts, "IS_MP3_PLAYING", True)
            setattr(core_vts, "current_ai_state", "SINGING")

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        
        if pygame.mixer.get_num_channels() < 8:
            pygame.mixer.set_num_channels(8)

        # 🛑 播放前徹底停止 pygame.mixer.music (避免 TTS、尖叫或背景音樂同時發聲疊加)
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

        ch_vocal = pygame.mixer.Channel(6)
        ch_inst = pygame.mixer.Channel(7)
        ch_vocal.stop()
        ch_inst.stop()

        snd_vocal = pygame.mixer.Sound(vocal_path)
        snd_inst = pygame.mixer.Sound(inst_path) if (inst_path and os.path.exists(inst_path)) else None

        # 👄 自動同步【純人聲】口型波形包絡至 Live2D 對嘴中樞（徹底杜絕伴奏重低音/鼓點干擾對嘴）
        if core_vts:
            try:
                extract_fn = getattr(core_vts, "extract_audio_mouth_envelope", None)
                if extract_fn:
                    envelope = await asyncio.to_thread(extract_fn, snd_vocal, 25)
                    setattr(core_vts, "CURRENT_MOUTH_ENVELOPE", envelope)
                    setattr(core_vts, "CURRENT_SMOOTH_MOUTH", 0.0)
                    print("👄 [口型同步] 成功將【純人聲音軌】波形包絡同步至 Live2D 對嘴中樞（100% 精準對嘴，零伴奏雜音干擾）！")
            except Exception as env_err:
                print(f"⚠️ [口型波形提取警告]: {env_err}")

        # 🎛️ 專業立體聲即時動態混音平衡：人聲清晰飽滿 (0.67)，伴奏音樂襯托 (0.55)
        ch_vocal.set_volume(0.67)
        if snd_inst:
            ch_inst.set_volume(0.55)

        # 🚀 雙軌同毫秒精準齊發，同微秒記錄對嘴起步基準時間戳
        if snd_inst:
            ch_inst.play(snd_inst)
        ch_vocal.play(snd_vocal)
        if core_vts:
            setattr(core_vts, "CURRENT_SPEECH_START_TIME", time.time())
            setattr(core_vts, "IS_SINGING_ACTIVE", True)
            setattr(core_vts, "IS_MP3_PLAYING", True)
            setattr(core_vts, "current_ai_state", "SINGING")
            
            # 🎤 唱歌自動拿出麥克風
            import services.vts_client as vc
            if vc.GLOBAL_VTS:
                asyncio.create_task(vc.trigger_vts_expression("麥克風"))

        inst_info = " + 獨立伴奏雙軌同步" if snd_inst else " (純人聲清唱)"
        print(f"🎤 [7L 舞台開唱] 正在演唱《{song_name}》（7L 甜妹主唱{inst_info}）！")
        
        # 完整播放整首歌曲，雙軌皆播畢或被手動指令中斷
        while (ch_vocal.get_busy() or (snd_inst and ch_inst.get_busy())) and IS_SINGING_ACTIVE:
            # 若歌聲部分已結束但伴奏在收尾，及時關閉口型波形避免嘴巴微動
            if not ch_vocal.get_busy() and core_vts and getattr(core_vts, "CURRENT_MOUTH_ENVELOPE", None):
                setattr(core_vts, "CURRENT_MOUTH_ENVELOPE", [])
                setattr(core_vts, "CURRENT_SMOOTH_MOUTH", 0.0)
            await asyncio.sleep(0.3)
            
        print(f"✨ [7L 舞台開唱] 《{song_name}》演唱完畢！")
    except Exception as e:
        print(f"❌ [播放異常]: {e}")
    finally:
        IS_SINGING_ACTIVE = False
        try:
            pygame.mixer.Channel(6).stop()
            pygame.mixer.Channel(7).stop()
        except Exception:
            pass
            
        # 唱歌結束自動收起麥克風，恢復預設狀態
        if core_vts:
            import services.vts_client as vc
            if vc.GLOBAL_VTS:
                asyncio.create_task(vc.trigger_vts_expression("_RESET_"))
        core_vts = get_core_vts()
        if core_vts:
            setattr(core_vts, "IS_SINGING_ACTIVE", False)
            setattr(core_vts, "IS_MP3_PLAYING", False)
            if getattr(core_vts, "current_ai_state", "") == "SINGING":
                setattr(core_vts, "current_ai_state", "IDLE")
            setattr(core_vts, "CURRENT_MOUTH_ENVELOPE", [])
            setattr(core_vts, "CURRENT_SMOOTH_MOUTH", 0.0)
            setattr(core_vts, "CURRENT_SPEECH_START_TIME", 0.0)

if __name__ == "__main__":
    async def test():
        res = await produce_and_sing_cover("Never Gonna Give You Up")
        print("結果:", res)
    asyncio.run(test())
