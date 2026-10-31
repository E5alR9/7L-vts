"""她說話的語氣：每一段的語速、音高、音量（老爸 2026-10-31：能邊說邊調語速、音高，也要能調大小聲）。

不用她每句多寫標籤（2026-10-26 拿掉舊的 [SPEED]／[PITCH] 就是因為每句多寫 2～4 個、TTS 又沒照做）：
- 照她本來就會寫的表情標籤自動調（生氣快、低、大聲；害羞慢、高、小聲……），表情一直延續到下一個表情；
- 每段句尾的標點微調（！大聲一點、～慢一點、…小聲一點、？高一點）；
- 想講悄悄話、大喊這種特別的，她在那句前面寫短標籤 [小聲] [大聲] [悄悄話] [快] [慢] [高] [低]，
  只管到下一個標籤（表情或語氣）為止。標籤會被台詞清洗拿掉，不會念出來。

speed 是語速倍率（乘在 TTS 原本的語速上），pitch 是升降幾個半音，gain_db 是大小聲。
"""
import re
from typing import Callable, Dict, List

NEUTRAL = {"speed": 1.0, "pitch": 0.0, "gain_db": 0.0}

# 表情 → (語速倍率, 半音, 分貝)。沒列的表情照原本的講
EMOTION_PROSODY: Dict[str, tuple] = {
    "愛心": (0.97, 1.0, 0.0),
    "比心": (1.0, 0.5, 0.0),
    "星星眼": (1.06, 1.5, 1.0),
    "臉紅": (0.93, 1.0, -2.0),
    "哭哭": (0.88, -1.0, -3.0),
    "吐舌": (1.05, 0.5, 0.0),
    "花花": (0.92, 1.0, -1.0),
    "問號": (1.0, 0.5, 0.0),
    "流汗": (1.05, 0.0, -1.0),
    "著急": (1.15, 0.5, 2.0),
    "暈": (0.9, -0.5, -1.0),
    "生氣": (1.1, -1.0, 3.0),
    "黑臉": (0.95, -1.0, 0.0),
    "黑化": (0.9, -1.5, -2.0),
    "驚訝": (1.1, 2.0, 2.0),
    "翻白眼": (0.95, -0.5, 0.0),
    "皺眉": (0.95, -0.5, 0.0),
    "眨眼": (1.0, 0.5, 0.0),
}
# 她常寫的別名（不在表情選單上，但意思一樣）
EMOTION_ALIASES = {"害羞": "臉紅", "開心": "星星眼", "難過": "哭哭", "哭": "哭哭", "委屈": "哭哭", "不爽": "生氣",
                   "慌張": "著急", "尷尬": "流汗", "疑惑": "問號", "嚇到": "驚訝", "陶醉": "花花", "撒嬌": "愛心"}

# 她自己寫的語氣標籤 → (語速倍率, 半音, 分貝)
TAG_PROSODY: Dict[str, tuple] = {
    "小聲": (1.0, 0.0, -7.0),
    "悄悄話": (0.92, 0.0, -10.0),
    "大聲": (1.0, 0.0, 4.0),
    "快": (1.15, 0.0, 0.0),
    "慢": (0.87, 0.0, 0.0),
    "高": (1.0, 2.0, 0.0),
    "低": (1.0, -2.0, 0.0),
}
TAG_RE = re.compile(r"\[(" + "|".join(sorted(TAG_PROSODY, key=len, reverse=True)) + r")\]")
_EXPR_RE = re.compile(r"\[\s*EXPRESSION\s*[:：]\s*([^\]]+?)\s*\]", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"\[[^\]]*\]")

SPEED_RANGE = (0.75, 1.3)
PITCH_RANGE = (-3.0, 3.0)
GAIN_RANGE = (-12.0, 6.0)


def _clamp(v, lo_hi):
    return max(lo_hi[0], min(lo_hi[1], v))


def _combine(*parts) -> dict:
    speed, pitch, gain = 1.0, 0.0, 0.0
    for p in parts:
        if p:
            speed *= p[0]
            pitch += p[1]
            gain += p[2]
    return {"speed": round(_clamp(speed, SPEED_RANGE), 3), "pitch": round(_clamp(pitch, PITCH_RANGE), 2),
            "gain_db": round(_clamp(gain, GAIN_RANGE), 1)}


def emotion_of(tag_value: str) -> tuple:
    name = (tag_value or "").strip()
    name = EMOTION_ALIASES.get(name, name)
    return EMOTION_PROSODY.get(name)


def punctuation_prosody(segment: str) -> tuple:
    """段尾標點的微調。"""
    t = (segment or "").rstrip()
    if not t:
        return None
    if t.endswith(("！", "!")):
        return (1.03, 0.0, 1.0)
    if t.endswith(("～", "~")):
        return (0.96, 0.3, 0.0)
    if t.endswith(("…", "...", "⋯")):
        return (0.95, 0.0, -1.5)
    if t.endswith(("？", "?")):
        return (1.0, 0.5, 0.0)
    return None


def pieces(raw_text: str) -> List[dict]:
    """她原本的話（含標籤）切成一塊一塊：每塊的文字、當下的表情語氣、她指定的語氣標籤。"""
    out = []
    emotion, explicit = None, None
    pos = 0
    text = raw_text or ""
    for m in _ANY_TAG_RE.finditer(text):
        if m.start() > pos:
            out.append({"text": text[pos:m.start()], "emotion": emotion, "explicit": explicit})
        tag = m.group(0)
        em = _EXPR_RE.fullmatch(tag)
        tm = TAG_RE.fullmatch(tag)
        if em:
            emotion = emotion_of(em.group(1))
            explicit = None      # 換表情：她指定的語氣只管到這裡
        elif tm:
            explicit = TAG_PROSODY[tm.group(1)]
        pos = m.end()
    if pos < len(text):
        out.append({"text": text[pos:], "emotion": emotion, "explicit": explicit})
    return out


def punctuation_at(speech: str, pos: int) -> tuple:
    """台詞（還保留！？～…的那份）在 pos 附近的句尾標點 → 微調。"""
    window = (speech or "")[max(0, pos - 3):pos + 2]
    for ch in reversed(window):
        if ch in "！!～~…⋯？?":
            return punctuation_prosody(ch)
    return None


def build_chunks(raw_text: str, clean_tts: Callable[[str], str], clean_speech: Callable[[str], str],
                 split: Callable[[str], List[str]]) -> List[tuple]:
    """她的話 → [(要念的一段, 這段的語氣)]。
    語氣一樣的連續幾塊併成一組、各組分開切段（語氣不同的地方一定斷開：以前「過來一下。[悄悄話] 我跟你說」
    併成同一段，整段都變悄悄話）。每段再照那組台詞裡對應位置的句尾標點微調
    （TTS 清洗會把！換成。，所以看清洗前的台詞）。"""
    groups = []
    for p in pieces(raw_text):
        key = (p["emotion"], p["explicit"])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(p["text"])
        else:
            groups.append((key, [p["text"]]))
    out = []
    for (emotion, explicit), texts in groups:
        g_text = "".join(texts)
        tts = clean_tts(g_text)
        if not (tts or "").strip():
            continue
        speech = clean_speech(g_text) or tts
        segs = [x for x in split(tts) if x and x.strip()]
        total = sum(len(x) for x in segs) or 1
        acc = 0
        for seg in segs:
            acc += len(seg)
            punct = punctuation_at(speech, round(acc / total * len(speech)))
            out.append((seg, _combine(emotion, explicit, punct)))
    return out


def is_neutral(p: dict) -> bool:
    return (not p or (abs(p.get("speed", 1.0) - 1.0) < 0.005 and abs(p.get("pitch", 0.0)) < 0.05
                      and abs(p.get("gain_db", 0.0)) < 0.1))


def describe(p: dict) -> str:
    """日誌用：「語速 1.10x、低 1 半音、大聲 3dB」。"""
    parts = []
    if abs(p.get("speed", 1.0) - 1.0) >= 0.005:
        parts.append(f"語速 {p['speed']:.2f}x")
    if abs(p.get("pitch", 0.0)) >= 0.05:
        parts.append(f"{'高' if p['pitch'] > 0 else '低'} {abs(p['pitch']):g} 半音")
    if abs(p.get("gain_db", 0.0)) >= 0.1:
        parts.append(f"{'大聲' if p['gain_db'] > 0 else '小聲'} {abs(p['gain_db']):g}dB")
    return "、".join(parts) or "原本的語氣"
