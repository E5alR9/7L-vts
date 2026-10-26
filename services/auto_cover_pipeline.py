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
import functools
import subprocess
import shutil
import time
import pygame
from collections import deque

import core.stage_state as stage
from core.utils import log_swallowed, spawn

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
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)  # 不指定會用 cp950 解 yt-dlp 的 UTF-8 輸出，讀取執行緒直接炸
            for f in os.listdir(CACHE_DIR):
                if f.startswith("temp_dl_") and f.endswith(".wav"):
                    src = os.path.join(CACHE_DIR, f)
                    shutil.move(src, output_wav)
                    print(f"✅ [YT-DLP 下載成功] 成功獲取高音質母帶: {output_wav}")
                    return True
        except Exception:
            continue
    return False

def _convert_local_to_raw(src_mp3: str, output_wav: str) -> bool:
    """自創曲入口：本地 MP3→44.1k 立體聲 wav（對齊 yt-dlp 產出規格，下游不分流）。
    已有合格 raw 直接沿用，不重轉。同步函數，調用方丟執行緒。"""
    try:
        if os.path.exists(output_wav) and os.path.getsize(output_wav) > 100000:
            print(f"💾 [快取命中] 已存在自創曲音軌: {output_wav}")
            return True
        cmd = [FFMPEG_EXE, "-y", "-i", src_mp3, "-ar", "44100", "-ac", "2", output_wav]
        ret = subprocess.run(cmd, capture_output=True, timeout=120)
        if ret.returncode == 0 and os.path.exists(output_wav) and os.path.getsize(output_wav) > 10000:
            print(f"✅ [自創曲載入成功] 高音質母帶: {output_wav}")
            return True
    except Exception as e:
        print(f"⚠️ [自創曲轉檔異常]: {e}")
    return False


def separate_stems_gpu(input_wav: str, song_name: str, tag: str = "") -> tuple[str, str]:
    """
    使用 Demucs / UVR 進行人聲與伴奏分離
    回傳: (vocals_path, instrumental_path)
    tag：快取命名空間前綴（自創曲傳 "orig_"，與翻唱快取零碰撞；預設空字串行為不變）
    """
    safe_name = tag + get_safe_filename(song_name)
    vocals_out = os.path.join(CACHE_DIR, f"{safe_name}_vocals.wav")
    inst_out = os.path.join(CACHE_DIR, f"{safe_name}_instrumental.wav")

    if os.path.exists(vocals_out) and os.path.exists(inst_out):
        print(f"💾 [快取命中] 已存在人聲與伴奏分軌檔案！")
        return vocals_out, inst_out

    print("⚡ [AI 人聲分離] Tier-1 Roformer GPU 分離（分鐘級，有進度＋心跳，不空轉）...")
    
    # Tier-1: Mel-Roformer（品質最好；失敗自動降級，絕不卡住管線）
    def _sep_progress(pct: int):
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("rvc_progress", {
                "active": True, "mode": "rvc", "stage": "Roformer GPU 拆解人聲與伴奏",
                "percent": 30 + int(max(0, min(100, pct)) * 0.18), "detail": song_name})
        except Exception:
            pass

    try:
        from services.roformer_sep import separate_roformer
        if separate_roformer(input_wav, vocals_out, inst_out,
                             song_name=song_name, progress_cb=_sep_progress):
            return vocals_out, inst_out
        print("🔄 [Roformer 未成功，降級 Demucs]...")
    except Exception as e:
        print(f"⚠️ [Roformer 模組異常，降級 Demucs]: {e}")

    # Tier-2: demucs 命令
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
        ret = subprocess.run(demucs_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
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
        "-af", "stereotools=mlev=0.015625:slev=1.0",
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
    - auto_pitch=True (預設): 啟用整首統一音域判決（先掃完全部樂句）
      * 整體偏低（低音發聲時長占比 >= 50%）→ 全曲統一 +12 半音 (進入 7L 甜美音域)
      * 整體偏高 → 全曲維持原調 0 半音 (自然甜美不尖叫，連偏低樂句也不動)
      * 同首歌內永遠只有一個偏移值，絕不在樂句邊界忽高忽低
    - semitones: 額外偏移量 (一般保持 0.0)
    - 採用官方 ContentVec + RMVPE 高精度聲學神經引擎
    （註：2026-10-09 曾試過高音三明治［f0 降調＋post-DSP 拉回］，盲聽證明
    post-DSP 本身就會花栗鼠，已整段移除；詳見 git 歷史。）
    """
    try:
        from services.neural_voice_converter import convert_vocal_to_xiaoyi
        _MODEL_PTH = r"C:\Users\qiwai\RVC-WebUI\assets\weights\7L_v2.pth"
        _INDEX_FILE = r"C:\Users\qiwai\RVC-WebUI\assets\indices\7L_v2_added_IVF256_Flat_nprobe_1_7L_v2_v2.index"

        def _valid(path):
            return bool(path) and os.path.exists(path) and os.path.getsize(path) > 10000

        def _run_convert(v_in, v_out, _key, _auto):
            return convert_vocal_to_xiaoyi(
                v_in, v_out, key=_key,
                model_pth=_MODEL_PTH, index_file=_INDEX_FILE,
                index_rate=0.88, auto_pitch=_auto)

        mode_str = "整首統一音域判決" if auto_pitch else f"固定 key={semitones:+0.1f}"
        print(f"👑 [7L 專屬曉伊原聲音色轉換] 啟用曉伊原生歌聲神經轉換 ({mode_str})...")
        ok = _run_convert(vocal_in, vocal_out, semitones, auto_pitch)
        if ok and _valid(vocal_out):
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
stage.register_singing_probe(lambda: IS_SINGING_ACTIVE)   # 「她在唱嗎」全程式看這個旗（core.stage_state.singing）

# —— 點歌排隊（2026-10-09：台上有人在唱就排隊＋背景 RVC 照做，不再直接丟掉）——
# 流程：請求進 SONG_REQUEST_QUEUE → 背景一次只做一首準備（GPU 安全）→
#  備好進 READY_SONGS → 舞台空了就開唱 → 每首結束遞謝幕紙條 → 下一首。
SONG_REQUEST_QUEUE = deque()   # 待準備：{"title", "requester"}
READY_SONGS = deque()          # 已備好待播：{"title", "vocal", "inst", "requester", "gen"}
MAX_PENDING_SONGS = 5          # 待播上限（防彈幕洗版；備好＋在唱的不計）
_ACTIVE_TITLES = set()         # 準備中＋備好＋演唱中的去重鍵（見 _dedupe_key）
_PIPELINE_GEN = 0              # 世代計數：stop_singing() 遞增，遲到的背景任務自動丟棄
_ORCH_TASK = None
_PREPARE_TASK = None
_PLAY_TASK = None

# 主程式交進來的東西（main() 開機時 bind_host）。以前從 sys.modules 撈主程式模組、或直接 import 主程式，
# 主程式改名或換啟動方式就默默失效；紙條還繞過紙條佇列直接送給主腦，沒去重也沒加鎖（2026-10-25 健檢）
_HOST = {}


def bind_host(speech_queue=None, get_last_tts_end=None, send_brain_slip=None):
    """main() 開機時呼叫：說話佇列、上次講完話的時間、給主腦遞紙條。AI 狀態直接讀寫 core.stage_state。"""
    _HOST.update({k: v for k, v in dict(speech_queue=speech_queue, get_last_tts_end=get_last_tts_end,
                                        send_brain_slip=send_brain_slip).items() if v is not None})


def _ai_state() -> str:
    return stage.ai_state()


def _core_set_ai_state(new: str, reason: str = "", only_from=None):
    """AI 狀態一律走 core.stage_state.set_ai_state（唯一轉換點：主程式登記的日誌、後台廣播照樣會發）。"""
    stage.set_ai_state(new, reason, only_from=only_from)

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
    _MIXED_RENDEZVOUS.clear()
    if n_q or n_r:
        print(f"🧹 [翻唱隊列] 已清空待播 {n_q} 首＋備好待播 {n_r} 首。")
    try:
        if pygame.mixer.get_init():
            pygame.mixer.Channel(6).stop()
            pygame.mixer.Channel(7).stop()
            pygame.mixer.music.stop()
    except Exception:
        pass
    stage.stop_playback()
    _core_set_ai_state("IDLE", "翻唱手動停止", only_from="SINGING")
    print("🛑 [7L 翻唱] 已成功手動停止歌聲與伴奏播放。")


def stop_current_song() -> bool:
    """只停當首（電擊打斷用）：停音訊＋清口型＋放掉舞台，隊列保留下一首照排。
    回 True=當時確實在唱。"""
    global IS_SINGING_ACTIVE, _NOW_PLAYING_TITLE, _PLAY_TASK
    was = bool(IS_SINGING_ACTIVE or _NOW_PLAYING_TITLE or
               (_PLAY_TASK is not None and not _PLAY_TASK.done()))
    if not was:
        return False
    try:
        if _PLAY_TASK is not None and not _PLAY_TASK.done():
            _PLAY_TASK.cancel()
    except Exception:
        pass
    IS_SINGING_ACTIVE = False
    _stopped_title = _NOW_PLAYING_TITLE
    _NOW_PLAYING_TITLE = ""
    #  2026-10-11：電擊打斷要順手拆掉這首的混用會合，不然下次重點同首會撿到
    #  上次沒等完的鋼琴旗，乾等 300 秒（_MIXED_SING_WAIT_SEC）才開唱。
    if _stopped_title:
        _MIXED_RENDEZVOUS.pop(_dedupe_key(_stopped_title), None)
    try:
        if pygame.mixer.get_init():
            pygame.mixer.Channel(6).stop()
            pygame.mixer.Channel(7).stop()
    except Exception:
        pass
    stage.stop_playback()
    _core_set_ai_state("IDLE", "電擊打斷當首", only_from="SINGING")
    print("🛑 [7L 翻唱] 電擊打斷：當首停止（排隊保留）。")
    return True

async def wait_for_intro_speech_complete(timeout: float = 15.0):
    """等候 7L 大腦完成開場白發話，再銜接翻唱開唱。
    2026-10-11：步驟 3 原本無限等——直播間聊不停（Johnny 式連聊）歌就永遠開不了口。
    上限兜底：開場應答約 6 秒，15 秒還在聊就直接開唱（邊唱邊聊好過乾等）。」"""
    if not _HOST:
        return
    # 1. 若大腦還在深度思考中 (THINKING)，先等候大腦產出台詞 (最多等 8 秒)
    t0 = time.time()
    while _ai_state() == "THINKING" and time.time() - t0 < 8.0:
        await asyncio.sleep(0.2)
    # 2. 緩衝等候語音進入 speech_queue 或開始播話
    await asyncio.sleep(0.5)
    # 3. 等候開場白說完 (佇列清空且發話完畢；超時硬開唱)
    t1 = time.time()
    _last_log = 0.0
    while True:
        sq = _HOST.get("speech_queue")
        has_queued = sq and not sq.empty()
        is_talking = _ai_state() == "TALKING"
        is_music = pygame.mixer.get_init() and pygame.mixer.music.get_busy() and not IS_SINGING_ACTIVE

        last_tts_end = (_HOST.get("get_last_tts_end") or (lambda: 0.0))()
        recent_speech = (time.time() - last_tts_end) < 2.5

        if has_queued or is_talking or is_music or recent_speech:
            el = time.time() - t1
            if el >= timeout:
                print(f"⏳ [開場白等待逾時] 背景聊太嗨不等了（{timeout:.0f}s），直接開唱！")
                break
            if el - _last_log >= 10.0:
                _last_log = el
                print(f"⏳ [等開場白] 背景聊天中…{el:.0f}s（{timeout:.0f}s 後不等了直接唱）。")
            await asyncio.sleep(0.3)
        else:
            break

def _dedupe_key(title: str) -> str:
    """去重鍵：用實際快取檔名歸一化（同檔＝同首歌，連「晴天」vs「晴天！」這種都算同一首）"""
    return get_safe_filename((title or "").strip()).casefold()

def is_song_active(song_name: str) -> bool:
    """這首歌是否已在唱／排隊／準備中（斷線救援用，避免重複排入）。"""
    return _dedupe_key(song_name) in _ACTIVE_TITLES

_NOW_PLAYING_TITLE = ""  # 台上正在唱的歌名（混用鋼琴同步用：備好或開唱才跟著彈）

# ── 混用會合（2026-10-11：邊彈邊唱要互相等）──
# 鋼琴視窗開好舉 piano 旗；翻唱要開唱了先等 piano 旗，再舉 sing 旗；兩旗都舉才放。
# 彈唱同一首歌（want_sync，2026-10-25）：翻唱側順便把伴奏轉成鋼琴譜（midi），
# 排一個共同起點（start_at）交給鋼琴側，人聲跟鋼琴照同一個時間點開始，才會真的對拍。
# 任一超時就自己先上，絕不綁架對方。stop_singing 全清。
_MIXED_RENDEZVOUS = {}  # dedupe_key(sing_title) -> 見 arm_mixed_rendezvous
_MIXED_SING_WAIT_SEC = 300.0  # 翻唱等鋼琴上限（譜搜尋再慢也夠了）
_MIXED_LEAD_SEC = 5.0         # 排定起點到開唱的預備時間：鋼琴走位、載譜、方塊先落 1.6 秒都在這段裡
_MIXED_INST_VOLUME = 0.4      # 彈唱同步時原曲伴奏收小（平常 0.55），鋼琴才聽得出來


def arm_mixed_rendezvous(sing_title, want_sync=False):
    """混用開場：建會合點回傳。重複點同首直接覆蓋（去重保證同時只有一單）。
    want_sync：彈的跟唱的是同一首，要用伴奏轉出來的譜同步彈。"""
    rv = {"piano": asyncio.Event(), "sing": asyncio.Event(), "want_sync": bool(want_sync),
          "midi": "", "start_at": None, "piano_gave_up": False}
    _MIXED_RENDEZVOUS[_dedupe_key(sing_title)] = rv
    return rv


async def _mixed_rendezvous_sing(rv, title, inst_path):
    """混用會合（翻唱側）：等鋼琴就位；want_sync 就同時把伴奏轉成鋼琴譜。
    兩邊都好了排共同起點（現在＋_MIXED_LEAD_SEC）寫進 rv 交給鋼琴側並回傳；
    鋼琴沒到、已經自己先彈、轉不出譜都回 None（照舊直接唱）。"""
    midi_task = None
    if rv.get("want_sync"):
        from services.audio_to_score import instrumental_to_piano_midi
        midi_task = asyncio.create_task(asyncio.to_thread(instrumental_to_piano_midi, inst_path or ""))
    print(f"🎤 [混用會合] 《{title}》麥克風就位，等鋼琴就位會合（最多 {_MIXED_SING_WAIT_SEC:.0f} 秒）...")
    piano_ready = False
    try:
        await asyncio.wait_for(rv["piano"].wait(), timeout=_MIXED_SING_WAIT_SEC)
        piano_ready = True
    except asyncio.TimeoutError:
        print("⚠️ [混用會合] 等鋼琴超時，先開唱，鋼琴隨後跟上。")
    if midi_task is not None:
        try:
            rv["midi"] = await midi_task or ""
        except Exception as e:
            print(f"⚠️ [混用會合] 伴奏轉譜異常: {e}")
    start_at = None
    if piano_ready and rv.get("midi") and not rv.get("piano_gave_up"):
        start_at = time.time() + _MIXED_LEAD_SEC
        rv["start_at"] = start_at
        print(f"🎤 [混用會合] 鋼琴就位＋伴奏譜到手，{_MIXED_LEAD_SEC:.0f} 秒後邊彈邊唱同步開演！")
    elif piano_ready:
        print("🎤 [混用會合] 鋼琴就位，邊彈邊唱開演（沒有同步譜，鋼琴照曲名找譜）。")
    rv["sing"].set()
    return start_at


def disarm_mixed_rendezvous(sing_title):
    _MIXED_RENDEZVOUS.pop(_dedupe_key(sing_title or ""), None)


async def _clear_prep_halo() -> bool:
    """開唱清場：臉上只有準備期的暈就摘掉；有別的戲/沒暈就不碰。回 True=摘過。"""
    try:
        import services.vts_client as vc
        halo = (vc.VTS_EXPRESSION_MAP or {}).get("暈")
        face = set(getattr(vc, "CURRENT_ACTIVE_EXPS", None) or set())
        if halo and face == {halo}:
            await vc.set_vts_expression(vc.GLOBAL_VTS, "_RESET_")
            return True
    except Exception:
        pass
    return False


def cover_ready_or_playing(title: str) -> bool:
    """這首翻唱是否已備好待播（READY_SONGS）或正在唱。混用時鋼琴等這個才開彈。"""
    if not (title or "").strip():
        return False
    key = _dedupe_key(title)
    for it in list(READY_SONGS):
        if _dedupe_key((it or {}).get("title", "")) == key:
            return True
    return bool(_NOW_PLAYING_TITLE) and _dedupe_key(_NOW_PLAYING_TITLE) == key

def _stage_busy() -> bool:
    """舞台是否有人在唱（管線旗＋主核心 AI 狀態）"""
    if IS_SINGING_ACTIVE:
        return True
    if _ai_state() == "SINGING":
        return True
    return False


def singing_audio_active() -> bool:
    """歌聲是否在響（單一真相源，2026-10-11）。
    背景：以前主程式也留一份 IS_SINGING_ACTIVE 由這裡 setattr 同步，兩份拷貝必分叉；
    2026-10-23 起旗子只剩本模組這一份（主程式經 is_singing_active() 來問）。
    所有收尾邏輯一律問這個（管線旗＋播放任務＋6/7 軌實響，三處任一即算數）。"""
    if IS_SINGING_ACTIVE or _NOW_PLAYING_TITLE:
        return True
    try:
        if _PLAY_TASK is not None and not _PLAY_TASK.done():
            return True
    except Exception:
        pass
    try:
        if pygame.mixer.get_init():
            if pygame.mixer.Channel(6).get_busy() or pygame.mixer.Channel(7).get_busy():
                return True
    except Exception:
        pass
    return False

def _send_brain_slip(text: str) -> bool:
    """給 Live 主腦遞紙條：走主程式的紙條出口（去重、加鎖、看門狗都在那邊）。"""
    fn = _HOST.get("send_brain_slip")
    try:
        return bool(fn and fn(text))
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


ORIGINAL_WATCH_SEC = int(os.getenv("ORIGINAL_WATCH_SEC", "20") or "20")
_ORIG_PREPARING = set()  # 感測器正在背景準備的 orig_ safe 名（防重複開工）


async def scan_originals_once():
    """掃 originals/ 一輪：有音軌、缺 orig_ 成品 → 背景備好（只準備不排隊，唱一定要明說）。
    GPU 一次只做一首（循序 await，不跟台上搶）。回備好的歌名清單。"""
    done = []
    try:
        import core.hard_command as hc
        os.makedirs(hc.ORIGINALS_DIR, exist_ok=True)
        files = sorted(f for f in os.listdir(hc.ORIGINALS_DIR)
                       if f.lower().endswith((".mp3", ".wav")))
    except Exception:
        return done
    for f in files:
        stem = os.path.splitext(f)[0]
        title = re.sub(r'[_\\-]+', ' ', stem).strip() or stem
        safe = "orig_" + get_safe_filename(title)
        if safe in _ORIG_PREPARING:
            continue
        try:
            ready = os.path.join(CACHE_DIR, f"{safe}_7l_vocal.wav")
            if os.path.exists(ready) and os.path.getsize(ready) > 100000:
                continue
        except Exception:
            log_swallowed()
        _ORIG_PREPARING.add(safe)
        try:
            print(f"👀 [自創曲感測] 發現新檔《{f}》，背景自動 RVC（備好等點，不自動開唱）。")
            vocal, _inst = await prepare_cover_song(
                title, source_mp3=os.path.join(hc.ORIGINALS_DIR, f), origin="original")
            if vocal:
                done.append(title)
        except Exception as e:
            print(f"⚠️ [自創曲感測] 《{title}》背景準備失敗: {e}")
        finally:
            _ORIG_PREPARING.discard(safe)
    return done


async def originals_watch_worker():
    """originals/ 感測常駐（20s 一輪，ORIGINAL_WATCH_SEC 調；0 停用）。
    檔存在本身就是人工節點——只準備不排隊，唱一定要明說「唱X」，跟翻唱同一個口令。"""
    if ORIGINAL_WATCH_SEC <= 0:
        return
    while True:
        try:
            await scan_originals_once()
        except Exception as e:
            print(f"⚠️ [自創曲感測異常]: {e}")
        await asyncio.sleep(ORIGINAL_WATCH_SEC)

def request_cover_song(song_name: str, requester: str = "", source_mp3: str = "", origin: str = "") -> str:
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
    SONG_REQUEST_QUEUE.append({"title": title, "requester": (requester or "").strip(),
                                 "source_mp3": source_mp3 or "", "origin": origin or ""})
    _ACTIVE_TITLES.add(key)
    _ensure_orchestrator()
    if idle:
        return f"已排程 7L 本人演唱《{title}》（點歌人只是點歌，唱歌的是 7L），背景準備好就開唱！"
    ahead = len(READY_SONGS) + len(SONG_REQUEST_QUEUE) - 1
    tail = "（下一首就輪到它）" if ahead <= 0 else f"（前面還有 {ahead} 首）"
    return f"《{title}》已排入點歌隊列{tail}，背景 RVC 會接著做、唱完手上這首就輪到它！"

async def _sing_orchestrator():
    """隊列調度：一次只做一首背景準備（GPU 安全），備好＋舞台空了就開唱，全空就收工。
    播放本身也是背景任務——迴圈全程每 0.5 秒轉一圈，台上唱歌時照樣開新的背景準備。"""
    global _ORCH_TASK, _PREPARE_TASK, _PLAY_TASK, _IS_PRODUCING_COVER
    _IS_PRODUCING_COVER = True
    try:
        while True:
            play_busy = _PLAY_TASK is not None and not _PLAY_TASK.done()
            # 1. 有備好的歌、舞台空了、且沒有播放任務在跑 → 開唱（不 await，做成背景任務）
            if READY_SONGS and not _stage_busy() and not play_busy:
                item = READY_SONGS.popleft()
                _PLAY_TASK = asyncio.create_task(
                    play_prepared_song(item["title"], item["vocal"], item["inst"], item["gen"]))
            # 2. 有待準備且沒有準備任務在跑 → 開一個背景準備（唱歌中也能 RVC）
            if SONG_REQUEST_QUEUE and (_PREPARE_TASK is None or _PREPARE_TASK.done()):
                item = SONG_REQUEST_QUEUE.popleft()
                _PREPARE_TASK = asyncio.create_task(_prepare_worker(item, _PIPELINE_GEN))
            # 3. 全空且舞台空 → 收工（下次點歌再啟動，不留殭屍任務）
            prep_busy = _PREPARE_TASK is not None and not _PREPARE_TASK.done()
            play_busy = _PLAY_TASK is not None and not _PLAY_TASK.done()
            if not SONG_REQUEST_QUEUE and not READY_SONGS and not _stage_busy() and not prep_busy and not play_busy:
                break
            await asyncio.sleep(0.5)
    finally:
        _ORCH_TASK = None
        _IS_PRODUCING_COVER = False

async def _run_with_heartbeat(awaitable_fn, label: str, song: str, interval: float = 30.0):
    """長任務心跳（2026-10-11：分離/RVC 幾分鐘零輸出，看起來像空轉）。
    每 interval 秒打一行進度＋推儀表板；結束自動停。回傳任務結果。"""
    import time as _t
    t0 = _t.time()
    done = False

    async def _ticker():
        while not done:
            await asyncio.sleep(interval)
            if done:
                break
            el = int(_t.time() - t0)
            print(f"⏳ [{label}進行中] 《{song}》…已跑 {el // 60}分{el % 60:02d}秒，還在跑（不是空轉）。")
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("rvc_progress", {
                    "active": True, "mode": "rvc", "stage": f"{label}進行中…",
                    "percent": -1, "detail": f"{song}（已跑{el // 60}分{el % 60:02d}秒）"
                })
            except Exception:
                pass

    tick = asyncio.create_task(_ticker())
    try:
        return await awaitable_fn()
    finally:
        done = True
        tick.cancel()
        try:
            await tick
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


async def _prepare_worker(item, gen: int):
    """背景準備一首歌（下載→分離→RVC）：成功進 READY，失敗遞紙條，全程不擋台上演唱。"""
    title = item["title"]
    try:
        vocal, inst = await prepare_cover_song(title, source_mp3=item.get("source_mp3", ""),
                                               origin=item.get("origin", ""))
        if gen != _PIPELINE_GEN:
            print(f"🛑 [翻唱隊列] 《{title}》準備完成但已被停止，丟棄不上台。")
            return
        if vocal:
            READY_SONGS.append({"title": title, "vocal": vocal, "inst": inst,
                                "requester": item.get("requester", ""), "gen": gen})
            print(f"✅ [翻唱隊列] 《{title}》背景準備完成，已排入待播！")
        else:
            _ACTIVE_TITLES.discard(_dedupe_key(title))
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("rvc_progress", {
                    "active": False, "mode": "rvc", "stage": "準備失敗",
                    "percent": 0, "detail": title})
            except Exception:
                pass
            _is_orig_missing = (item.get("origin") or "") == "original" and not (item.get("source_mp3") or "")
            if _is_orig_missing:
                _send_brain_slip(f"[系統提示：有人點自創曲《{title}》，但 MP3 還沒丟進 songs_library/originals。"
                                  f"請直接跟大家說這首還沒生好、請老爸生好丟進來再點，不要說排程了。]")
            else:
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
    global _NOW_PLAYING_TITLE
    key = _dedupe_key(title)
    try:
        await wait_for_intro_speech_complete()
        if gen != _PIPELINE_GEN:
            print(f"🛑 [翻唱隊列] 《{title}》開唱前已被停止，跳過。")
            return f"《{title}》已停止，不開唱。"
        _NOW_PLAYING_TITLE = title
        # 混用會合：等鋼琴旗（300 秒不到就自己先唱，不綁架）；同一首歌排共同起點，開播後鋼琴照人聲校時
        start_at, on_start = None, None
        _rv = _MIXED_RENDEZVOUS.pop(key, None)
        if _rv is not None:
            start_at = await _mixed_rendezvous_sing(_rv, title, inst_path)
            if start_at:
                def _sync_piano(t0, midi=_rv["midi"]):
                    import services.piano_engine as pe
                    pe.sync_piano_clock(t0, midi)
                on_start = _sync_piano
        # 開唱清場：準備期的暈（busy worker 掛的）別帶上台；臉有別的戲就不碰
        await _clear_prep_halo()
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("rvc_progress", {
                "active": True, "mode": "rvc", "stage": "舞台開唱",
                "percent": 100, "detail": title})
        except Exception:
            pass
        await play_cover_audio(vocal_path, title, inst_path=inst_path, start_at=start_at, on_start=on_start)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"❌ [翻唱開唱異常] 《{title}》: {e}")
        return f"《{title}》開唱失敗，跳過。"
    finally:
        _NOW_PLAYING_TITLE = ""
        _ACTIVE_TITLES.discard(key)
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("rvc_progress", {
                "active": False, "mode": "rvc", "stage": "演唱完畢",
                "percent": 100, "detail": title})
        except Exception:
            pass
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
_PREPARING = set()  # 正在背景準備的 (origin, 去重鍵)：同首併發只做一次
_PREPARE_WAIT_SEC = 600.0


def _prepare_singleflight(fn):
    """同首併發只做一次（2026-10-11：感測器 20s 輪詢 vs 點播撞車會雙開 GPU）。
    先到的做，後到的等（600s 上限＋30s 打點，絕不空轉假象），再進來直接吃快取。
    key 取 (origin, 去重鍵)：大小寫差異頂多多等一次，絕不 double-GPU、不髒快取。"""
    @functools.wraps(fn)
    async def _wrapper(song_name: str = "", source_mp3: str = "", origin: str = "", **kw):
        key = ((origin or ""), _dedupe_key(song_name))
        t0 = time.time()
        _logged = 0.0
        while key in _PREPARING:
            el = time.time() - t0
            if el >= _PREPARE_WAIT_SEC:
                break
            if el - _logged >= 30.0:
                _logged = el
                print(f"⏳ [準備併發等待] 《{song_name}》另一路正在準備，等它做完不重開 GPU（已等 {el:.0f}s）。")
            await asyncio.sleep(3.0)
        _PREPARING.add(key)
        try:
            return await fn(song_name, source_mp3=source_mp3, origin=origin, **kw)
        finally:
            _PREPARING.discard(key)
    return _wrapper


@_prepare_singleflight
async def prepare_cover_song(song_name: str, source_mp3: str = "", origin: str = ""):
    """背景準備一首歌（查快取→下載/本地載入→分離→RVC），成功回 (vocal, inst)，失敗回 (None, None)。
    只做準備、不開唱；開唱由 play_prepared_song 經調度器執行。
    自創曲（origin="original"）：不碰 YouTube，本地 MP3 轉 raw；快取檔名掛 orig_ 前綴，
    與翻唱快取零碰撞（同歌名兩邊各存各的；去重鍵相同，同時只能排一邊）。"""
    # 清理歌名引數中的多餘字樣（request_cover_song 已清過，這裡防直接調用）
    song_name = re.sub(r'^(?:song_name\s*=\s*)?[\'"]?', '', (song_name or "").strip())
    song_name = re.sub(r'[\'"]?$', '', song_name.strip()).strip().strip('「」『』')
    if not song_name:
        return None, None
    try:

        _tag = "orig_" if (origin or "") == "original" else ""
        safe_name = _tag + get_safe_filename(song_name)
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
                log_swallowed()
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
                print(f"⚡ [人聲伴奏已分離] 直接啟動 7L 曉伊 RVC 少女歌聲置換 (整首統一音域判決): 《{song_name}》...")
                rvc_ok = await _run_with_heartbeat(
                    lambda: asyncio.to_thread(pitch_shift_vocal_to_female, vocal_raw, cached_vocal, 0.0),
                    "RVC 聲線置換", song_name)
                if rvc_ok and os.path.exists(cached_vocal) and os.path.getsize(cached_vocal) > 10000:
                    play_vocal = cached_vocal

        # 若命中快取或已極速轉換完畢，直接回傳備好路徑（開唱由調度器執行）
        if play_vocal:
            play_inst = cached_inst if (os.path.exists(cached_inst) and os.path.getsize(cached_inst) > 100000) else None
            print(f"💾 [7L 專屬翻唱庫] 命中已就緒之獨立人聲與伴奏: 《{song_name}》 (雙軌同步即時放音)")
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("rvc_progress", {
                    "active": True, "mode": "rvc", "stage": "快取命中即將開唱",
                    "percent": 95, "detail": song_name})
            except Exception:
                pass
            return play_vocal, play_inst

        print(f"🚀 [7L 全自動翻唱引擎啟動] 目標曲目: 《{song_name}》")
        try:
            import services.web_dashboard as web_dash
            web_dash.broadcast_event("rvc_progress", {
                "active": True, "mode": "rvc", "stage": "下載 YouTube 高音質音軌", "percent": 10, "detail": song_name
            })
        except Exception: pass
        
        raw_wav = os.path.join(CACHE_DIR, f"{safe_name}_raw.wav")
        
        # 步驟 1: 音軌來源（自創曲走本地 MP3，不碰 YouTube；orig_ 命名空間已在 safe_name 區隔）
        if (origin or "") == "original":
            try:
                import services.web_dashboard as web_dash
                web_dash.broadcast_event("rvc_progress", {
                    "active": True, "mode": "rvc", "stage": "載入自創曲音軌",
                    "percent": 10, "detail": song_name})
            except Exception:
                pass
            if not source_mp3 or not os.path.exists(source_mp3):
                print(f"❌ [自創曲缺檔] 《{song_name}》的 MP3 還沒丟進 songs_library/originals。")
                return None, None
            if not await asyncio.to_thread(_convert_local_to_raw, source_mp3, raw_wav):
                print(f"❌ [自創曲轉檔失敗] 《{song_name}》")
                return None, None
            success = True
        else:
            # YouTube 翻唱：下載高音質音軌
            success = await asyncio.to_thread(download_youtube_audio, song_name, raw_wav)
        if not success or not os.path.exists(raw_wav):
            try:
                web_dash.broadcast_event("rvc_progress", {"active": False, "stage": "下載失敗", "percent": 0})
            except Exception: pass
            print(f"❌ [翻唱準備失敗] 在 YouTube 找不到《{song_name}》可用的高音質音軌。")
            return None, None

        try:
            web_dash.broadcast_event("rvc_progress", {
                "active": True, "mode": "rvc", "stage": "Roformer GPU 拆解人聲與伴奏", "percent": 30, "detail": song_name
            })
        except Exception: pass

        # 步驟 2: 分離伴奏與人聲（幾分鐘級，掛心跳以免看起來空轉）
        _tag = "orig_" if (origin or "") == "original" else ""
        vocal_wav, inst_wav = await _run_with_heartbeat(
            lambda: asyncio.to_thread(separate_stems_gpu, raw_wav, song_name, _tag),
            "人聲分離", song_name)

        try:
            web_dash.broadcast_event("rvc_progress", {
                "active": True, "mode": "rvc", "stage": "準備進行 RVC 聲線置換", "percent": 50, "detail": song_name
            })
        except Exception: pass

        # 步驟 3: RVC 原生少女歌聲轉換 (整首統一音域：整體偏低全曲+12半音，整體偏高全曲維持原調)
        trans_vocal = os.path.join(CACHE_DIR, f"{safe_name}_7l_vocal.wav")
        rvc_ok = await _run_with_heartbeat(
            lambda: asyncio.to_thread(pitch_shift_vocal_to_female, vocal_wav, trans_vocal, 0.0),
            "RVC 聲線置換", song_name)
        if not rvc_ok or not os.path.exists(trans_vocal) or os.path.getsize(trans_vocal) < 10000:
            print("❌ [翻唱管線中斷] RVC 神經歌聲置換未成功，終止播放避免直出原唱！")
            return None, None

        return trans_vocal, inst_wav
    except Exception as e:
        print(f"❌ [翻唱準備異常] 《{song_name}》: {e}")
        return None, None

async def play_cover_audio(vocal_path: str, song_name: str, inst_path: str = None, start_at: float = None, on_start=None):
    """
    雙軌同步極致舞台放音：
    - 軌道 6 (Vocal Track): 7L 純淨人聲，專門連動 Live2D 對嘴包絡（0 伴奏鼓點干擾）
    - 軌道 7 (Instrumental Track): 獨立伴奏立體聲同步齊發（無需混音壓制成同一個 MP3）
    - start_at（彈唱同步）：等到這個時間點（time.time()）才齊發，伴奏收小讓鋼琴出來；
      開播的實際時間交給 on_start（鋼琴照它校時）
    """
    global IS_SINGING_ACTIVE
    try:
        IS_SINGING_ACTIVE = True
        stage.IS_MP3_PLAYING = True
        _core_set_ai_state("SINGING", f"準備開唱《{song_name}》")

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
        try:
            from services.audio_analysis import extract_audio_mouth_envelope
            stage.CURRENT_MOUTH_ENVELOPE = await asyncio.to_thread(extract_audio_mouth_envelope, snd_vocal, 25)
            stage.CURRENT_SMOOTH_MOUTH = 0.0
            print("👄 [口型同步] 成功將【純人聲音軌】波形包絡同步至 Live2D 對嘴中樞（100% 精準對嘴，零伴奏雜音干擾）！")
        except Exception as env_err:
            print(f"⚠️ [口型波形提取警告]: {env_err}")

        # 🎛️ 專業立體聲即時動態混音平衡：人聲清晰飽滿 (0.67)，伴奏音樂襯托 (0.55)
        ch_vocal.set_volume(0.67)
        if snd_inst:
            ch_inst.set_volume(_MIXED_INST_VOLUME if start_at else 0.55)

        if start_at:
            # 彈唱同步：等到共同起點才放（asyncio.sleep 在 Windows 只準到 15ms 左右，最後一小段空轉）
            remain = start_at - time.time()
            if remain > 0.03:
                await asyncio.sleep(remain - 0.03)
            while time.time() < start_at:
                pass

        # 🚀 雙軌同毫秒精準齊發，同微秒記錄對嘴起步基準時間戳
        if snd_inst:
            ch_inst.play(snd_inst)
        ch_vocal.play(snd_vocal)
        stage.start_playback()   # 播放旗標＋對嘴起點（嘴型包絡上面已經設好）
        if on_start:
            try:
                on_start(stage.CURRENT_SPEECH_START_TIME)
            except Exception as sync_err:
                print(f"⚠️ [彈唱同步] 鋼琴校時失敗: {sync_err}")
        if _HOST:
            _core_set_ai_state("SINGING", f"雙軌齊發《{song_name}》")
            
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
                spawn(_toggle_mic(True))

        inst_info = " + 獨立伴奏雙軌同步" if snd_inst else " (純人聲清唱)"
        print(f"🎤 [7L 舞台開唱] 正在演唱《{song_name}》（7L 甜妹主唱{inst_info}）！")
        
        # 完整播放整首歌曲，雙軌皆播畢或被手動指令中斷
        while (ch_vocal.get_busy() or (snd_inst and ch_inst.get_busy())) and IS_SINGING_ACTIVE:
            # 若歌聲部分已結束但伴奏在收尾，及時關閉口型波形避免嘴巴微動
            if not ch_vocal.get_busy() and stage.CURRENT_MOUTH_ENVELOPE:
                stage.clear_mouth()
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
        if _HOST:
            import services.vts_client as vc
            if vc.GLOBAL_VTS:
                async def _toggle_mic_off():
                    try:
                        await asyncio.wait_for(vc.GLOBAL_VTS.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ToggleMic",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": "话筒.exp3.json", "active": False}
                        }), timeout=0.5)
                    except Exception: pass
                spawn(_toggle_mic_off())
        stage.stop_playback()
        _core_set_ai_state("IDLE", f"演唱結束《{song_name}》", only_from="SINGING")

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
