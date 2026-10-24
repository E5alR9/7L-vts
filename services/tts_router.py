r"""
 TTS 路由器 (TTS Router)

 目的：
   把直播主迴圈的語音合成，從「寫死單一本機 GPT-SoVITS 路徑的單一引擎」
   改成可插拔的引擎鏈（本機 Kokoro 引擎已移除，目前由 xiaoyi / cosyvoice /
   cloud_gptsovits / edge / elevenlabs 組成，見 _ENGINES）。

 引擎優先序（可用環境變數覆寫）：

   TTS_FALLBACK=xiaoyi        原 GPT-SoVITS 曉伊（需本機存在 GPT-SoVITS 安裝）

 語言自動判定：假名/漢字/半形片假名啟發式（detect_language 只分 zh/ja 大方向）；
    多語言 SoVITS（本地曉伊／雲端）一律傳 raw 假名＋text_language auto，由模型
    自己分段唸——只有純中文聲線（edge HsiaoChen）才在合成前把假名音譯成中文
    （transliterate_kana_to_zh，例：バカ → 巴卡）。

 介面：
   await get_tts_audio_bytes(text)  ->  WAV/MP3 bytes（與原 get_xiaoyi_audio_bytes 相容）
   get_active_engine()              ->  目前生效的引擎名稱（供儀表板/日誌）
PROVIDER: LOCAL-cosyvoice/xiaoyi＋CLOUD-edge/elevenlabs/cloud_gptsovits（見 docs/AI_SOURCES.md）
"""

import asyncio
import os
import re
import io
import time
from typing import Optional

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
TTS_SPEED = float(os.getenv("TTS_SPEED") or "1.0")

_active_engine: Optional[str] = None
_engine_errors: dict = {}
_rescue_probe: dict = {"at": 0.0}      # 鏈首試探時間戳：讓降級後的引擎能自動升級回來


def _log(msg: str) -> None:
    """安全輸出：Windows cp950 主控台印不出 emoji 時自動降級，绝不讓 log 打斷合成流程"""
    try:
        # 走 log_print：它會先清掉狀態列；直接 print 會黏在狀態列後面，錯誤訊息等於看不到（2026-10-24）
        from core.utils import log_print
        log_print(msg)
        return
    except Exception:
        pass
    try:
        print(msg)
    except Exception:
        try:
            print(msg.encode("utf-8", "replace").decode("ascii", "replace"))
        except Exception:
            pass


RE_TAG = re.compile(r'\[[A-Z_]+(?::[^\]]*)?\]')

# ── 片假名→中文音譯表（中文聲線唸日文梗用；例：バカ→巴卡）─────────────────
# 只處理假名 run，其餘文字原樣保留。長音ー、小促音ッ直接丟掉（中文無此音），
# 中黑點・轉頓號保留斷句，拗音（キャ等）合併成單字。
_KANA_SMALL_VOWEL = {"ァ": "阿", "ィ": "伊", "ゥ": "烏", "ェ": "埃", "ォ": "奧",
                     "ャ": "亞", "ュ": "優", "ョ": "約"}
_KANA_BASE = {
    "ア": "阿", "イ": "伊", "ウ": "烏", "エ": "艾", "オ": "奧",
    "カ": "卡", "キ": "奇", "ク": "酷", "ケ": "克", "コ": "考",
    "サ": "薩", "シ": "西", "ス": "蘇", "セ": "塞", "ソ": "索",
    "タ": "塔", "チ": "奇", "ツ": "茨", "テ": "特", "ト": "托",
    "ナ": "娜", "ニ": "尼", "ヌ": "努", "ネ": "內", "ノ": "諾",
    "ハ": "哈", "ヒ": "希", "フ": "弗", "ヘ": "嘿", "ホ": "霍",
    "マ": "馬", "ミ": "米", "ム": "姆", "メ": "梅", "モ": "莫",
    "ヤ": "雅", "ユ": "優", "ヨ": "約",
    "ラ": "拉", "リ": "利", "ル": "魯", "レ": "雷", "ロ": "羅",
    "ワ": "瓦", "ヲ": "沃", "ン": "恩",
    "ガ": "嘎", "ギ": "基", "グ": "咕", "ゲ": "格", "ゴ": "夠",
    "ザ": "扎", "ジ": "吉", "ズ": "茲", "ゼ": "澤", "ゾ": "佐",
    "ダ": "達", "ヂ": "吉", "ヅ": "茲", "デ": "得", "ド": "都",
    "バ": "巴", "ビ": "比", "ブ": "布", "ベ": "貝", "ボ": "波",
    "パ": "帕", "ピ": "皮", "プ": "普", "ペ": "佩", "ポ": "破",
    "ヴ": "武",
}
_KANA_COMBO = {
    "キャ": "卡", "キュ": "丘", "キョ": "喬",
    "シャ": "沙", "シュ": "舒", "ショ": "肖", "シェ": "謝",
    "チャ": "茶", "チュ": "丘", "チェ": "切", "チョ": "喬",
    "ジャ": "爵", "ジュ": "朱", "ジョ": "佐", "ジェ": "傑",
    "ギャ": "加",
    "ファ": "法", "フィ": "菲", "フェ": "費", "フォ": "佛",
    "ヴァ": "瓦", "ヴィ": "維", "ヴェ": "韋", "ヴォ": "沃",
    "ウィ": "維", "ウェ": "韋", "ウォ": "沃", "イェ": "耶",
    "ティ": "蒂", "ディ": "迪", "トゥ": "圖", "ドゥ": "杜",
    "ツァ": "擦", "クァ": "夸", "グァ": "瓜",
}
_KANA_DROP = set("ッー・")
_HALF_PUNCT = {"｡": "。", "､": "、", "｢": "「", "｣": "」", "･": "・"}
_HALF_KANA = {
    "ｱ": "ア", "ｲ": "イ", "ｳ": "ウ", "ｴ": "エ", "ｵ": "オ",
    "ｶ": "カ", "ｷ": "キ", "ｸ": "ク", "ｹ": "ケ", "ｺ": "コ",
    "ｻ": "サ", "ｼ": "シ", "ｽ": "ス", "ｾ": "セ", "ｿ": "ソ",
    "ﾀ": "タ", "ﾁ": "チ", "ﾂ": "ツ", "ﾃ": "テ", "ﾄ": "ト",
    "ﾅ": "ナ", "ﾆ": "ニ", "ﾇ": "ヌ", "ﾈ": "ネ", "ﾉ": "ノ",
    "ﾊ": "ハ", "ﾋ": "ヒ", "ﾌ": "フ", "ﾍ": "ヘ", "ﾎ": "ホ",
    "ﾏ": "マ", "ﾐ": "ミ", "ﾑ": "ム", "ﾒ": "メ", "ﾓ": "モ",
    "ﾔ": "ヤ", "ﾕ": "ユ", "ﾖ": "ヨ",
    "ﾗ": "ラ", "ﾘ": "リ", "ﾙ": "ル", "ﾚ": "レ", "ﾛ": "ロ",
    "ﾜ": "ワ", "ｦ": "ヲ", "ﾝ": "ン",
    "ｧ": "ァ", "ｨ": "ィ", "ｩ": "ゥ", "ｪ": "ェ", "ｫ": "ォ",
    "ｬ": "ャ", "ｭ": "ュ", "ｮ": "ョ", "ｯ": "ッ", "ｰ": "ー",
}
_HALF_VOICED = {  # 半形浊点/半浊点组合（X + ﾞ/ﾟ）
    "ｶﾞ": "ガ", "ｷﾞ": "ギ", "ｸﾞ": "グ", "ｹﾞ": "ゲ", "ｺﾞ": "ゴ",
    "ｻﾞ": "ザ", "ｼﾞ": "ジ", "ｽﾞ": "ズ", "ｾﾞ": "ゼ", "ｿﾞ": "ゾ",
    "ﾀﾞ": "ダ", "ﾁﾞ": "ヂ", "ﾂﾞ": "ヅ", "ﾃﾞ": "デ", "ﾄﾞ": "ド",
    "ﾊﾞ": "バ", "ﾋﾞ": "ビ", "ﾌﾞ": "ブ", "ﾍﾞ": "ベ", "ﾎﾞ": "ボ",
    "ﾊﾟ": "パ", "ﾋﾟ": "ピ", "ﾌﾟ": "プ", "ﾍﾟ": "ペ", "ﾎﾟ": "ポ",
    "ｳﾞ": "ヴ",
}


def _fold_to_full_kata(text: str) -> str:
    """平假名→片假名、半形→全形，統一成全形片假名再查表。"""
    out = []
    for ch in text:
        o = ord(ch)
        if 0x3041 <= o <= 0x3096:      # 平假名ぁ-ヶ → ァ-ヶ
            out.append(chr(o + 0x60))
        elif ch in _HALF_PUNCT:
            out.append(_HALF_PUNCT[ch])
        elif ch in _HALF_KANA:
            out.append(_HALF_KANA[ch])
        else:
            out.append(ch)
    return "".join(out)


def transliterate_kana_to_zh(text: str) -> str:
    """把文字中的假名 run 音譯成中文（中文聲線用；非假名原樣保留）。

    例：ロンリーユニバース → 羅恩利優尼巴斯；バカ → 巴卡。
    日文路徑不要呼叫（Nanami 直接唸假名）。
    """
    if not text or not re.search(r'[\u3040-\u309F\u30A0-\u30FF\uFF61-\uFF9F]', text):
        return text
    # 半形浊点组合先合併（ﾊﾞ → バ），再整串 fold 成全形片假名（一對一，不改長度）
    for half, full in _HALF_VOICED.items():
        if half in text:
            text = text.replace(half, full)
    folded = _fold_to_full_kata(text)
    out = []
    i, n = 0, len(folded)
    while i < n:
        ch = folded[i]
        two = folded[i:i + 2]
        if two in _KANA_COMBO:
            out.append(_KANA_COMBO[two])
            i += 2
        elif ch in _KANA_BASE:
            out.append(_KANA_BASE[ch])
            i += 1
        elif ch in _KANA_SMALL_VOWEL:
            out.append(_KANA_SMALL_VOWEL[ch])
            i += 1
        elif ch == "・":
            out.append("、")
            i += 1
        elif ch in _KANA_DROP:
            i += 1  # 促音ッ／長音ー／中黑點直接丟掉（中文無此音）
        else:
            out.append(ch)  # 漢字／拉丁／數字／標點原樣保留
            i += 1
    return "".join(out)


def detect_language(text: str) -> str:
    """回傳 'ja' 或 'zh'（假名/漢字啟發式，中文語境優先）。

    2026-10-09 修正：
    - 半形片假名（U+FF61–FF9F，YT 歌名常見）也計入假名——之前完全漏掉。
    - 中日混合句仍判 zh（整句是中文），但中文路徑會先把假名音譯
      （transliterate_kana_to_zh），所以聲線不會唸爛片假名。
    - 全漢字日文（無假名）啟發式無解，維持 zh；純英文維持 zh（引擎鏈無 EN
      聲線可接，接了也沒地方去——kokoro 引擎與 EN_VOICE 已同步清掉）。
    """
    num_kana = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\uFF61-\uFF9F]', text))
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
    # lang 參數保留（標示呼叫時的判定語境），目前不分支：假名一律原樣保留，
    # 交給各引擎自己處理——多語言 SoVITS 用 auto 原生唸假名，edge 中文聲線
    # 在 _synth_edge 內另行音譯（見 transliterate_kana_to_zh）。
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


def sovits_text_lang(text: str) -> str:
    """GPT-SoVITS text_language：純日→ja，純中→zh，其餘混合→auto（模型自己分段）。

    跟本地曉伊同一哲學（見 local_xiaoyi_service.synthesize_xiaoyi_bytes）：
    模型是多語言的，不要硬鎖單一語系逼它唸錯另一種文字。
    """
    num_kana = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\uFF61-\uFF9F]', text))
    num_hanzi = len(re.findall(r'[\u4E00-\u9FFF]', text))
    has_latin = bool(re.search(r'[A-Za-z]', text))
    if num_kana > 0 and num_hanzi == 0 and not has_latin:
        return "ja"
    if num_kana == 0 and not has_latin:
        return "zh"
    return "auto"


async def _synth_edge(text: str) -> bytes:
    """微軟 Edge-TTS 雲端合成（台灣腔女聲 / 日文聲線），回傳 MP3 bytes"""
    import edge_tts
    lang = detect_language(text)
    if lang == "zh" and re.search(r'[\u3040-\u309F\u30A0-\u30FF\uFF61-\uFF9F]', text):
        # HsiaoChen 是純中文聲線、假名會唸爛：先音譯成中文再唸。
        # （多語言 SoVITS 不走這條，不受影響）
        text = transliterate_kana_to_zh(text)
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
#   1) 預設不啟用，要用請設 TTS_ENGINE=elevenlabs（建議 TTS_FALLBACK=edge,xiaoyi）
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
# 啟動約 25~60 秒；單句合成 RTF 約 1.4。
# 服務沒開或逾時 → 拋錯讓引擎鏈降級 edge/xiaoyi（不中斷直播）。
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
        
    # GPT-SoVITS 的語系：純日→ja、純中→zh，混合一律 auto（模型自己分段唸）。
    # 絕不能對混合句硬鎖 zh/ja，否則另一種文字會被唸爛。
    req_lang = sovits_text_lang(text)
    
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

# 單引擎無回應上限（GPU 推理 hang 不會拋錯，超時直接換下一個）
ENGINE_TIMEOUT_SEC = 90.0


def get_active_engine() -> Optional[str]:
    return _active_engine


def get_engine_errors() -> dict:
    return dict(_engine_errors)


def file_extension(engine: str) -> str:
    """回傳該引擎產出的副檔名（供播放端正確命名暫存檔）"""
    return ".mp3" if engine in ("edge", "elevenlabs") else ".wav"


def _ffmpeg_exe() -> str:
    import shutil
    return (os.getenv("FFMPEG_EXE")
            or shutil.which("ffmpeg")
            or r"C:\ffmpeg\bin\ffmpeg.exe")


# 連續靜音超過幾秒判缺段（自娛自樂事故：18 秒音訊裡 14 秒數位靜音，時長反而超標）。
# TTS 都是短句，正常標點停頓 <0.5s；2.0s 以上的洞一定是合成端掉片。
MAX_SILENCE_SEC = 2.0
QUALITY_RETRIES = int(os.getenv("TTS_QUALITY_RETRIES", "2"))   # 品質不合格時同引擎重抽次數


def _quality_problem(text: str, data) -> str:
    """合成結果的品質檢查；合格回 ""。空音訊不算品質問題（交給呼叫端的「回傳音訊為空」）。"""
    if not data or len(data) <= 100:
        return ""
    dur, gap, voiced = _audio_profile_full(data)
    if dur is None:
        return ""
    n = len(text.strip())
    expect = max(1.5, n * 0.22)
    # 念一兩個字就停住、後面全是靜音直到長度上限（實測總長 20~57 秒、真的有聲只有 0.5~2 秒）。
    # 靜音在尾巴不在中段，舊檢查放行：7L 對著空氣講 20 幾秒，後面排隊的話全卡住（2026-10-25）
    if dur > max(8.0, expect * 2.5):
        return f"音訊過長疑似沒念完（{dur:.1f}s/預期{expect:.1f}s）"
    if n >= 10:
        if dur < expect * 0.4:
            return f"音訊過短疑似缺段（{dur:.1f}s/預期{expect:.1f}s）"
        if voiced is not None and voiced < expect * 0.3:
            return f"有聲只有{voiced:.1f}s疑似沒念完（預期{expect:.1f}s）"
        if gap is not None and gap > MAX_SILENCE_SEC:
            return f"音訊中段靜音{gap:.1f}s疑似掉片（自娛自樂式缺段）"
    return ""


def _audio_profile(data: bytes):
    """回 (秒數|None, 最大靜音洞|None)；細節見 _audio_profile_full。"""
    seconds, longest, _voiced = _audio_profile_full(data)
    return seconds, longest


def _audio_profile_full(data: bytes):
    """內容嗅探而非副檔名（2026-10-11 教訓：xiaoyi 掛 .wav 標回的卻是 MP3，
    舊守衛 wave.open 直接炸＝失明）。回 (秒數|None, 最大靜音洞|None, 有聲秒數|None)。
    wav 走標準庫；其他格式走 ffmpeg 解碼；都沒有就 (None, None, None) 跳過檢查。"""
    if not data or len(data) <= 100:
        return None, None, None
    pcm = None
    rate = 0
    try:
        import wave as _wv
        with _wv.open(io.BytesIO(data), "rb") as w:
            n, ch, rate = w.getnframes(), w.getnchannels(), w.getframerate()
            raw = w.readframes(n)
        import array as _ar
        a = _ar.array("h", raw)
        if ch == 2:
            a = a[0::2]
        pcm = a
    except Exception:
        pcm = None
    if pcm is None:
        try:
            import subprocess as _sp
            exe = _ffmpeg_exe()
            if not exe or not os.path.exists(exe):
                return None, None, None
            rate = 16000
            r = _sp.run([exe, "-v", "error", "-i", "pipe:0",
                         "-f", "s16le", "-ac", "1", "-ar", str(rate), "pipe:1"],
                        input=bytes(data), capture_output=True, timeout=30)
            if r.returncode != 0 or len(r.stdout) < rate * 2:
                return None, None, None
            import array as _ar
            a = _ar.array("h", r.stdout)
            if len(a) % 2:
                a = a[:-1]
            pcm = a
        except Exception:
            return None, None, None
    try:
        seconds = len(pcm) / float(rate or 1)
        win = max(1, int(rate * 0.25))
        prof = []
        for i in range(0, len(pcm), win):
            seg = pcm[i:i + win]
            prof.append((sum(s * s for s in seg) / len(seg)) ** 0.5 if seg else 0.0)
        if not prof:
            return seconds, None, None
        peak = max(prof)
        floor = max(80.0, peak * 0.02)
        longest = cur = voiced = 0.0
        step = win / float(rate or 1)
        for v in prof:
            if v < floor:
                cur += step
                longest = max(longest, cur)
            else:
                cur = 0.0
                voiced += step
        return seconds, longest, voiced
    except Exception:
        return None, None, None


# ── 語句磁碟快取（2026-10-11：同樣的口頭禪別再花 3 秒合成一次）───────────────
# 同文＋同引擎＋同語速命中約 50ms（測過：3.01s → 0.05s）。SoVITS 有採樣隨機性，
# 快取等於把同一句的講法固定下來——對主播人設是加分（口頭禪每次同一個味道）。
# 換聲線模型時 bump TTS_CACHE_VERSION，否則舊音色殘留。
TTS_CACHE_VERSION = "v4"  # v1 混入過中段靜音毒檔＋錯標格式，2026-10-11 全面換血；
# v3（2026-10-25）：參考音換成停頓壓短版，舊檔裡也有「念一兩字就停」的尾巴靜音檔漏網；v4：top_p 0.8→1.0（失敗的根本原因），語氣跟著變
TTS_CACHE_DIR = os.getenv("TTS_CACHE_DIR") or os.path.join(BASE_DIR, "data", "tts_cache")
TTS_CACHE_MAX_FILES = int(os.getenv("TTS_CACHE_MAX_FILES") or "500")
TTS_CACHE_MAX_BYTES = int(os.getenv("TTS_CACHE_MAX_BYTES") or str(300 * 1024 * 1024))
TTS_CACHE_DISABLE = os.getenv("TTS_CACHE_DISABLE") == "1"


def _tts_cache_key(text: str, engine: str) -> str:
    import hashlib
    raw = f"{TTS_CACHE_VERSION}|{engine}|{TTS_SPEED}|{text.strip()}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest() + file_extension(engine)


def _tts_cache_path(key: str) -> str:
    return os.path.join(TTS_CACHE_DIR, key)


def tts_cache_get(text: str, engine: str):
    """命中回 bytes（附帶刷新 mtime 做 LRU）；未命中／停用回 None。純函數之外只碰快取目錄。"""
    if TTS_CACHE_DISABLE:
        return None
    try:
        p = _tts_cache_path(_tts_cache_key(text, engine))
        if not os.path.exists(p) or os.path.getsize(p) <= 100:
            return None
        with open(p, "rb") as f:
            data = f.read()
        if len(data) <= 100:
            return None
        try:
            os.utime(p, None)
        except Exception:
            pass
        return data
    except Exception:
        return None


def tts_cache_put(text: str, engine: str, data: bytes) -> None:
    """只存通過時長守衛的完整音訊；寫完順手剪枝。失敗一律吞掉（快取絕不擋合成）。"""
    if TTS_CACHE_DISABLE or not data or len(data) <= 100:
        return
    try:
        os.makedirs(TTS_CACHE_DIR, exist_ok=True)
        with open(_tts_cache_path(_tts_cache_key(text, engine)), "wb") as f:
            f.write(data)
        _tts_cache_prune()
    except Exception:
        pass


def _tts_cache_prune() -> None:
    try:
        files = []
        total = 0
        for name in os.listdir(TTS_CACHE_DIR):
            p = os.path.join(TTS_CACHE_DIR, name)
            try:
                st = os.stat(p)
            except Exception:
                continue
            if not os.path.isfile(p):
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
        files.sort()
        while (len(files) > TTS_CACHE_MAX_FILES or total > TTS_CACHE_MAX_BYTES) and files:
            _, sz, p = files.pop(0)
            try:
                os.remove(p)
            except Exception:
                pass
            total -= sz
    except Exception:
        pass


async def get_tts_audio_bytes(text: str) -> bytes:
    """
    依引擎鏈合成語音。全部失敗回傳 b""（呼叫端會記錄警告，不會中斷直播）。
    單引擎 90 秒無回應視為卡死（GPU 推理 hang 不會拋錯），超時直接換下一個，
    絕不讓一顆引擎拖住整條語音管線（2026-10-11：xiaoyi 卡死導致全場靜默）。
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
            hit = tts_cache_get(text, engine)
            if hit:
                if _active_engine != engine:
                    _log(f"[TTS Router] 切換引擎 -> {engine}")
                    _active_engine = engine
                _engine_errors.pop(engine, None)
                return hit
            # 品質不合格（缺段／中段長靜音）時同引擎重試一次：GPT-SoVITS 取樣有隨機性，重抽通常就好。
            # 舊碼直接換下一個引擎，但預設鏈只有 xiaoyi 一個，結果整句靜音（2026-10-24 實機：26.8s 靜音被擋、7L 沒出聲）
            # 實測（「老爸。30秒到囉。快快，記得喝水喔…」）單次失敗率可到 1/3～5/8，所以最多抽 3 次
            for _attempt in range(QUALITY_RETRIES + 1):
                data = await asyncio.wait_for(fn(text), timeout=ENGINE_TIMEOUT_SEC)
                quality_err = _quality_problem(text, data)
                if not quality_err:
                    break
                if _attempt < QUALITY_RETRIES:
                    _log(f"[TTS Router] {engine} 品質不合格（{quality_err}），同引擎重抽（第 {_attempt + 1} 次）")
            if quality_err:
                raise RuntimeError(f"{quality_err}，換引擎")
            if data and len(data) > 100:
                if _active_engine != engine:
                    _log(f"[TTS Router] 切換引擎 -> {engine}")
                    _active_engine = engine
                _engine_errors.pop(engine, None)
                tts_cache_put(text, engine, data)
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
