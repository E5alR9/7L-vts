# -*- coding: utf-8 -*-
"""
⚙️ 控制台可編輯的 .env 設定（白名單 + 安全讀寫）

設計原則：
1. 白名單 SETTINGS_SPECS 是唯一真相來源：前端表單、驗證、是否需重啟全依它。
2. 機密金鑰（secret=True）**只寫不讀**：GET 永遠不回傳值，只回「是否已設/長度/前綴」。
3. 寫檔採「區塊替換」而非整檔重寫：.env 裡 GROQ_API_KEYS 是多行大值，
   動錯一行就會讓 dotenv 解析中斷（本專案踩過一次雷，tests 有守）。
4. restart=False 的設定寫檔同時熱套用到 os.environ（OPERATOR_INPUT 這類是惰性讀取 → 立即生效）。
"""
import os
import re
import tempfile
from typing import Any, Dict, List, Tuple

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

# type: str / int / float / bool / choice    restart: 是否要重啟 V7 才生效
SETTINGS_SPECS: List[Dict[str, Any]] = [
    # ── 語音 ──
    {"key": "TTS_ENGINE", "label": "TTS 主引擎（優先序，逗號分隔）", "type": "str", "restart": True},
    {"key": "TTS_FALLBACK", "label": "TTS 備援引擎（逗號分隔）", "type": "str", "restart": True},
    {"key": "TTS_ZH_VOICE", "label": "Kokoro 中文聲線", "type": "str", "restart": True},
    {"key": "TTS_SPEED", "label": "語速倍率", "type": "float", "restart": True, "default": "1.0"},
    {"key": "COSYVOICE_URL", "label": "CosyVoice 服務位址", "type": "str", "restart": True,
     "default": "http://127.0.0.1:9881"},
    {"key": "ELEVEN_VOICE_ID", "label": "ElevenLabs 聲線 ID", "type": "str", "restart": True},
    # ── 直播輸入（觀眾留言來源）──
    {"key": "TWITCH_CHANNELS", "label": "Twitch 頻道（逗號分隔）", "type": "str", "restart": True, "optional": True},
    {"key": "YOUTUBE_CHANNEL", "label": "YouTube 頻道（@handle/網址/UC id，自動跟進目前直播）",
     "type": "str", "restart": True, "optional": True},
    {"key": "YOUTUBE_LIVE_ID", "label": "YouTube 直播 ID / 網址（頻道模式下可留空）",
     "type": "str", "restart": True, "optional": True},
    # ── 行為開關（restart=False → 寫檔同時熱套用）──
    {"key": "OPERATOR_INPUT", "label": "操作者輸入通道（麥/鍵/後台打字）", "type": "bool",
     "restart": False, "default": "0"},
    {"key": "OPERATOR_SPEECH", "label": "對操作者也發聲", "type": "bool", "restart": False, "default": "0"},
    {"key": "GROQ_REQUESTS_PER_MINUTE", "label": "Groq 每分鐘上限（0=不限）", "type": "int",
     "restart": False, "default": "20"},
    # ── LLM / 網路 ──
    {"key": "GROQ_TEXT_MODELS", "label": "Groq 模型梯隊（空=預設）", "type": "str", "restart": True, "optional": True},
    {"key": "WEB_BIND_HOST", "label": "控制台綁定位址", "type": "choice",
     "choices": ["127.0.0.1", "0.0.0.0"], "restart": True, "default": "127.0.0.1"},
    # ── 機密（只寫不讀）──
    {"key": "GROQ_API_KEYS", "label": "Groq 金鑰（逗號分隔）", "type": "str", "restart": True, "secret": True},
    {"key": "GEMINI_API_KEY", "label": "Gemini 金鑰", "type": "str", "restart": True, "secret": True},
    {"key": "ELEVENLABS_API_KEY", "label": "ElevenLabs 金鑰", "type": "str", "restart": True, "secret": True},
    {"key": "DISCORD_TOKEN_7L", "label": "Discord Token", "type": "str", "restart": True, "secret": True},
    {"key": "SIGN_API_KEY", "label": "TikTok 簽章金鑰", "type": "str", "restart": True, "secret": True},
    {"key": "TAVILY_KEYS", "label": "Tavily 搜尋金鑰", "type": "str", "restart": True, "secret": True},
    {"key": "MONGO_URI", "label": "MongoDB 連線字串", "type": "str", "restart": True, "secret": True},
]

SPEC_BY_KEY = {s["key"]: s for s in SETTINGS_SPECS}


def _split_entries(lines: List[str]) -> List[Tuple[str, int, int]]:
    """把 .env 拆成 (key, start, end) 區塊；值可跨多行（吃到下一個 KEY= / 空行 / 註解為止）"""
    entries = []
    i, n = 0, len(lines)
    while i < n:
        m = _KEY_RE.match(lines[i])
        if m:
            key, start = m.group(1), i
            i += 1
            while i < n and not _KEY_RE.match(lines[i]) and lines[i].strip() \
                    and not lines[i].lstrip().startswith("#"):
                i += 1
            entries.append((key, start, i))
        else:
            i += 1
    return entries


def read_env_file(path: str = None) -> Dict[str, str]:
    """解析 .env（含多行值）→ dict。找不到檔案回 {}"""
    path = path or ENV_PATH
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    out: Dict[str, str] = {}
    for key, s, e in _split_entries(lines):
        first = lines[s]
        val = first.split("=", 1)[1] if "=" in first else ""
        extra = [l for l in lines[s + 1:e]]
        if extra:
            val = val + "\n" + "\n".join(extra)
        out[key] = val.strip().strip('"').strip("'")
    return out


def read_settings(path: str = None) -> List[Dict[str, Any]]:
    """給前端的表單資料。機密只回 secret_info，絕不回 value。"""
    cur = read_env_file(path)
    specs = []
    for s in SETTINGS_SPECS:
        raw = cur.get(s["key"], s.get("default", ""))
        item = {k: s[k] for k in ("key", "label", "type", "restart") if k in s}
        if "choices" in s:
            item["choices"] = s["choices"]
        if s.get("secret"):
            item["secret"] = True
            item["value"] = ""
            item["secret_info"] = {
                "set": bool(raw),
                "len": len(raw),
                "prefix": (raw[:4] + "…") if raw else "",
            }
        else:
            item["secret"] = False
            item["value"] = raw
        specs.append(item)
    return specs


def _validate(spec: Dict[str, Any], raw: str) -> Tuple[str, str]:
    """回傳 (normalized_value, error)；error 非空表示拒絕"""
    t = spec["type"]
    raw = (raw if raw is not None else "").strip() if t != "str" else (raw or "")
    if t == "bool":
        return ("1" if raw.lower() in ("1", "true", "yes", "on") else "0"), ""
    if t == "int":
        if not re.fullmatch(r"-?\d+", raw or ""):
            return "", "需為整數"
        return str(int(raw)), ""
    if t == "float":
        try:
            return str(float(raw)), ""
        except ValueError:
            return "", "需為數字"
    if t == "choice":
        if raw not in (spec.get("choices") or []):
            return "", f"必須是 {'/'.join(spec.get('choices') or [])} 之一"
        return raw, ""
    # str
    if raw == "" and not spec.get("optional") and not spec.get("secret"):
        return "", "不可為空"
    return raw, ""


def _fmt_value(v: str) -> str:
    """dotenv 格式：含 # / 空白 / 引號時加雙引號"""
    if v == "":
        return ""
    if re.search(r'[#\s"]', v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def update_settings(updates: Dict[str, str], path: str = None) -> Tuple[List[str], List[str], Dict[str, str]]:
    """寫入 .env。回傳 (applied, restart_needed, errors)。

    - 不在白名單的 key → errors（拒寫）
    - secret 且值為空 → 跳過（視為「不修改」）
    - restart=False → 同步 os.environ 熱套用
    - 區塊替換：多行金鑰值原封保留（只換指定 key 的區塊）
    """
    path = path or ENV_PATH
    applied: List[str] = []
    restart: List[str] = []
    errors: Dict[str, str] = {}

    normalized: Dict[str, str] = {}
    for key, raw in (updates or {}).items():
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            errors[key] = "不在可編輯白名單"
            continue
        if spec.get("secret") and not str(raw or "").strip():
            continue                      # 機密留空 = 不修改
        val, err = _validate(spec, str(raw))
        if err:
            errors[key] = err
            continue
        normalized[key] = val

    if not normalized and errors:
        return applied, restart, errors

    if not os.path.exists(path):
        # 沒有 .env → 直接建（全部追加）
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for k, v in normalized.items():
                f.write(f"{k}={_fmt_value(v)}\n")
        applied = list(normalized)
        restart = [k for k in applied if SPEC_BY_KEY[k].get("restart")]
        for k in applied:
            if not SPEC_BY_KEY[k].get("restart"):
                os.environ[k] = normalized[k]
        return applied, restart, errors

    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    # ✏️ 動 .env 前先備份：控制台可編輯 → 必須可回滾。單檔輪替（.env.backup = 上一版）。
    #    （tests 有守：備份內容 = 寫入前的舊值）
    try:
        import shutil
        shutil.copy2(path, path + ".backup")
    except Exception:
        pass

    newline = "\r\n" if original.count("\r\n") > original.count("\n") // 2 else "\n"
    lines = original.replace("\r\n", "\n").split("\n")
    entries = _split_entries(lines)

    out_lines: List[str] = []
    pending = dict(normalized)
    last = 0
    for key, s, e in entries:
        out_lines.extend(lines[last:s])
        last = e
        if key in pending:
            out_lines.append(f"{key}={_fmt_value(pending.pop(key))}")
            applied.append(key)
        else:
            out_lines.extend(lines[s:e])
    out_lines.extend(lines[last:])
    # 追加新 key
    for k in list(pending):
        if out_lines and out_lines[-1] != "":
            out_lines.append("")
        out_lines.append(f"{k}={_fmt_value(pending.pop(k))}")
        applied.append(k)

    text = newline.join(out_lines)
    # 原子寫入（先 tmp 再 replace，避免寫到一半斷電毀掉 .env）
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".envtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    restart = [k for k in applied if SPEC_BY_KEY[k].get("restart")]
    for k in applied:                      # 熱套用：非 restart 的 key 立即生效
        if not SPEC_BY_KEY[k].get("restart"):
            os.environ[k] = normalized.get(k, os.environ.get(k, ""))
    return applied, restart, errors
