r"""
🎙️ TTS 路由器 (TTS Router)

🎯 目的：
   把直播主迴圈的語音合成，從「寫死單一本機 GPT-SoVITS 路徑的單一引擎」
   改成可插拔的引擎鏈，預設走本地小模型 Kokoro-82M (ONNX，約 310MB)。

⚙️ 引擎優先序（可用環境變數覆寫）：
   TTS_ENGINE=kokoro          預設：本地離線、RTX 3060 Ti 或 CPU 都跑得動
        ↓ 失敗才降級
   TTS_FALLBACK=edge          微軟雲端（台灣腔 zh-TW 聲線），音質優良、零 GPU
        ↓
   TTS_FALLBACK=xiaoyi        原 GPT-SoVITS 曉伊（需本機存在 GPT-SoVITS 安裝）

🌍 語言自動判定：沿用原 local_xiaoyi_service 的假名/漢字啟發式，
   中文夾日文梗（バカ → 八嘎）會先做音譯，再交給對應聲線。

📦 介面：
   await get_tts_audio_bytes(text)  ->  WAV/MP3 bytes（與原 get_xiaoyi_audio_bytes 相容）
   get_active_engine()              ->  目前生效的引擎名稱（供儀表板/日誌）
PROVIDER: LOCAL-kokoro/cosyvoice/xiaoyi＋CLOUD-edge/elevenlabs（見 docs/AI_SOURCES.md）
"""

import os
import re
import io
import time
import asyncio
import threading
from typing import Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOKORO_DIR = os.path.join(BASE_DIR, "models", "kokoro")

# ── 設定 ─────────────────────────────────────────────────────────────────────
ENGINE_ORDER = [e.strip().lower() for e in (os.getenv("TTS_ENGINE") or "kokoro").split(",") if e.strip()]
_FALLBACK = [e.strip().lower() for e in (os.getenv("TTS_FALLBACK") or "edge,xiaoyi").split(",") if e.strip()]

# 依序嘗試的完整引擎鏈（去重、保序）
_seen = set()
ENGINE_CHAIN = []
for _e in ENGINE_ORDER + _FALLBACK:
    if _e not in _seen:
        _seen.add(_e)
        ENGINE_CHAIN.append(_e)
if not ENGINE_CHAIN:
    ENGINE_CHAIN = ["kokoro", "edge", "xiaoyi"]

ZH_VOICE = os.getenv("TTS_ZH_VOICE") or "zf_001"      # v1.1-zh 聲線檔為匿名 ID（zf_001~zf_099）
JA_VOICE = os.getenv("TTS_JA_VOICE") or "edge"         # 此 voices 檔無日文聲線 -> 走 edge-tts
EN_VOICE = os.getenv("TTS_EN_VOICE") or "af_sol"
TTS_SPEED = float(os.getenv("TTS_SPEED") or "1.0")
KOKORO_MODEL = os.getenv("TTS_KOKORO_MODEL") or "kokoro-v1.1-zh.onnx"
KOKORO_VOICES = os.getenv("TTS_KOKORO_VOICES") or "voices-v1.1-zh.bin"

_active_engine: Optional[str] = None
_engine_errors: dict = {}
_rescue_probe: dict = {"at": 0.0}      # 鏈首試探時間戳：讓降級後的引擎能自動升級回來


def _log(msg: str) -> None:
    """安全輸出：Windows cp950 主控台印不出 emoji 時自動降級，绝不讓 log 打斷合成流程"""
    try:
        print(msg)
    except Exception:
        try:
            print(msg.encode("utf-8", "replace").decode("ascii", "replace"))
        except Exception:
            pass

# ── Kokoro 懶載入（模型 310MB，只在第一次合成時載入）─────────────────────────
_kokoro = None
_kokoro_lock = threading.Lock()


def _resolve_kokoro_paths() -> Tuple[Optional[str], Optional[str]]:
    model = os.path.join(KOKORO_DIR, KOKORO_MODEL)
    voices = os.path.join(KOKORO_DIR, KOKORO_VOICES)
    # 目錄裡若只有另一版檔案就自動抓現有的
    if not os.path.exists(model):
        cands = sorted([f for f in os.listdir(KOKORO_DIR) if f.endswith(".onnx")]) if os.path.isdir(KOKORO_DIR) else []
        if cands:
            model = os.path.join(KOKORO_DIR, cands[0])
    if not os.path.exists(voices):
        cands = sorted([f for f in os.listdir(KOKORO_DIR) if f.endswith(".bin")]) if os.path.isdir(KOKORO_DIR) else []
        if cands:
            voices = os.path.join(KOKORO_DIR, cands[0])
    if os.path.exists(model) and os.path.exists(voices):
        return model, voices
    return None, None


def _get_kokoro():
    global _kokoro
    if _kokoro is not None:
        return _kokoro
    model, voices = _resolve_kokoro_paths()
    if not model:
        raise RuntimeError(f"Kokoro 模型檔缺失（{KOKORO_DIR}）")
    # Windows 下 phonemizer 需要 espeak-ng 資料；espeakng_loader 內建一份
    try:
        import espeakng_loader
        os.environ.setdefault("ESPEAK_DATA_PATH", espeakng_loader.get_data_path())
        os.environ.setdefault("ESPEAKNG_DLL_PATH", espeakng_loader.get_library_path())
    except Exception:
        pass
    from kokoro_onnx import Kokoro
    _kokoro = Kokoro(model, voices)
    return _kokoro


# ── 文字前處理（沿用原曉伊服務的防卡頓規則）──────────────────────────────────
_LOANWORDS = {
    'バカ': '八嘎', 'ばか': '八嘎',
    'かわいい': '卡哇伊', 'カワイイ': '卡哇伊',
    'すごい': '斯國一', 'スゴイ': '斯國一',
    'すげえ': '斯國一', 'スゲエ': '斯國一',
    'やばい': '呀拜', 'ヤバイ': '呀拜',
    'おはよ': '歐嗨喲', 'オハヨ': '歐嗨喲',
    'ありがと': '阿里嘎多', 'アリガト': '阿里嘎多',
}
RE_TAG = re.compile(r'\[[A-Z_]+(?::[^\]]*)?\]')

# ── 中文 G2P（kokoro-v1.1-zh 專用）─────────────────────────────────────────
# 背景：kokoro-v1.1-zh 的訓練 tokenization 是 misaki `version='1.1'` 前端產生的
#       「注音符號 + 數字聲調」（ㄋㄧ2ㄏㄠ3）。若改用 espeak 的 IPA（ni2χˈɑu2），
#       雖然字符都在模型詞彙裡（詞彙同時含 IPA 與注音），但音素分佈與訓練不符，
#       念出來聲調會跑掉、聽感像別的方言（實測聽起來像粵語）。
#       反過來用 misaki 預設版（IPA+箭頭 ↓↗↘→）也不行：那些箭頭符號不在詞彙內會被丟掉、
#       聲調全失。唯 version='1.1' 與 ONNX 嵌入詞彙完全吻合（含 ZH_MAP 那批漢字）。
_ZHG2P = None


def _get_zhg2p():
    """延遲載入 misaki v1.1 中文前端；失敗回 None（呼叫端降級 espeak，比整條引擎炸掉好）"""
    global _ZHG2P
    if _ZHG2P is None:
        try:
            from misaki import zh as _mzh
            en_callable = None
            try:
                from misaki import en as _men
                _en_g2p = _men.G2P()
                en_callable = lambda w: (_en_g2p(w)[0] or "")   # 中英混說時的英文段
            except Exception:
                en_callable = None
            _ZHG2P = _mzh.ZHG2P(version="1.1", en_callable=en_callable)
        except Exception as e:
            _log(f"[TTS Router] misaki v1.1 前端載入失敗，中文將降級 espeak cmn: {e}")
            _ZHG2P = False   # 記住失敗，不要每次重試
    return _ZHG2P or None


def detect_language(text: str) -> str:
    """回傳 'ja' 或 'zh'（沿用原假名/漢字啟發式，中文語境優先）"""
    num_kana = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', text))
    num_hanzi = len(re.findall(r'[\u4E00-\u9FFF]', text))
    has_chinese_markers = bool(re.search(r'[的了嗎吧呢這那是在說妳你我他們著啦喔呀嘛欸咦啥誰怎麼盧搞弄為什麼]', text))
    if num_kana > 0:
        if num_hanzi == 0:
            return "ja"
        if not has_chinese_markers and (num_kana / (num_kana + num_hanzi) >= 0.35):
            return "ja"
        if has_chinese_markers and (num_kana / (num_kana + num_hanzi) >= 0.65):
            return "ja"
    return "zh"


def _clean_text(text: str, lang: str) -> str:
    text = RE_TAG.sub('', text or "")
    text = re.sub(r'[\(（][^\)）]*[\)）]', '', text)          # 括號表情 (∠・ω<)
    text = re.sub(r'[⌒☆★♪♡♥✧✦๑•̀ㅂ•́و✧~～]+', '！', text)
    text = text.replace("7L", "小七").replace("7l", "小七")
    text = re.sub(r'[，,]{2,}', '，', text)
    text = re.sub(r'[！!]{2,}', '！', text)
    text = re.sub(r'[？?]{2,}', '？', text)      # TTS 對連續問號會唸得怪，收斂成一個
    text = re.sub(r'[。]{2,}', '。', text)
    # ⚠️ 只 strip 逗號：句尾的 ？！。 必須保留，TTS 靠它判語氣
    text = text.strip(' ，,')
    if lang != "ja":
        for k, v in _LOANWORDS.items():
            text = text.replace(k, v)
    return text


# ── 各引擎實作 ───────────────────────────────────────────────────────────────
def _synth_kokoro_sync(text: str) -> bytes:
    """阻塞式合成（Kokoro ONNX），回傳 WAV bytes"""
    k = _get_kokoro()
    lang = detect_language(text)
    text = _clean_text(text, lang)
    if not text:
        return b""

    if lang == "ja":
        # v1.1-zh 聲線檔不含日文聲線：直接拋錯，讓引擎鏈降級到 edge-tts 日文聲線
        if JA_VOICE == "edge" or not _voice_exists(k, JA_VOICE):
            raise RuntimeError("Kokoro voices 檔無日文聲線，日文交給 edge-tts")
        voice = JA_VOICE
    elif lang == "en":
        voice = EN_VOICE if _voice_exists(k, EN_VOICE) else _pick_voice(k, "af_")
    else:
        voice = ZH_VOICE if _voice_exists(k, ZH_VOICE) else _pick_voice(k, "zf_")
    if not voice:
        raise RuntimeError("voices 檔內沒有可用聲線")

    # 中文：走 misaki v1.1（注音+數字調），與 kokoro-v1.1-zh 訓練格式一致
    g2p = _get_zhg2p() if lang == "zh" else None
    if g2p is not None:
        try:
            phonemes, _ = g2p(text)
        except Exception as e:
            _log(f"[TTS Router] v1.1 G2P 失敗（{e}），降級 espeak cmn")
            phonemes = None
    else:
        phonemes = None

    if phonemes and phonemes.strip() and not phonemes.strip() == "?" * len(phonemes):
        samples, sr = k.create(phonemes, voice=voice, speed=TTS_SPEED, lang="cmn", is_phonemes=True)
    else:
        # espeak 語系代碼：中文是 cmn（普通話）不是 zh；僅在 misaki 不可用時兜底
        espeak_lang = {"zh": "cmn", "ja": "ja", "en": "en-us"}.get(lang, "cmn")
        samples, sr = k.create(text, voice=voice, speed=TTS_SPEED, lang=espeak_lang)
    import numpy as np
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, np.asarray(samples, dtype=np.float32), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _voice_exists(k, name: str) -> bool:
    try:
        voices = k.get_voices() if hasattr(k, "get_voices") else list(getattr(k, "voices", {}).keys())
        return bool(name) and name in set(voices)
    except Exception:
        return True   # 無法列舉時不設限，交給 create() 自己報錯


def _pick_voice(k, prefix: str) -> str:
    """挑第一個符合前綴的可用聲線（zf_ / zm_ / af_ …）"""
    try:
        voices = sorted(k.get_voices() if hasattr(k, "get_voices") else getattr(k, "voices", {}).keys())
        for v in voices:
            if v.startswith(prefix):
                return v
    except Exception:
        pass
    return ""


async def _synth_kokoro(text: str) -> bytes:
    # ONNX 推論是 CPU 密集，丟到執行緒避免卡住直播事件迴圈
    async with _AioLock(_kokoro_lock):
        return await asyncio.to_thread(_synth_kokoro_sync, text)


class _AioLock:
    """把 threading.Lock 包成 async context（to_thread 內仍需序列化同一模型）"""
    def __init__(self, lock: threading.Lock):
        self._lock = lock

    async def __aenter__(self):
        await asyncio.to_thread(self._lock.acquire)
        return self

    async def __aexit__(self, *exc):
        self._lock.release()
        return False


async def _synth_edge(text: str) -> bytes:
    """微軟 Edge-TTS 雲端合成（台灣腔女聲 / 日文聲線），回傳 MP3 bytes"""
    import edge_tts
    lang = detect_language(text)
    voice = "ja-JP-NanamiNeural" if lang == "ja" else "zh-TW-HsiaoChenNeural"
    text = _clean_text(text, lang)
    if not text:
        return b""
    comm = edge_tts.Communicate(text, voice=voice, rate="+0%")
    buf = io.BytesIO()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


async def _synth_xiaoyi(text: str) -> bytes:
    """原 GPT-SoVITS 曉伊（需本機有 GPT-SoVITS 安裝，否則拋錯讓鏈降級）"""
    svc_path = os.getenv("GPT_SOVITS_DIR") or os.path.join(os.path.expanduser("~"), "GPT-SoVITS")
    if not os.path.isdir(svc_path):
        raise RuntimeError(f"GPT-SoVITS 不存在: {svc_path}")
    import local_xiaoyi_service
    return await local_xiaoyi_service.get_xiaoyi_audio_bytes(text)


# ── ElevenLabs（雲端精品 TTS）───────────────────────────────────────────────
# 免費版每月 10,000 字元（≈10 分鐘語音），所以：
#   1) 預設不啟用，要用請設 TTS_ENGINE=elevenlabs（建議 TTS_FALLBACK=kokoro,edge,xiaoyi）
#   2) 內建額度守衛：每 10 分鐘查一次官方額度，用盡自動拋錯 → 引擎鏈降級回本地
#   3) 模型先走最快的 flash（TTFB ~0.37s），失敗自動改試 multilingual_v2（品質最穩）
ELEVEN_KEY = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
ELEVEN_VOICE = (os.getenv("ELEVEN_VOICE_ID") or "").strip() or "EXAVITQu4vr4xnSDxMaL"   # Sarah
ELEVEN_MODEL = (os.getenv("ELEVEN_MODEL") or "").strip() or "eleven_flash_v2_5"
ELEVEN_MODEL_QUALITY = (os.getenv("ELEVEN_MODEL_QUALITY") or "").strip() or "eleven_multilingual_v2"
ELEVEN_OUT_FMT = os.getenv("ELEVEN_OUTPUT_FORMAT") or "mp3_44100_128"
ELEVEN_LIMIT_FALLBACK = int(os.getenv("ELEVEN_MONTHLY_LIMIT") or "10000")

_quota = {"at": 0.0, "used": 0, "limit": ELEVEN_LIMIT_FALLBACK, "local": 0, "logged": False}


async def eleven_remaining() -> int:
    """剩餘可用字元（遠端額度快取 10 分鐘；查失敗就退回本地計數）"""
    now = time.time()
    if ELEVEN_KEY and now - _quota["at"] > 600:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.get("https://api.elevenlabs.io/v1/user/subscription",
                                  headers={"xi-api-key": ELEVEN_KEY})
            if r.status_code == 200:
                sub = r.json().get("subscription", r.json())
                _quota.update(at=now,
                              used=int(sub.get("character_count") or 0),
                              limit=int(sub.get("character_limit") or ELEVEN_LIMIT_FALLBACK))
            else:
                _quota["at"] = now - 540          # 60 秒後重試，不要每次合成都打
        except Exception:
            _quota["at"] = now - 540
    return max(0, _quota["limit"] - _quota["used"] - _quota["local"])


async def _eleven_call(cli, text: str, model: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}/stream"
    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
    }
    async with cli.stream("POST", url, headers={"xi-api-key": ELEVEN_KEY},
                          params={"output_format": ELEVEN_OUT_FMT}, json=payload) as resp:
        if resp.status_code != 200:
            body = (await resp.aread()).decode("utf-8", "replace")
            raise RuntimeError(f"ElevenLabs {model} HTTP {resp.status_code}: {body[:150]}")
        buf = io.BytesIO()
        async for chunk in resp.aiter_bytes():
            buf.write(chunk)
        data = buf.getvalue()
    if not data:
        raise RuntimeError(f"ElevenLabs {model} 回傳空白音訊")
    return data


async def _synth_elevenlabs(text: str) -> bytes:
    """ElevenLabs 串流合成（MP3 bytes）。額度不足拋錯讓引擎鏈降級到本地。"""
    if not ELEVEN_KEY:
        raise RuntimeError("未設定 ELEVENLABS_API_KEY")
    lang = detect_language(text)
    text = _clean_text(text, lang)
    if not text:
        return b""

    left = await eleven_remaining()
    if left <= 0:
        raise RuntimeError(f"ElevenLabs 月額度已用盡（{_quota['used']}/{_quota['limit']}），降級本地引擎")
    if not _quota["logged"]:
        _quota["logged"] = True
        _log(f"[TTS Router] ElevenLabs 啟用: voice={ELEVEN_VOICE} model={ELEVEN_MODEL} "
             f"剩餘額度 {left}/{_quota['limit']} 字元（每月重置）")

    import httpx
    async with httpx.AsyncClient(timeout=60.0) as cli:
        try:
            data = await _eleven_call(cli, text, ELEVEN_MODEL)
        except Exception as e:
            # 主模型不可用（免費版沒開／模型改名）→ 退到品質款再試一次
            if ELEVEN_MODEL_QUALITY and ELEVEN_MODEL != ELEVEN_MODEL_QUALITY:
                _log(f"[TTS Router] ElevenLabs {ELEVEN_MODEL} 失敗，改試 {ELEVEN_MODEL_QUALITY}: {e}")
                data = await _eleven_call(cli, text, ELEVEN_MODEL_QUALITY)
            else:
                raise

    _quota["local"] += len(text)
    return data


# ── CosyVoice3（本地精品 TTS，獨立 venv + localhost 服務）─────────────────────
# 模型 Fun-CosyVoice3-0.5B（9.3GB、中文韻律開源第一梯隊），跑在
#   venvs\cosyvoice\Scripts\python.exe services\cosyvoice_server.py --port 9881
# 啟動約 25~60 秒；單句合成 RTF 約 1.4（比 Kokoro 慢、比 Qwen3-TTS 快）。
# 服務沒開或逾時 → 拋錯讓引擎鏈降級 kokoro/edge（不中斷直播）。
COSYVOICE_URL = (os.getenv("COSYVOICE_URL") or "http://127.0.0.1:9881").rstrip("/")
COSYVOICE_TIMEOUT = float(os.getenv("COSYVOICE_TIMEOUT") or "60")


async def _synth_cosyvoice(text: str) -> bytes:
    lang = detect_language(text)
    text = _clean_text(text, lang)
    if not text:
        return b""
    import httpx
    async with httpx.AsyncClient(timeout=COSYVOICE_TIMEOUT) as cli:
        r = await cli.post(f"{COSYVOICE_URL}/tts", json={"text": text})
        if r.status_code != 200:
            detail = r.text[:180]
            raise RuntimeError(f"cosyvoice HTTP {r.status_code}: {detail}")
        data = r.content
    if not data:
        raise RuntimeError("cosyvoice 回傳空白音訊")
    return data


_ENGINES = {
    "kokoro": _synth_kokoro,
    "edge": _synth_edge,
    "xiaoyi": _synth_xiaoyi,
    "elevenlabs": _synth_elevenlabs,
    "cosyvoice": _synth_cosyvoice,
}


def get_active_engine() -> Optional[str]:
    return _active_engine


def get_engine_errors() -> dict:
    return dict(_engine_errors)


def file_extension(engine: str) -> str:
    """回傳該引擎產出的副檔名（供播放端正確命名暫存檔）"""
    return ".mp3" if engine in ("edge", "elevenlabs") else ".wav"


async def get_tts_audio_bytes(text: str) -> bytes:
    """
    依引擎鏈合成語音。全部失敗回傳 b""（呼叫端會記錄警告，不會中斷直播）。
    """
    global _active_engine
    if not text or not text.strip():
        return b""

    # 第一次成功後固定走該引擎（避免每次合成都重試失敗引擎）
    chain = ([_active_engine] if _active_engine in _ENGINES else []) + \
            [e for e in ENGINE_CHAIN if e != _active_engine]

    # 自動升級：當前引擎不是鏈首時（例：啟動時 cosyvoice 服務還沒載入完、先落在
    # kokoro），每 120 秒把鏈首提到最前試探一次；服務就緒後下次合成會切回去。
    top = ENGINE_CHAIN[0] if ENGINE_CHAIN else None
    if top and top != _active_engine and top in _ENGINES:
        if time.time() - _rescue_probe["at"] >= 120.0:
            _rescue_probe["at"] = time.time()
            chain = [top] + [e for e in chain if e != top]

    for engine in chain:
        fn = _ENGINES.get(engine)
        if fn is None:
            continue
        try:
            t0 = time.time()
            data = await fn(text)
            if data and len(data) > 100:
                if _active_engine != engine:
                    _log(f"[TTS Router] 切換引擎 -> {engine}")
                    _active_engine = engine
                _engine_errors.pop(engine, None)
                return data
            raise RuntimeError("回傳音訊為空")
        except Exception as e:
            prev = _engine_errors.get(engine)
            _engine_errors[engine] = str(e)[:200]
            if _active_engine == engine:
                _active_engine = None  # 生效中的引擎壞了，重新走整條鏈
            if prev != _engine_errors[engine]:      # 同樣錯誤不重複刷屏（避免每句都 log）
                _log(f"[TTS Router] {engine} 失敗，降級下一個: {str(e)[:120]}")
            continue
    return b""


# 向後相容：舊程式碼呼叫 get_xiaoyi_audio_bytes 也能運作
async def get_xiaoyi_audio_bytes(text: str) -> bytes:
    return await get_tts_audio_bytes(text)
