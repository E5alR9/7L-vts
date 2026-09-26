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

FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe") else "ffmpeg"
YT_DLP_EXE = shutil.which("yt-dlp") or "yt-dlp"

def get_safe_filename(name: str) -> str:
    return re.sub(r'[^\w\u4e00-\u9fa5]', '_', name).strip('_')


def _clean_cover_title(s: str) -> str:
    s = re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', (s or "").strip())
    s = re.sub(r'[\'"]?$', '', s.strip()).strip()
    s = re.sub(r'^(?:\[)?(?:AUTO_SING_SONG|SING_SONG|AUTO_SING|SING|翻唱|唱歌|唱|點歌)[：:\s]*', '', s, flags=re.IGNORECASE).strip()
    return s.strip()


# ── 翻唱意圖閘門＋暫存隔離區（鋼琴垃圾場教訓：沒確認＝不下載） ──
STAGING_DIR = os.path.join(CACHE_DIR, "_staging")
os.makedirs(STAGING_DIR, exist_ok=True)

_PIANO_WORDS = ["彈", "鋼琴", "演奏", "midi", "琴譜", "伴奏彈", "彈琴"]
_SING_VERBS = ["翻唱", "唱一首", "唱首", "來一首", "來首", "點歌", "cover", "唱歌", "唱一下", "唱首歌", "唱"]
_TAIL_JUNK = ["好不好聽", "好不好", "可不可以", "可以嗎", "行不行", "一下", "一首", "一遍"]


def is_sing_request(raw_text: str):
    """嚴格翻唱意圖閘：回 (是否點唱, 乾淨歌名)。
    - 純數字/標點/超短/日常寒暄 → False，絕不下載。
    - 含鋼琴字眼且無唱字 → False（歸鋼琴管）。
    - 必須有唱系動詞或《》書名號歌名。"""
    if not raw_text or not raw_text.strip():
        return False, ""
    q = re.sub(r'【.*?】[：:]?', '', raw_text)
    q = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', q).strip(' ：:\t\r\n')
    if not q or len(q) <= 1:
        return False, ""
    ql = q.lower().strip()
    if ql.isdigit() or re.fullmatch(r'[\d\s.,!?:;~～\-_+、，。！？]+', ql):
        return False, ""
    non_song = ["你好", "哈囉", "安安", "早安", "晚安", "在嗎", "笑死", "666", "好聽", "厲害",
                "加油", "謝謝", "拜拜", "晚安安", "多喝水", "注意身體"]
    if any(k == ql for k in non_song):
        return False, ""
    has_piano = any(w in q for w in _PIANO_WORDS)
    has_sing = any(v in ql for v in _SING_VERBS) or "唱" in q
    if has_piano and not has_sing:
        return False, ""
    title = ""
    m = re.search(r'《([^》]{1,40})》', q)
    if m:
        title = m.group(1).strip()
    if not title:
        # 演唱/歌唱/合唱是名詞（演唱會/歌唱比賽），不是點唱，略過裸唱提取
        bare_ok = not any(w in ql for w in ["演唱", "歌唱", "合唱", "唱片", "唱腔", "歌聲"])
        for v in sorted(_SING_VERBS, key=len, reverse=True):
            if v == "唱" and not bare_ok:
                continue
            if v in ql:
                idx = ql.find(v) + len(v)
                cand = q[idx:idx + 30].strip(' ：:、，, 。！？')
                cand = re.split(r'[，。！？\n]', cand)[0].strip()
                if cand:
                    title = cand
                break
    if not title and not has_sing:
        return False, ""
    if has_sing and not title:
        # 有唱令但沒歌名（如「唱一首」）：算意圖，歌名留空由大腦工具補
        return True, ""
    title = re.sub(r'^(?:歌曲|一首|首|個|支)\s*', '', title).strip()
    for junk in _TAIL_JUNK:
        if title.endswith(junk) and len(title) > len(junk) + 1:
            title = title[:-len(junk)].strip()
    title = re.sub(r'[（(]\s*(?:唱歌|翻唱|唱)\s*[）)]\s*$', '', title).strip()
    if not title:
        return False, ""
    return True, _clean_cover_title(title)


def cleanup_staging(max_age_days: float = 3.0, max_files: int = 10):
    """開機清暫存：刪 3 天以上未動的預取檔，只留最新 10 組，垃圾不過夜。"""
    try:
        files = []
        for f in os.listdir(STAGING_DIR):
            fp = os.path.join(STAGING_DIR, f)
            if os.path.isfile(fp):
                files.append((os.path.getmtime(fp), fp))
        files.sort()
        now = time.time()
        for mt, fp in files:
            if now - mt > max_age_days * 86400:
                try:
                    os.remove(fp)
                except Exception:
                    pass
        files = [(mt, fp) for mt, fp in files if os.path.exists(fp)]
        if len(files) > max_files * 3:
            for _, fp in files[:len(files) - max_files * 3]:
                try:
                    os.remove(fp)
                except Exception:
                    pass
    except Exception:
        pass


async def maybe_prefetch_cover(raw_text: str) -> str:
    """聊天預取：閘門通過才抓音源＋分軌到暫存區（不做 RVC，省顯卡）。
    回傳 safe_name（命中預取），無事回空字串。絕不污染正式曲庫。"""
    try:
        ok, title = is_sing_request(raw_text)
        if not ok or not title:
            return ""
        safe = get_safe_filename(title)
        staged_v = os.path.join(STAGING_DIR, f"{safe}_vocals.wav")
        staged_i = os.path.join(STAGING_DIR, f"{safe}_instrumental.wav")
        if (os.path.exists(staged_v) and os.path.exists(staged_i)
                and os.path.getsize(staged_v) > 100000):
            return safe
        if _IS_PRODUCING_COVER:
            return ""
        print(f"👂 [翻唱預取] 偵測到點唱意圖《{title}》，背景偷跑音源＋分軌…")
        raw_wav = os.path.join(STAGING_DIR, f"{safe}_raw.wav")
        ok_dl = await asyncio.to_thread(download_youtube_audio, title, raw_wav)
        if not ok_dl or not os.path.exists(raw_wav):
            return ""
        v_path, i_path = await asyncio.to_thread(separate_stems_gpu, raw_wav, title, STAGING_DIR)
        if (v_path and i_path and os.path.exists(v_path) and os.path.exists(i_path)
                and os.path.getsize(v_path) > 100000):
            print(f"✅ [翻唱預取] 《{title}》分軌已備妥，點歌即開唱！")
            return safe
        return ""
    except Exception as e:
        print(f"⚠️ [翻唱預取異常]: {e}")
        return ""

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
    print(f"🔍 [YT-DLP 智慧搜歌中] 正在向 YouTube 搜尋《{song_query}》頂級女聲/翻唱音軌...")
    if os.path.exists(output_wav) and os.path.getsize(output_wav) > 100000:
        print(f"💾 [快取命中] 已存在高品質音訊: {output_wav}")
        return True

    clean_q = song_query.lower().strip().replace("-", " ").replace("_", " ")
    candidates = []
    if clean_q in CURATED_SEARCH_MAP:
        candidates.append(f"ytsearch1:{CURATED_SEARCH_MAP[clean_q]}")
    candidates.extend([
        f"ytsearch1:{song_query} female cover",
        f"ytsearch1:{song_query} song",
        f"ytsearch1:{song_query}",
        f"ytsearch1:{song_query} audio"
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
                    print(f"✅ [YT-DLP 下載成功] 成功獲取頂級自然女聲母帶: {output_wav}")
                    return True
        except Exception:
            continue
    return False

def separate_stems_gpu(input_wav: str, song_name: str, out_dir: str = None) -> tuple[str, str]:
    """
    使用 Demucs / UVR 進行人聲與伴奏分離
    回傳: (vocals_path, instrumental_path)
    out_dir: 指定輸出目錄（預取走暫存區，確認點歌走正式曲庫，避免未確認歌曲污染正式庫）
    """
    base_dir = out_dir or CACHE_DIR
    safe_name = get_safe_filename(song_name)
    vocals_out = os.path.join(base_dir, f"{safe_name}_vocals.wav")
    inst_out = os.path.join(base_dir, f"{safe_name}_instrumental.wav")
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
        "-n", "htdemucs",
        "-d", "cuda",
        "-o", base_dir,
        input_wav
    ]
    try:
        ret = subprocess.run(demucs_cmd, capture_output=True, text=True, timeout=180)
        if ret.returncode == 0:
            # 尋找 htdemucs/{track_name}/vocals.wav & no_vocals.wav
            base_name = os.path.splitext(os.path.basename(input_wav))[0]
            demucs_dir = os.path.join(base_dir, "htdemucs", base_name)
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
        ok = convert_vocal_to_xiaoyi(vocal_in, vocal_out, key=semitones, model_name="xiaoyi", index_rate=0.88, auto_pitch=auto_pitch)
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

def _announce_cover_status(msg: str, song_name: str = ""):
    """📢 翻唱管線即時狀態回報（不走 speech_queue TTS 排隊，唱歌中也能即時顯示字幕+後台，避免觀眾以為卡死）"""
    try:
        print(f"🎤 [翻唱狀態] {msg}")
    except Exception:
        pass
    try:
        core_vts = get_core_vts()
        if core_vts:
            try:
                upd = getattr(core_vts, "update_subtitle", None)
                if callable(upd):
                    try:
                        upd(msg)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                log_fn = getattr(core_vts, "log_print", None)
                if callable(log_fn):
                    log_fn(f"🎤 [翻唱狀態] {msg}")
            except Exception:
                pass
        import services.web_dashboard as web_dash
        try:
            web_dash.broadcast_event("ai_speech", {"text": msg, "target": "dad", "model": "cover-pipeline"})
        except Exception:
            pass
        try:
            web_dash.broadcast_event("cover_status", {"message": msg, "song": song_name or ""})
        except Exception:
            pass
    except Exception:
        pass


def get_cover_pipeline_status(song_name: str = "") -> str:
    """回報管線即時狀態字串，供大腦二輪確認播報（步驟4）"""
    try:
        if IS_SINGING_ACTIVE:
            return f"《{song_name}》已經在舞台上開唱了" if song_name else "已經在舞台上開唱了"
        if _IS_PRODUCING_COVER:
            return f"《{song_name}》已經在處理中了（抓音源/分軌/RVC 進行中），請稍等一下馬上就好" if song_name else "已經在處理中了，馬上就好"
        if song_name:
            safe = get_safe_filename(song_name)
            cached_vocal = os.path.join(CACHE_DIR, f"{safe}_7l_vocal.wav")
            if os.path.exists(cached_vocal) and os.path.getsize(cached_vocal) > 100000:
                return f"《{song_name}》有現成版本，馬上就能開唱"
        return f"已收到《{song_name}》，正在啟動翻唱管線" if song_name else "已收到點歌，正在啟動翻唱管線"
    except Exception:
        return f"《{song_name}》處理中" if song_name else "處理中"


async def _put_outro_first(sq, item):
    """🛡️ 謝幕詞插隊到 speech_queue 最 front：唱歌中預想的回覆已在隊列裡排隊，謝幕必須先播再播閒聊"""
    try:
        if sq is None:
            return False
        try:
            _empty = sq.empty()
        except Exception:
            _empty = False
        if _empty:
            await sq.put(item)
            return True
        try:
            sq._queue.appendleft(item)
            return True
        except Exception:
            await sq.put(item)
            return True
    except Exception:
        return False

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
        if has_queued or is_talking or is_music:
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
    try:
        # 清理歌名引數中的多餘字樣（純字串處理，放重入閘前後皆可，先洗再判狀態才準）
        song_name = _clean_cover_title(song_name)
    except Exception:
        pass
    if _IS_PRODUCING_COVER:
        print(f"⚠️ [翻唱流水線] 當前已有歌曲正在處理中，略過雙軌並發重複調用！")
        _announce_cover_status(get_cover_pipeline_status(song_name), song_name)
        return f"老爸，我已經在準備為大家唱這首歌囉！{get_cover_pipeline_status(song_name)}！"
    _IS_PRODUCING_COVER = True
    cleanup_staging()
    try:
        _announce_cover_status(f"收到點歌《{song_name}》，正在抓音源準備中…", song_name)

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

        # 2. 若人聲與伴奏已拆解但尚未轉換 7L 聲線，走分段流式（首段轉完即開唱）
        if not play_vocal:
            vocal_raw = os.path.join(CACHE_DIR, f"{safe_name}_vocals.wav")
            if os.path.exists(vocal_raw) and os.path.exists(cached_inst) and os.path.getsize(vocal_raw) > 100000:
                print(f"⚡ [人聲伴奏已分離] 分段流式 RVC 直開唱: 《{song_name}》...")
                await wait_for_intro_speech_complete()
                if await _streaming_cover_play(vocal_raw, cached_inst, song_name):
                    outro_msg = f"謝謝大家～剛才為老爸帶來的是翻唱歌曲《{song_name}》！希望老爸喜歡～"
                    core_vts = get_core_vts()
                    if core_vts:
                        sq = getattr(core_vts, "speech_queue", None)
                        if sq:
                            try:
                                await _put_outro_first(sq, {
                                    "text": outro_msg,
                                    "target": "dad",
                                    "raw_text": f"[EXPRESSION: 喜悅] {outro_msg}",
                                    "model": "gemini-3.8-flash"
                                })
                            except Exception:
                                pass
                    return outro_msg
                return f"老爸，7L 剛才嗓子被電阻卡了一下，沒能成功換上我的聲線，待會再為大家唱這首喔！"

        # 若命中快取或已極速轉換完畢，立即開唱！
        if play_vocal:
            play_inst = cached_inst if (os.path.exists(cached_inst) and os.path.getsize(cached_inst) > 100000) else None
            print(f"💾 [7L 專屬翻唱庫] 命中已就緒之獨立人聲與伴奏: 《{song_name}》 (雙軌同步即時放音)")
            # 等候 7L 當前開場白講完
            await wait_for_intro_speech_complete()
            await play_cover_audio(play_vocal, song_name, inst_path=play_inst)

            outro_msg = f"謝謝大家～剛才為老爸帶來的是翻唱歌曲《{song_name}》！希望老爸喜歡～"
            core_vts = get_core_vts()
            if core_vts:
                sq = getattr(core_vts, "speech_queue", None)
                if sq:
                    try:
                        await _put_outro_first(sq, {
                            "text": outro_msg,
                            "target": "dad",
                            "raw_text": f"[EXPRESSION: 喜悅] {outro_msg}",
                            "model": "gemini-3.8-flash"
                        })
                    except Exception:
                        pass
            return outro_msg

        # 2.5 暫存晉升：預取過的分軌直接轉正，省掉下載＋分離
        staged_v = os.path.join(STAGING_DIR, f"{safe_name}_vocals.wav")
        staged_i = os.path.join(STAGING_DIR, f"{safe_name}_instrumental.wav")
        if (os.path.exists(staged_v) and os.path.exists(staged_i)
                and os.path.getsize(staged_v) > 100000):
            try:
                shutil.copy2(staged_v, os.path.join(CACHE_DIR, f"{safe_name}_vocals.wav"))
                shutil.copy2(staged_i, os.path.join(CACHE_DIR, f"{safe_name}_instrumental.wav"))
                print(f"⚡ [暫存晉升] 《{song_name}》預取分軌轉正，跳過下載＋分離！")
            except Exception:
                pass

        print(f"🚀 [7L 全自動翻唱引擎啟動] 目標曲目: 《{song_name}》")
        raw_wav = os.path.join(CACHE_DIR, f"{safe_name}_raw.wav")

        # 步驟 1: 下載
        success = await asyncio.to_thread(download_youtube_audio, song_name, raw_wav)
        if not success or not os.path.exists(raw_wav):
            _announce_cover_status(f"《{song_name}》音源抓取失敗，待會再試試！", song_name)
            return f"老爸，在 YouTube 找《{song_name}》時麥克風卡了一下，待會再試試！"

        # 步驟 2: 分離伴奏與人聲
        _announce_cover_status(f"《{song_name}》抓到音源了，正在分離人聲跟伴奏…", song_name)
        vocal_wav, inst_wav = await asyncio.to_thread(separate_stems_gpu, raw_wav, song_name)

        # 步驟 3+4: 分段 RVC＋邊播邊轉（首段轉完即開唱，不再等整首）
        _announce_cover_status(f"《{song_name}》分軌完成，正在換上我的聲音（分段轉換中）…", song_name)
        await wait_for_intro_speech_complete()
        sang = await _streaming_cover_play(vocal_wav, inst_wav, song_name)
        if not sang:
            return f"老爸，7L 剛才嗓子被電阻卡了一下，沒能成功換上我的聲線，待會再為大家唱這首喔！"

        # 步驟 5: 演唱完畢後謝幕詞插隊最前（先謝幕再播閒聊）
        outro_msg = f"謝謝大家～剛才為老爸帶來的是翻唱歌曲《{song_name}》！希望老爸喜歡～"
        core_vts = get_core_vts()
        if core_vts:
            sq = getattr(core_vts, "speech_queue", None)
            if sq:
                try:
                    await _put_outro_first(sq, {
                        "text": outro_msg,
                        "target": "dad",
                        "raw_text": f"[EXPRESSION: 喜悅] {outro_msg}",
                        "model": "gemini-3.8-flash"
                    })
                except Exception:
                    pass

        return outro_msg
    finally:
        _IS_PRODUCING_COVER = False

def _split_vocal_timeline(vocal_path: str, chunk_target: float = 30.0):
    """找靜音點切分人聲音軌：每 ~30s 在 [t+25, t+38] 窗內找 RMS 最小點下刀；
    剩餘 <40s 直接收尾。回 [(start_s, end_s)]。失敗回整軌單段。"""
    try:
        import soundfile as sf
        import numpy as np
        data, sr = sf.read(vocal_path, always_2d=True)
        total_s = len(data) / float(sr)
        if total_s <= 40.0:
            return [(0.0, total_s)]
        mono = data.mean(axis=1).astype(np.float64)
        frame = max(1, int(sr * 0.2))
        nfr = len(mono) // frame
        rms = np.sqrt((mono[:nfr * frame].reshape(nfr, frame) ** 2).mean(axis=1) + 1e-12)
        bounds = [0.0]
        t = 0.0
        while total_s - t > 40.0:
            lo, hi = t + 25.0, min(t + 38.0, total_s)
            i0, i1 = int(lo / 0.2), int(hi / 0.2)
            i0 = max(0, min(i0, nfr - 1))
            i1 = max(i0 + 1, min(i1, nfr))
            cut_i = i0 + int(np.argmin(rms[i0:i1]))
            t = min(cut_i * 0.2, total_s)
            bounds.append(t)
        bounds.append(total_s)
        segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] > 5.0]
        return segs or [(0.0, total_s)]
    except Exception as e:
        print(f"⚠️ [分段切分回退整軌]: {e}")
        try:
            import soundfile as sf
            info = sf.info(vocal_path)
            return [(0.0, float(info.frames) / float(info.samplerate or 44100))]
        except Exception:
            return [(0.0, 180.0)]


def _slice_wav(in_path: str, start_s: float, end_s: float, out_path: str):
    """按秒切段寫檔（保留原 sr/聲道）。"""
    import soundfile as sf
    data, sr = sf.read(in_path, always_2d=True)
    i0 = max(0, int(start_s * sr))
    i1 = max(i0 + 1, min(len(data), int(end_s * sr)))
    sf.write(out_path, data[i0:i1], sr)
    return out_path


def _align_vocal_to_inst(conv_vocal_path: str, ref_samples: int, ref_sr: int, out_path: str):
    """RVC 產出對齊伴奏段：重取樣＋補齊/裁剪，確保雙軌同毫秒。"""
    import soundfile as sf
    import numpy as np
    data, sr = sf.read(conv_vocal_path, always_2d=True)
    if data.shape[1] > 1:
        data = data.mean(axis=1, keepdims=True)
    if sr != ref_sr and len(data) > 1:
        old_idx = np.linspace(0.0, 1.0, num=len(data))
        new_len = max(1, int(len(data) * ref_sr / sr))
        data = np.interp(np.linspace(0.0, 1.0, num=new_len), old_idx, data[:, 0]).reshape(-1, 1)
        sr = ref_sr
    if len(data) < ref_samples:
        pad = np.zeros((ref_samples - len(data), 1), dtype=data.dtype)
        data = np.concatenate([data, pad], axis=0)
    else:
        data = data[:ref_samples]
    sf.write(out_path, data, ref_sr)
    return out_path


async def _streaming_cover_play(vocal_wav: str, inst_wav: str | None, song_name: str) -> bool:
    """🎤 分段流式翻唱：30s 大塊靜音點切分 → 首段轉完即開唱 → 後段邊播邊轉 queue 接續。
    回 True=播完（或播過一段以上後中斷，照發謝幕），False=一段都沒播成。"""
    global IS_SINGING_ACTIVE
    work_dir = os.path.join(CACHE_DIR, f"stream_{get_safe_filename(song_name)}")
    os.makedirs(work_dir, exist_ok=True)
    converted_parts = []
    started = False
    ref_sr = 44100
    inst_chunks = []
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
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass
        ch_vocal = pygame.mixer.Channel(6)
        ch_inst = pygame.mixer.Channel(7)
        ch_vocal.stop()
        ch_inst.stop()

        import soundfile as sf
        inst_data, inst_sr = (sf.read(inst_wav, always_2d=True) if inst_wav and os.path.exists(inst_wav) else (None, 44100))
        if inst_data is not None and inst_data.shape[1] > 1:
            inst_data = inst_data.mean(axis=1, keepdims=True)
        ref_sr = inst_sr if inst_data is not None else 44100

        segments = _split_vocal_timeline(vocal_wav)
        print(f"🎤 [分段流式] 《{song_name}》切成 {len(segments)} 段，首段轉完即開唱！")
        _announce_cover_status(f"《{song_name}》分軌完成，正在換上我的聲音（第 1/{len(segments)} 段）…", song_name)

        for i, (s, e) in enumerate(segments):
            ip = os.path.join(work_dir, f"inst_{i:02d}.wav")
            if inst_data is None:
                inst_chunks.append(None)
                continue
            i0 = max(0, int(s * inst_sr))
            i1 = max(i0 + 1, min(len(inst_data), int(e * inst_sr)))
            sf.write(ip, inst_data[i0:i1], inst_sr)
            inst_chunks.append(ip)

        snd_keep = []  # 防 GC：播完前 удержи Sound 物件
        for i, (s, e) in enumerate(segments):
            if not IS_SINGING_ACTIVE:
                print("🛑 [分段流式] 演唱中斷，停止後續轉換")
                return started
            seg_in = os.path.join(work_dir, f"vocal_in_{i:02d}.wav")
            seg_raw = os.path.join(work_dir, f"vocal_7l_{i:02d}.wav")
            seg_out = os.path.join(work_dir, f"vocal_play_{i:02d}.wav")
            _slice_wav(vocal_wav, s, e, seg_in)
            if i > 0:
                _announce_cover_status(f"《{song_name}》演唱中…（{i + 1}/{len(segments)} 段準備中）", song_name)
            ok = await asyncio.to_thread(pitch_shift_vocal_to_female, seg_in, seg_raw, 0.0)
            if not ok or not os.path.exists(seg_raw):
                print(f"❌ [分段流式] 第 {i + 1} 段聲線轉換失敗，中止演唱")
                _announce_cover_status(f"《{song_name}》第 {i + 1} 段嗓子卡住了，先停在這！", song_name)
                return started
            ref_n = 0
            if inst_chunks[i]:
                info = sf.info(inst_chunks[i])
                ref_n, ref_sr = info.frames, info.samplerate
            else:
                ref_n = sf.info(seg_raw).frames
            _align_vocal_to_inst(seg_raw, ref_n, ref_sr, seg_out)
            converted_parts.append(seg_out)

            snd_v = pygame.mixer.Sound(seg_out)
            snd_i = pygame.mixer.Sound(inst_chunks[i]) if inst_chunks[i] else None
            snd_keep.extend([x for x in (snd_v, snd_i) if x])
            if not started:
                ch_vocal.set_volume(0.67)
                if snd_i:
                    ch_inst.set_volume(0.55)
                    ch_inst.play(snd_i)
                ch_vocal.play(snd_v)
                if core_vts:
                    setattr(core_vts, "CURRENT_SPEECH_START_TIME", time.time())
                print(f"🎤 [7L 舞台開唱] 《{song_name}》第 1 段開唱（後段邊播邊轉）！")
                started = True
            else:
                while IS_SINGING_ACTIVE and ch_vocal.get_queue() is not None:
                    await asyncio.sleep(0.2)
                if not IS_SINGING_ACTIVE:
                    return True
                ch_vocal.queue(snd_v)
                if snd_i:
                    while IS_SINGING_ACTIVE and ch_inst.get_queue() is not None:
                        await asyncio.sleep(0.2)
                    if IS_SINGING_ACTIVE:
                        ch_inst.queue(snd_i)
            if core_vts:
                try:
                    extract_fn = getattr(core_vts, "extract_audio_mouth_envelope", None)
                    if extract_fn:
                        setattr(core_vts, "CURRENT_MOUTH_ENVELOPE", extract_fn(snd_v, fps=25))
                        setattr(core_vts, "CURRENT_SMOOTH_MOUTH", 0.0)
                except Exception:
                    pass
            await asyncio.sleep(0.1)

        while (ch_vocal.get_busy() or ch_vocal.get_queue() is not None
               or (inst_chunks and inst_chunks[0] and (ch_inst.get_busy() or ch_inst.get_queue() is not None))) and IS_SINGING_ACTIVE:
            await asyncio.sleep(0.3)
        print(f"✨ [7L 舞台開唱] 《{song_name}》演唱完畢！")

        try:
            import soundfile as sf2
            import numpy as np2
            full = []
            for p in converted_parts:
                d, _ = sf2.read(p, always_2d=True)
                full.append(d)
            if full:
                safe = get_safe_filename(song_name)
                sf2.write(os.path.join(CACHE_DIR, f"{safe}_7l_vocal.wav"),
                          np2.concatenate(full, axis=0), ref_sr)
        except Exception as e:
            print(f"⚠️ [整軌存檔略過]: {e}")
        return True
    except Exception as e:
        print(f"❌ [分段流式異常]: {e}")
        return started
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
        IS_SINGING_ACTIVE = False
        try:
            pygame.mixer.Channel(6).stop()
            pygame.mixer.Channel(7).stop()
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
                    setattr(core_vts, "CURRENT_MOUTH_ENVELOPE", extract_fn(snd_vocal, fps=25))
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

        inst_info = " + 獨立伴奏雙軌同步" if snd_inst else " (純人聲清唱)"
        print(f"🎤 [7L 舞台開唱] 正在演唱《{song_name}》（7L 草莓甜妹主唱{inst_info}）！")
        
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
