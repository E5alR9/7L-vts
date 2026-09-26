"""
⚡ Groq 極速文字路由器 (Groq Text Router)

🎯 目的：
   把所有「純文字」AI 呼叫（發言哨兵、背景決策、記憶審查、搜尋提煉、觀眾回應）
   統一走 Groq 第一梯隊，Gemini 只保留給視覺與 Live API 音訊。

⚙️ 設計：
   1. 多金鑰輪詢 (round-robin) + 逐 (金鑰, 模型) 冷卻，遇 429 自動降級到下一梯隊。
   2. 回傳 Gemini 形狀的相容物件 (.text / .function_calls[].name/.args)，
      讓呼叫端只換一行就能完成遷移，不必重寫下游解析邏輯。
   3. 工具宣告自動在「專案格式」與「OpenAI wire 格式」之間轉換，
      並把帶點號的工具名稱 (如 pe.play_virtual_piano) 安全地映射回原名。

用法：
    from core.groq_router import groq_chat
    resp = await groq_chat(messages, tools=INTERACTIONS_TOOLS, timeout=3.0)
    if resp:
        print(resp.text, resp.function_calls)
"""

import os
import re
import time
import asyncio
from typing import Any, Dict, List, Optional

# ── 模型梯隊（越前面越快；可用 GROQ_TEXT_MODELS 環境變數覆寫）────────────────
# 實測本帳號 /models 只有 11 個，其中可自由對話的僅下列 4 個
# （whisper-large-v3*、meta-llama/llama-prompt-guard-*、canopylabs/orpheus-*
#   openai/gpt-oss-safeguard-20b 都不是聊天模型；原梯隊的 groq/compound[mini]
#   在本帳號不存在，呼叫會直接 404，已移除）
DEFAULT_MODEL_LADDER = [
    "qwen/qwen3.8-27b",        # 極速主力（原專案第一順位，實測 0.4s 級）
    "openai/gpt-oss-120b",     # 高智商旗艦（120B 最強推理）
    "openai/gpt-oss-20b",      # 輕量保底（20B 快答）
    "allam-2-7b",              # 最終防線（7B；阿拉伯語系為主，中文較弱，僅墊底）
]


def _load_keys() -> List[str]:
    raw = (
        os.getenv("GROQ_API_KEYS")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("GROQ_KEYS")
        or os.getenv("GROQ_KEY")
        or ""
    )
    return [k.strip() for k in re.split(r"[\s,;]+", raw) if k.strip()]


def _load_ladder() -> List[str]:
    raw = os.getenv("GROQ_TEXT_MODELS") or ""
    models = [m.strip() for m in re.split(r"[\s,;]+", raw) if m.strip()]
    return models or list(DEFAULT_MODEL_LADDER)


# ── 每分鐘請求限流（GROQ_REQUESTS_PER_MINUTE，0 或未設 = 不限）──────────────
# 滑動 60 秒視窗；跨金鑰總量計算（限的是「這台機器打給 Groq 的總請求」）。
# 惰性讀取 env：改 .env 後重啟（或 dotenv 重載）即生效，不需改程式。
_rpm_stamp: List[float] = []
_rpm_last_log = 0.0


def _rpm_limit() -> int:
    raw = (os.getenv("GROQ_REQUESTS_PER_MINUTE") or "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 0


async def throttle_rpm() -> None:
    """在實際發出請求前呼叫；超過每分鐘上限就等到視窗滑動。"""
    global _rpm_last_log
    limit = _rpm_limit()
    if limit <= 0:
        _rpm_stamp.clear()
        return
    while True:
        now = time.monotonic()
        while _rpm_stamp and now - _rpm_stamp[0] >= 60.0:
            _rpm_stamp.pop(0)
        if len(_rpm_stamp) < limit:
            break
        wait = 60.0 - (now - _rpm_stamp[0]) + 0.05
        if now - _rpm_last_log > 30.0:
            _rpm_last_log = now
            _log(f"[Groq Router] 達到 {limit} RPM 上限，等待 {wait:.1f}s（視窗滑動）")
        await asyncio.sleep(min(max(wait, 0.05), 60.0))
    _rpm_stamp.append(time.monotonic())


GROQ_KEYS: List[str] = _load_keys()
MODEL_LADDER: List[str] = _load_ladder()

_clients: List[Any] = []
_client_error: Optional[str] = None
# 冷卻表：key -> 何時解除
_key_cooldown: Dict[str, float] = {}
# 模型鎖：model -> 何時解除（整台模型暫時下架）
_model_cooldown: Dict[str, float] = {}
_call_step = 0


def _get_clients() -> List[Any]:
    """延遲建立 AsyncGroq 用戶端（每把金鑰一個）"""
    global _clients, _client_error, GROQ_KEYS
    if _clients:
        return _clients
    if not GROQ_KEYS:
        # dotenv 可能在本模組 import 之後才載入，這裡補撈一次
        GROQ_KEYS = _load_keys()
    if not GROQ_KEYS:
        return _clients
    try:
        from groq import AsyncGroq
        _clients = [AsyncGroq(api_key=k) for k in GROQ_KEYS if k]
    except Exception as e:  # pragma: no cover - 套件缺失時保持靜默降級
        _client_error = str(e)
        _clients = []
    return _clients


def is_available() -> bool:
    """是否有可用的 Groq 金鑰且未全數冷卻"""
    if not GROQ_KEYS:
        return False
    now = time.time()
    return any(_key_cooldown.get(k, 0) < now for k in GROQ_KEYS)


def reset():
    """測試用：清空冷卻狀態"""
    _key_cooldown.clear()
    _model_cooldown.clear()


# ── 模型可用性交叉驗證（自動過濾已下架/寫錯的模型名）─────────────────────────
# 背景：Groq 會調整模型名單，梯隊裡若殘留不存在的名稱，每次都會撞 404 浪費一輪。
_models_cache: Dict[str, Any] = {"at": 0.0, "set": None, "fail_at": 0.0}
_MODELS_TTL = 6 * 3600.0     # 6 小時抓一次
_MODELS_RETRY = 120.0        # 抓取失敗後 2 分鐘才重試，避免每次呼叫都打 /models


def _log(msg: str) -> None:
    """安全輸出（Windows cp950 主控台印不出部分字元時自動降級）"""
    try:
        print(msg)
    except Exception:
        try:
            print(msg.encode("utf-8", "replace").decode("ascii", "replace"))
        except Exception:
            pass


def _fetch_available_models_sync() -> Optional[set]:
    if not GROQ_KEYS:
        return None
    try:
        import httpx
        r = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {GROQ_KEYS[0]}"},
            timeout=10.0,
        )
        if r.status_code == 200:
            ids = {m.get("id") for m in (r.json().get("data") or []) if m.get("id")}
            return ids or None
    except Exception:
        pass
    return None


def get_available_models(force: bool = False) -> Optional[set]:
    """同步取得可用模型集合（有快取；失敗回 None 表示「不確定」）"""
    now = time.time()
    cached = _models_cache.get("set")
    if cached is not None and (force or now - float(_models_cache.get("at") or 0) < _MODELS_TTL):
        return cached
    if not force and now - float(_models_cache.get("fail_at") or 0) < _MODELS_RETRY:
        return cached   # 剛失敗過，先沿用舊值（可能仍是 None）
    ids = _fetch_available_models_sync()
    if ids:
        _models_cache.update(at=now, set=ids, fail_at=0.0)
        return ids
    _models_cache["fail_at"] = now
    return cached


async def _filter_unavailable(ladder: List[str]) -> List[str]:
    """把當前帳號上不存在的模型名從梯隊剔除（查證失敗時維持原梯隊）"""
    if len(ladder) <= 1:
        return ladder
    avail = await asyncio.to_thread(get_available_models)
    if not avail:
        return ladder
    kept = [m for m in ladder if m in avail]
    if not kept:                     # 快取過期/名稱全變：寧可用原梯隊也不要空的
        return ladder
    dropped = [m for m in ladder if m not in avail]
    if dropped:
        _log(f"[Groq Router] 過濾掉不存在的模型: {dropped}（保留 {kept}）")
    return kept


# ── 回傳物件：模擬 Google GenAI 的回應形狀 ───────────────────────────────────
class _FunctionCall:
    __slots__ = ("name", "args", "call_id", "wire_name")

    def __init__(self, name: str, args: Dict[str, Any], call_id: str = "", wire_name: str = ""):
        self.name = name          # 還原後的原名（含點號，供 execute_tool_dispatch 使用）
        self.args = args or {}
        self.call_id = call_id    # OpenAI tool_call id（多輪追蹤用）
        self.wire_name = wire_name or name

    def __repr__(self):  # pragma: no cover
        return f"_FunctionCall({self.name}, {self.args})"


class GroqResponse:
    """Gemini 相容回應殼：下游只需用 .text / .function_calls 即可"""

    __slots__ = ("text", "function_calls", "raw", "model")

    def __init__(self, text: Optional[str], function_calls: List[_FunctionCall], raw: Any, model: str):
        self.text = text
        self.function_calls = function_calls
        self.raw = raw
        self.model = model

    def __bool__(self) -> bool:
        return bool(self.text) or bool(self.function_calls)


# ── 工具宣告轉換 ─────────────────────────────────────────────────────────────
_DOT_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def _schema_to_json(schema: Any) -> Dict[str, Any]:
    """把 google.genai Schema / 一般 dict 轉成 JSON Schema"""
    if schema is None:
        return {}
    if isinstance(schema, dict):
        out: Dict[str, Any] = {}
        s_type = schema.get("type")
        if s_type:
            out["type"] = str(s_type).lower()
        if schema.get("description"):
            out["description"] = schema["description"]
        props = schema.get("properties")
        if isinstance(props, dict):
            out["type"] = out.get("type", "object")
            out["properties"] = {k: _schema_to_json(v) for k, v in props.items()}
        if schema.get("required"):
            out["required"] = list(schema["required"])
        items = schema.get("items")
        if items is not None:
            out["items"] = _schema_to_json(items)
        return out

    # google.genai types.Schema
    out = {}
    s_type = getattr(schema, "type", None)
    if s_type:
        try:
            out["type"] = str(getattr(s_type, "value", s_type)).lower()
        except Exception:
            out["type"] = str(s_type).lower()
    desc = getattr(schema, "description", None)
    if desc:
        out["description"] = desc
    props = getattr(schema, "properties", None)
    if props:
        out["type"] = out.get("type", "object")
        out["properties"] = {k: _schema_to_json(v) for k, v in dict(props).items()}
    required = getattr(schema, "required", None)
    if required:
        out["required"] = list(required)
    items = getattr(schema, "items", None)
    if items is not None:
        out["items"] = _schema_to_json(items)
    return out


def _iter_decl(tool: Any):
    """回傳 (name, description, parameters_json_schema)；不支援則回傳 None"""
    if isinstance(tool, dict):
        # 專案格式：{"type":"function","name":...,"description":...,"parameters":{...}}
        if "name" in tool and "function" not in tool:
            return (
                tool.get("name", ""),
                tool.get("description", ""),
                _schema_to_json(tool.get("parameters") or {}),
            )
        # OpenAI wire 格式：{"type":"function","function":{...}}
        fn = tool.get("function")
        if isinstance(fn, dict):
            return (
                fn.get("name", ""),
                fn.get("description", ""),
                _schema_to_json(fn.get("parameters") or {}),
            )
        return None

    # google.genai types.Tool(function_declarations=[...])
    decls = getattr(tool, "function_declarations", None)
    if decls:
        # 這裡只支援單個 declaration 的情況；多個時由呼叫端展平
        d = decls[0]
        return (
            getattr(d, "name", ""),
            getattr(d, "description", ""),
            _schema_to_json(getattr(d, "parameters", None)),
        )
    return None


def to_openai_tools(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """把專案格式 / Gemini 格式的工具宣告轉成 OpenAI wire 格式"""
    if not tools:
        return []
    out: List[Dict[str, Any]] = []
    for tool in tools:
        if tool is None:
            continue
        # Gemini Tool 可能內含多個 declaration，先展平
        decls = getattr(tool, "function_declarations", None)
        if decls:
            for d in decls:
                item = {
                    "name": getattr(d, "name", ""),
                    "description": getattr(d, "description", ""),
                    "parameters": _schema_to_json(getattr(d, "parameters", None)),
                }
                out.append(_as_wire(item))
            continue
        parsed = _iter_decl(tool)
        if parsed:
            name, desc, params = parsed
            if name:
                out.append(_as_wire({"name": name, "description": desc, "parameters": params}))
    return out


def _as_wire(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": item["name"],
            "description": item.get("description", "") or "",
            "parameters": item.get("parameters") or {"type": "object", "properties": {}},
        },
    }


def _wire_name(original: str) -> str:
    """OpenAI 工具名稱只允許 [A-Za-z0-9_-]，把 pe.play_virtual_piano 之類的點號安全化"""
    return _DOT_SAFE.sub("_", original) if original else original


# ── 主呼叫函式 ───────────────────────────────────────────────────────────────
async def groq_chat(
    messages: List[Dict[str, str]],
    *,
    tools: Optional[List[Any]] = None,
    model: Optional[str] = None,
    temperature: float = 0.75,
    max_tokens: int = 500,
    timeout: float = 4.0,
    models: Optional[List[str]] = None,
) -> Optional[GroqResponse]:
    """
    以 Groq 進行一次文字補全。成功回傳 GroqResponse，全部失敗回傳 None（呼叫端自行降級）。

    messages: OpenAI 格式 [{"role": "...", "content": "..."}]
    tools:    專案格式 INTERACTIONS_TOOLS 或 Gemini tools，都會自動轉換
    """
    global _call_step

    clients = _get_clients()
    if not clients:
        return None

    ladder = models or ([model] if model else MODEL_LADDER)
    ladder = await _filter_unavailable(ladder)   # 剔除 Groq 帳號上不存在的模型名
    wire_tools = to_openai_tools(tools) if tools else None

    # 工具名稱映射（安全化 -> 原名），供回應還原
    name_map: Dict[str, str] = {}
    if wire_tools:
        for wt in wire_tools:
            original = wt["function"]["name"]
            safe = _wire_name(original)
            if safe != original:
                name_map[safe] = original
                wt["function"]["name"] = safe

    now = time.time()
    _call_step += 1

    # 依序嘗試：模型梯隊 × 金鑰輪詢
    for m_name in ladder:
        if _model_cooldown.get(m_name, 0) > now:
            continue
        for offset in range(len(clients)):
            idx = (_call_step + offset) % len(clients)
            key = GROQ_KEYS[idx] if idx < len(GROQ_KEYS) else ""
            if key and _key_cooldown.get(key, 0) > now:
                continue
            client = clients[idx]
            try:
                kwargs: Dict[str, Any] = {
                    "model": m_name,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if wire_tools:
                    kwargs["tools"] = wire_tools

                await throttle_rpm()   # 每分鐘請求上限（GROQ_REQUESTS_PER_MINUTE）
                raw = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=timeout)

                if not raw or not raw.choices:
                    continue
                choice = raw.choices[0]
                msg = choice.message
                text = getattr(msg, "content", None)
                if text is not None:
                    text = text.strip()

                fcs: List[_FunctionCall] = []
                for tc in (getattr(msg, "tool_calls", None) or []):
                    fn = getattr(tc, "function", None)
                    if fn is None:
                        continue
                    safe_name = getattr(fn, "name", "") or ""
                    import json as _json
                    try:
                        args = _json.loads(getattr(fn, "arguments", None) or "{}")
                    except Exception:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    call_id = getattr(tc, "id", "") or ""
                    fcs.append(_FunctionCall(
                        name_map.get(safe_name, safe_name),
                        args,
                        call_id=call_id,
                        wire_name=safe_name,
                    ))

                if not text and not fcs:
                    continue
                return GroqResponse(text=text, function_calls=fcs, raw=raw, model=m_name)

            except asyncio.TimeoutError:
                # 超時通常是單次抖動，換下一組金鑰即可
                continue
            except Exception as e:
                _note_failure(m_name, key, str(e))
                continue

    return None


# ── 自動工具多輪：模型呼叫工具 -> 執行 -> 回填結果再問一次 ─────────────────────
async def groq_chat_auto(
    messages: List[Dict[str, str]],
    *,
    tools: Optional[List[Any]] = None,
    tool_executor=None,
    max_rounds: int = 3,
    timeout: float = 4.0,
    temperature: float = 0.75,
    max_tokens: int = 500,
    models: Optional[List[str]] = None,
) -> Optional[GroqResponse]:
    """
    自動完成 Function Calling 迴圈。

    tool_executor: async fn(fn_name, fn_args) -> str（通常是 execute_tool_dispatch 的包裝）
                   若為 None，則模型一呼叫工具就直接回傳（交給呼叫端決定）。
    回傳：text = 各輪口語的串接；function_calls = 最後一輪的工具呼叫。
    """
    import json as _json

    msgs: List[Dict[str, Any]] = list(messages)
    text_parts: List[str] = []
    last_fcs: List[_FunctionCall] = []
    last_resp: Optional[GroqResponse] = None

    for _round in range(max(1, max_rounds)):
        resp = await groq_chat(
            msgs, tools=tools, timeout=timeout,
            temperature=temperature, max_tokens=max_tokens, models=models,
        )
        if resp is None:
            break
        last_resp = resp

        if resp.text:
            text_parts.append(resp.text)

        if not resp.function_calls:
            break
        if tool_executor is None:
            break  # 沒有執行器：原樣交回呼叫端

        last_fcs = resp.function_calls
        # 1) 追加 assistant 訊息（帶 wire 名稱與 tool_call id）
        msgs.append({
            "role": "assistant",
            "content": resp.text or "",
            "tool_calls": [
                {
                    "id": fc.call_id or f"call_{i}",
                    "type": "function",
                    "function": {"name": fc.wire_name, "arguments": _json.dumps(fc.args, ensure_ascii=False)},
                }
                for i, fc in enumerate(resp.function_calls)
            ],
        })
        # 2) 逐個執行工具並回填 tool 結果
        for fc in resp.function_calls:
            try:
                result = await tool_executor(fc.name, fc.args)
            except Exception as e:
                result = f"工具執行錯誤: {e}"
            msgs.append({
                "role": "tool",
                "tool_call_id": fc.call_id or "",
                "content": str(result)[:4000] if result is not None else "",
            })

    if last_resp is None:
        return None

    combined = "\n".join(t for t in text_parts if t and t.strip()).strip()
    if not combined and not last_fcs:
        return None
    return GroqResponse(text=combined or None, function_calls=last_fcs, raw=last_resp.raw, model=last_resp.model)


# ── Google GenAI 內容 -> OpenAI 訊息（純文字） ───────────────────────────────
def contents_to_messages(contents) -> Optional[List[Dict[str, str]]]:
    """
    把 google.genai 的 types.Content 列表轉成 OpenAI messages。
    含圖片/音訊等非文字零件時回傳 None（這類多模態請求請交給 Gemini）。
    """
    if not contents:
        return None
    out: List[Dict[str, str]] = []
    for c in contents:
        role = getattr(c, "role", "user") or "user"
        oai_role = "assistant" if role in ("model", "assistant") else "user"
        parts = getattr(c, "parts", None) or []
        texts = []
        for p in parts:
            if getattr(p, "inline_data", None) is not None:
                return None                      # 圖片 / 音訊 -> 交給 Gemini
            if getattr(p, "function_call", None) is not None:
                return None                      # 既有工具呼叫軌跡 -> 交給 Gemini
            t = getattr(p, "text", None)
            if t:
                texts.append(t)
        if texts:
            out.append({"role": oai_role, "content": "\n".join(texts)})
    return out or None


def _note_failure(model: str, key: str, err: str):
    """依錯誤內容施加短冷卻（429 冷卻較長、其他短暫冷卻）"""
    now = time.time()
    low = err.lower()
    if "429" in err or "rate limit" in low or "rate_limit" in low:
        if key:
            _key_cooldown[key] = now + 30.0
        _model_cooldown[model] = now + 60.0
    elif "timeout" in low or "timed out" in low or "connection" in low:
        if key:
            _key_cooldown[key] = now + 3.0
    elif "model" in low and ("not found" in low or "does not exist" in low or "invalid" in low):
        # 模型名稱過期：整台下架 10 分鐘，避免每次都撞
        _model_cooldown[model] = now + 600.0


# ── 同步便捷包裝（給非 async 場景用）─────────────────────────────────────────
def chat_sync(*args, **kwargs) -> Optional[GroqResponse]:
    """同步包裝：僅供測試腳本使用（會自行建立事件迴圈）"""
    return asyncio.new_event_loop().run_until_complete(groq_chat(*args, **kwargs))
