r"""
 TTS 路由器 (TTS Router)

 目的：
   把直播主迴圈的語音合成，從「寫死單一本機 GPT-SoVITS 路徑的單一引擎」
   改成可插拔的引擎鏈，預設走本地小模型 Kokoro-82M (ONNX，約 310MB)。

 引擎優先序（可用環境變數覆寫）：

   TTS_FALLBACK=xiaoyi        原 GPT-SoVITS 曉伊（需本機存在 GPT-SoVITS 安裝）

 語言自動判定：沿用原 local_xiaoyi_service 的假名/漢字啟發式，
   中文夾日文梗（バカ → 八嘎）會先做音譯，再交給對應聲線。

 介面：
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

# ── 設定 ─────────────────────────────────────────────────────────────────────
ENGINE_ORDER = [e.strip().lower() for e in (os.getenv("TTS_ENGINE") or "cloud_gptsovits").split(",") if e.strip()]
_FALLBACK = [e.strip().lower() for e in (os.getenv("TTS_FALLBACK") or "xiaoyi").split(",") if e.strip()]

# 依序嘗試的完整引擎鏈（去重、保序）
_seen = set()
ENGINE_CHAIN = []
for _e in ENGINE_ORDER + _FALLBACK:
    if _e not in _seen:
        _seen.add(_e)
        ENGINE_CHAIN.append(_e)
if not ENGINE_CHAIN:
    ENGINE_CHAIN = ["xiaoyi", "edge"]

ZH_VOICE = os.getenv("TTS_ZH_VOICE") or "zf_001"
JA_VOICE = os.getenv("TTS_JA_VOICE") or "edge"
EN_VOICE = os.getenv("TTS_EN_VOICE") or "af_sol"
TTS_SPEED = float(os.getenv("TTS_SPEED") or "1.0")

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


RE_TAG = re.compile(r'\[[A-Z_]+(?::[^\]]*)?\]')

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
    text = re.sub(r'[\(（][^\)）]*[\)）]', '', text)
    text = re.sub(r'[⌒☆★♪♡♥✧✦๑•̀ㅂ•́و✧~～]+', '！', text)
    text = text.replace("7L", "小七").replace("7l", "小七")
    text = re.sub(r'[，,]{2,}', '，', text)
    text = re.sub(r'[！!]{2,}', '！', text)
    text = re.sub(r'[？?]{2,}', '？', text)
    text = re.sub(r'[。]{2,}', '。', text)
    text = text.strip(' ，,')
    return text


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

async def _synth_cloud_gptsovits(text: str) -> bytes:
    """傳送到 Google Colab 的遠端 GPT-SoVITS API 伺服器 (api_v2)"""
    colab_url = (os.getenv("COLAB_SOVITS_URL") or "").rstrip("/")
    if not colab_url:
        raise RuntimeError("未設定 COLAB_SOVITS_URL 環境變數")
        
    lang = detect_language(text)
    text = _clean_text(text, lang)
    if not text:
        return b""
        
    # GPT-SoVITS 的語系代碼通常為 "zh", "ja", "en" 等
    req_lang = "zh" if lang != "ja" else "ja"
    
    # 這些是你原本給 GPT-SoVITS 的參考音訊與文字，需根據你的模型微調
    ref_audio = os.getenv("TTS_SOVITS_REF_AUDIO") or ""
    prompt_text = os.getenv("TTS_SOVITS_PROMPT_TEXT") or ""
    prompt_lang = os.getenv("TTS_SOVITS_PROMPT_LANG") or "zh"
    
    import httpx
    async with httpx.AsyncClient(timeout=45.0) as cli:
        # 呼叫官方 api_v2.py 的寫法
        payload = {
            "text": text,
            "text_language": req_lang,
            "ref_audio_path": ref_audio,
            "prompt_text": prompt_text,
            "prompt_language": prompt_lang,
            "cut_punc": "，。！？"
        }
        r = await cli.post(f"{colab_url}/tts", json=payload)
        if r.status_code != 200:
            detail = r.text[:180]
            raise RuntimeError(f"Colab GPT-SoVITS HTTP {r.status_code}: {detail}")
        data = r.content
        
    if not data:
        raise RuntimeError("Colab GPT-SoVITS 回傳空白音訊")
    return data




_ENGINES = {
    "edge": _synth_edge,
    "xiaoyi": _synth_xiaoyi,
    "elevenlabs": _synth_elevenlabs,
    "cosyvoice": _synth_cosyvoice,
    "cloud_gptsovits": _synth_cloud_gptsovits,
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
