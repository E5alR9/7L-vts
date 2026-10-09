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
from collections import deque

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

# —— 點歌排隊（2026-10-09：台上有人在唱就排隊＋背景 RVC 照做，不再直接丟掉）——
#  parade: 請求進 SONG_REQUEST_QUEUE → 背景一次只做一首準備（GPU 安全）→
#  備好進 READY_SONGS → 舞台空了就開唱 → 每首結束遞謝幕紙條 → 下一首。
SONG_REQUEST_QUEUE = deque()   # 待準備：{"title", "requester"}
READY_SONGS = deque()          # 已備好待播：{"title", "vocal", "inst", "requester", "gen"}
MAX_PENDING_SONGS = 5          # 待播上限（防彈幕洗版；備好＋在唱的不計）
_ACTIVE_TITLES = set()         # 準備中＋備好＋演唱中的去重鍵（見 _dedupe_key）
_PIPELINE_GEN = 0              # 世代計數：stop_singing() 遞增，遲到的背景任務自動丟棄
_ORCH_TASK = None
_PREPARE_TASK = None

def get_core_vts():
    """動態取得當前運行的主核心模組，杜絕重複 import 導致 .env 與全域狀態衝突"""
    return sys.modules.get("vts_7L_test") or sys.modules.get("__main__")

def stop_singing():
    """立即中斷當前 7L 翻唱演奏並恢復狀態"""
    global IS_SINGING_ACTIVE, _PIPELINE_GEN
    IS_SINGING_ACTIVE = False
    # 停止＝整個不唱了：待播＋備好全部清空，世代遞增讓遲到的背景準備自動丟棄
    _PIPELINE_GEN += 1
    n_q = len(SONG_REQUEST_QUEUE)
    n_r = len(READY_SONGS)
    SONG_REQUEST_QUEUE.clear()
    READY_SONGS.clear()
    _ACTIVE_TITLES.clear()
    if n_q or n_r:
        print(f"🧹 [翻唱隊列] 已清空待播 {n_q} 首＋備好待播 {n_r} 首。")
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

def _dedupe_key(title: str) -> str:
    """去重鍵：用實際快取檔名歸一化（同檔＝同首歌，連「晴天」vs「晴天！」這種都算同一首）"""
    return get_safe_filename((title or "").strip()).casefold()

def _stage_busy() -> bool:
    """舞台是否有人在唱（含主核心同步過來的狀態）"""
    if IS_SINGING_ACTIVE:
        return True
    core_vts = get_core_vts()
    if core_vts:
        if getattr(core_vts, "IS_SINGING_ACTIVE", False):
            return True
        if getattr(core_vts, "current_ai_state", "") == "SINGING":
            return True
    return False

def _send_brain_slip(text: str) -> bool:
    """給 Live 主腦遞紙條（跟本檔謝幕紙條同通道）。"""
    try:
        from vts_7L_test import GLOBAL_LIVE_SESSION
        if GLOBAL_LIVE_SESSION:
            asyncio.create_task(GLOBAL_LIVE_SESSION.send_realtime_input(text=text))
            return True
    except Exception as e:
        print(f"⚠️ [翻唱引擎] 紙條傳送失敗 ({e})")
    return False

def _ensure_orchestrator():
    """確保調度協程活著（同步、可重複呼叫；無 event loop 時靜默跳過等下次請求）。"""
    global _ORCH_TASK
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _ORCH_TASK is None or _ORCH_TASK.done():
        _ORCH_TASK = loop.create_task(_sing_orchestrator())

def request_cover_song(song_name: str, requester: str = "") -> str:
    """點歌入口（同步、零等待）：有誰寫誰 requester。回傳給大腦看的狀態文字。

    - 台上沒人＋沒在準備 → 立刻開工，回「準備好就開唱」
    - 台上有人／準備中 → 排入隊列，背景 RVC 照做，回排隊位置
    - 重複／隊列滿 → 誠實回報，不再無聲丟掉
    """
    title = re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', (song_name or "").strip())
    title = re.sub(r'[\'"]?$', '', title.strip()).strip().strip('「」『』')
    if not title:
        return "這首歌名是空的，跳過囉！"
    key = _dedupe_key(title)
    if key in _ACTIVE_TITLES:
        return f"《{title}》已經在唱／排隊／準備中了，不重複排入！"
    if len(SONG_REQUEST_QUEUE) >= MAX_PENDING_SONGS:
        return f"點歌隊列滿了（最多 {MAX_PENDING_SONGS} 首待播），等唱完幾首再點！"
    idle = ((_ORCH_TASK is None or _ORCH_TASK.done())
            and not READY_SONGS and not _stage_busy()
            and (_PREPARE_TASK is None or _PREPARE_TASK.done()))
    SONG_REQUEST_QUEUE.append({"title": title, "requester": (requester or "").strip()})
    _ACTIVE_TITLES.add(key)
    _ensure_orchestrator()
    if idle:
        return f"已排程 7L 本人演唱《{title}》（點歌人只是點歌，唱歌的是 7L），背景準備好就開唱！"
    ahead = len(READY_SONGS) + len(SONG_REQUEST_QUEUE) - 1
    tail = "（下一首就輪到它）" if ahead <= 0 else f"（前面還有 {ahead} 首）"
    return f"《{title}》已排入點歌隊列{tail}，背景 RVC 會接著做、唱完手上這首就輪到它！"

async def _sing_orchestrator():
    """隊列調度：一次只做一首背景準備（GPU 安全），備好＋舞台空了就開唱，全空就收工。"""
    global _ORCH_TASK, _PREPARE_TASK, _IS_PRODUCING_COVER
    _IS_PRODUCING_COVER = True
    try:
        while True:
            # 1. 有備好的歌且舞台空了 → 開唱（await 期間背景準備可並行）
            if READY_SONGS and not _stage_busy():
                item = READY_SONGS.popleft()
                await play_prepared_song(item["title"], item["vocal"], item["inst"], item["gen"])
                continue
            # 2. 有待準備且沒有準備任務在跑 → 開一個背景準備（唱歌中也能 RVC）
            if SONG_REQUEST_QUEUE and (_PREPARE_TASK is None or _PREPARE_TASK.done()):
                item = SONG_REQUEST_QUEUE.popleft()
                _PREPARE_TASK = asyncio.create_task(_prepare_worker(item, _PIPELINE_GEN))
            # 3. 全空且舞台空 → 收工（下次點歌再啟動，不留殭屍任務）
            prep_busy = _PREPARE_TASK is not None and not _PREPARE_TASK.done()
            if not SONG_REQUEST_QUEUE and not READY_SONGS and not _stage_busy() and not prep_busy:
                break
            await asyncio.sleep(0.5)
    finally:
        _ORCH_TASK = None
        _IS_PRODUCING_COVER = False

async def _prepare_worker(item, gen: int):
    """背景準備一首歌（下載→分離→RVC）：成功進 READY，失敗遞紙條，全程不擋台上演唱。"""
    title = item["title"]
    try:
        vocal, inst = await prepare_cover_song(title)
        if gen != _PIPELINE_GEN:
            print(f"🛑 [翻唱隊列] 《{title}》準備完成但已被停止，丟棄不上台。")
            return
        if vocal:
            READY_SONGS.append({"title": title, "vocal": vocal, "inst": inst,
                                "requester": item.get("requester", ""), "gen": gen})
            print(f"✅ [翻唱隊列] 《{title}》背景準備完成，已排入待播！")
        else:
            _ACTIVE_TITLES.discard(_dedupe_key(title))
            _send_brain_slip(f"[系統提示：剛才點的《{title}》背景準備失敗（下載／分離／轉換卡住），請自然地跟大家說這首先跳過、可以再點別首！]")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"❌ [翻唱準備異常] 《{title}》: {e}")
        _ACTIVE_TITLES.discard(_dedupe_key(title))
        if gen == _PIPELINE_GEN:
            _send_brain_slip(f"[系統提示：剛才點的《{title}》背景準備失敗（下載／分離／轉換卡住），請自然地跟大家說這首先跳過、可以再點別首！]")

async def play_prepared_song(title: str, vocal_path: str, inst_path: str, gen: int) -> str:
    """播一首備好的歌：等開場白 → 世代檢查 → 開唱 → 謝幕紙條（含隊列深度）。"""
    key = _dedupe_key(title)
    try:
        await wait_for_intro_speech_complete()
        if gen != _PIPELINE_GEN:
            print(f"🛑 [翻唱隊列] 《{title}》開唱前已被停止，跳過。")
            return f"《{title}》已停止，不開唱。"
        await play_cover_audio(vocal_path, title, inst_path=inst_path)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"❌ [翻唱開唱異常] 《{title}》: {e}")
        return f"《{title}》開唱失敗，跳過。"
    finally:
        _ACTIVE_TITLES.discard(key)
    if gen != _PIPELINE_GEN:
        return f"《{title}》已停止。"
    depth = len(SONG_REQUEST_QUEUE) + len(READY_SONGS)
    tail = f"後面還有 {depth} 首在排隊，再接著唱！" if depth > 0 else ""
    _send_brain_slip(f"[系統提示：妳剛才演唱完畢了歌曲《{title}》，請自然地向老爸與觀眾謝幕，可以順便問問他們覺得好不好聽！{tail}]")
    print(f"🚨 [翻唱引擎] 已將謝幕指示塞給 Live 主腦，由主腦動態接管發言！")
    return f"謝謝大家～剛才唱給大家的是 7L 的翻唱歌曲《{title}》！希望老爸喜歡～"

async def produce_and_sing_cover(song_name: str, requester: str = "") -> str:
    """點歌入口（相容舊名）：一律進隊列；台上有人就排隊＋背景 RVC 照做，不再丟掉。"""
    return request_cover_song(song_name, requester)
async def prepare_cover_song(song_name: str):
    """背景準備一首歌（查快取→下載→分離→RVC），成功回 (vocal, inst)，失敗回 (None, None)。
    只做準備、不開唱；開唱由 play_prepared_song 經調度器執行。"""
    # 清理歌名引數中的多餘字樣（request_cover_song 已清過，這裡防直接調用）
    song_name = re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', (song_name or "").strip())
    song_name = re.sub(r'[\'"]?$', '', song_name.strip()).strip().strip('「」『』')
    if not song_name:
        return None, None
    try:

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

        # 若命中快取或已極速轉換完畢，直接回傳備好路徑（開唱由調度器執行）
        if play_vocal:
            play_inst = cached_inst if (os.path.exists(cached_inst) and os.path.getsize(cached_inst) > 100000) else None
            print(f"💾 [7L 專屬翻唱庫] 命中已就緒之獨立人聲與伴奏: 《{song_name}》 (雙軌同步即時放音)")
            return play_vocal, play_inst

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
            print(f"❌ [翻唱準備失敗] 在 YouTube 找不到《{song_name}》可用的高音質音軌。")
            return None, None

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
            return None, None

        return trans_vocal, inst_wav
    except Exception as e:
        print(f"❌ [翻唱準備異常] 《{song_name}》: {e}")
        return None, None

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
            
            # 🎤 唱歌自動拿出麥克風 (不重置其他表情，單獨開關麥克風)
            import services.vts_client as vc
            if vc.GLOBAL_VTS:
                async def _toggle_mic(active=True):
                    try:
                        await asyncio.wait_for(vc.GLOBAL_VTS.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ToggleMic",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": "话筒.exp3.json", "active": active}
                        }), timeout=0.5)
                    except Exception: pass
                asyncio.create_task(_toggle_mic(True))

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
            
        # 唱歌結束自動收起麥克風 (不重置其他表情)
        if core_vts:
            import services.vts_client as vc
            if vc.GLOBAL_VTS:
                async def _toggle_mic_off():
                    try:
                        await asyncio.wait_for(vc.GLOBAL_VTS.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ToggleMic",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": "话筒.exp3.json", "active": False}
                        }), timeout=0.5)
                    except Exception: pass
                asyncio.create_task(_toggle_mic_off())
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
        print("點歌結果:", res)
        # 等背景隊列排空（準備＋演唱跑完才結束）
        for _ in range(3600):
            if (not SONG_REQUEST_QUEUE and not READY_SONGS and not _stage_busy()
                    and (_ORCH_TASK is None or _ORCH_TASK.done())
                    and (_PREPARE_TASK is None or _PREPARE_TASK.done())):
                break
            await asyncio.sleep(1)
        print("隊列已排空。")
    asyncio.run(test())
