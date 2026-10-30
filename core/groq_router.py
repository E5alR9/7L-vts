"""
⚡ Groq 極速文字路由器 (Groq Text Router)
PROVIDER: GROQ（api.groq.com 直連；見 docs/AI_SOURCES.md）

🎯 目的：
   純文字的快線：REST 大腦第一棒（core/rest_brain）、哨兵的 Groq 備援、搜尋提煉、鋼琴意圖解析；
   多模態與 Live 走 Gemini。

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

from core import usage
from core.env_config import load_project_env
from core.utils import log_print

load_project_env()   # 下面載入時就讀 GROQ 金鑰：誰先 import 本模組都一樣

# ── 模型梯隊（越前面越快；可用 GROQ_TEXT_MODELS 環境變數覆寫）────────────────
# 實測本帳號 /models 只有 11 個，其中可自由對話的僅下列 4 個
# （whisper-large-v3*、meta-llama/llama-prompt-guard-*、canopylabs/orpheus-*
#   openai/gpt-oss-safeguard-20b 都不是聊天模型；原梯隊的 groq/compound[mini]
#   在本帳號不存在，呼叫會直接 404，已移除）
DEFAULT_MODEL_LADDER = [
    "qwen/qwen3.8-27b",        # 極速主力（原專案第一順位，實測 0.4s 級）
    "openai/gpt-oss-120b",     # 高智商旗艦（120B 最強推理）
    "openai/gpt-oss-20b",      # 輕量保底（20B 快答）
]
# allam-2-7b 2026-10-27 拿掉：實測記憶濃縮整段重複亂寫，哨兵格式也不對，墊底只會講錯話

# gpt-oss 是推理模型：先想再答，想的部分也算 max_tokens。不設的話想太久、內容回空字串（2026-10-27 實測三題空兩題半）
REASONING_EFFORT = "low"
REASONING_EXTRA_TOKENS = 512


def _is_reasoning_model(model: str) -> bool:
    return model.startswith("openai/gpt-oss")


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
# 冷卻表：(key, model) -> 何時解除。每把金鑰是各自的組織、額度各算，而且額度是一個模型一份
# （2026-10-30 實測：每把每天 1000 次、每分鐘 8000 token，互不影響），所以一把撞限流不該連累別把或別的模型
_key_cooldown: Dict[tuple, float] = {}
# 模型鎖：model -> 何時解除（整台模型暫時下架）
_model_cooldown: Dict[str, float] = {}
_call_step = 0


def make_async_clients(keys) -> List[Any]:
    """每把金鑰一個 AsyncGroq，共用同一個 HTTP 連線池。各自建的話每個都要載一次 SSL 設定，
    26 把要 6 秒，而且是在第一次 groq_chat 裡同步建、整個程式凍住（2026-10-26 量的）；共用只要 0.5 秒。"""
    from groq import AsyncGroq, DefaultAsyncHttpxClient
    shared = DefaultAsyncHttpxClient()
    return [AsyncGroq(api_key=k, http_client=shared) for k in keys if k]


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
        _clients = make_async_clients(GROQ_KEYS)
    except Exception as e:  # pragma: no cover - 套件缺失時保持靜默降級
        _client_error = str(e)
        _clients = []
    return _clients


def is_available() -> bool:
    """是否有可用的 Groq 金鑰且未全數冷卻"""
    if not GROQ_KEYS:
        return False
    now = time.time()
    return any(_key_cooldown.get((k, m), 0) < now for k in GROQ_KEYS for m in MODEL_LADDER)


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
        log_print(msg)
    except Exception:
        try:
            log_print(msg.encode("utf-8", "replace").decode("ascii", "replace"))
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
            data = r.json().get("data") or []
            ids = {m.get("id") for m in data if m.get("id")}
            # 每個模型一次最多能生多少（2026-10-30 實測：qwen3.8-27b 16384、gpt-oss 65536），超過 Groq 直接回 400
            _models_cache["caps"] = {m["id"]: int(m["max_completion_tokens"]) for m in data
                                     if m.get("id") and isinstance(m.get("max_completion_tokens"), int)}
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
    avail = await asyncio.to_thread(get_available_models)   # 只指定一個模型也要抓：生成上限的天花板從這裡來
    if len(ladder) <= 1:
        return ladder
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


# ── 串流收字：卡住馬上知道 ───────────────────────────────────────────────────
# 2026-10-30 老爸：一次拿整段的話，Groq 卡住要等到時限才知道，中間分不出是還在跑還是卡死了。
# 串流一塊一塊來，多久沒來就是卡了（平常第一塊 0.2～0.4 秒、之後幾乎連續）
FIRST_CHUNK_SEC = 3.0   # 送出後這麼久連第一塊都沒來
STALL_SEC = 2.0         # 開始吐字以後，中間停這麼久


class _Stalled(Exception):
    pass


async def _stream_reply(client: Any, kwargs: Dict[str, Any], hard_timeout: float) -> Any:
    """用串流拿一次回覆，收完拼成跟非串流一樣的形狀（.choices[0].message.content、.usage.total_tokens）。
    沒在 FIRST_CHUNK_SEC／STALL_SEC 內等到下一塊就丟 _Stalled；整段超過 hard_timeout 照舊丟 TimeoutError。"""
    end = time.monotonic() + hard_timeout

    async def within(aw, limit: float, what: str):
        left = end - time.monotonic()
        if left <= 0:
            if asyncio.iscoroutine(aw):
                aw.close()   # 沒等就丟掉，免得跳「coroutine was never awaited」
            raise asyncio.TimeoutError
        try:
            return await asyncio.wait_for(aw, timeout=min(limit, left))
        except asyncio.TimeoutError:
            if limit + 0.05 < left:   # 留點餘裕：兩個一樣長時，浮點誤差會讓「時限到了」被誤報成卡住
                raise _Stalled(what) from None
            raise

    stream = await within(client.chat.completions.create(**kwargs, stream=True), FIRST_CHUNK_SEC,
                          f"送出 {FIRST_CHUNK_SEC:.0f} 秒都沒回應")
    parts: List[str] = []
    finish = None
    tokens = 0
    got_any = False
    try:
        it = stream.__aiter__()
        while True:
            try:
                chunk = await within(it.__anext__(), STALL_SEC if got_any else FIRST_CHUNK_SEC,
                                     f"吐了 {len(''.join(parts))} 字後卡住 {STALL_SEC:.0f} 秒" if got_any
                                     else f"{FIRST_CHUNK_SEC:.0f} 秒都沒吐出第一塊")
            except StopAsyncIteration:
                break
            got_any = True   # 推理模型先吐的思考內容也算有在動
            for ch in (getattr(chunk, "choices", None) or []):
                piece = getattr(getattr(ch, "delta", None), "content", None)
                if piece:
                    parts.append(piece)
                finish = getattr(ch, "finish_reason", None) or finish
            used = getattr(chunk, "usage", None) or getattr(getattr(chunk, "x_groq", None), "usage", None)
            tokens = getattr(used, "total_tokens", 0) or tokens
    finally:
        try:
            await stream.close()
        except Exception:
            pass

    from types import SimpleNamespace
    if not got_any:
        return SimpleNamespace(choices=[], usage=None)
    message = SimpleNamespace(content="".join(parts), tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)],
                           usage=SimpleNamespace(total_tokens=tokens))


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
    total_timeout: Optional[float] = None,
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
    # 總時限：timeout 只管單次；梯隊 × 金鑰全逾時的話，舊碼最壞要好幾分鐘才回 None（2026-10-25 健檢）
    budget = total_timeout if total_timeout is not None else max(timeout * 3, 10.0)
    deadline = time.monotonic() + budget

    stalls: Dict[str, int] = {}   # 這次呼叫裡每個模型卡住幾次

    # 依序嘗試：模型梯隊 × 金鑰輪詢
    for m_name in ladder:
        if _model_cooldown.get(m_name, 0) > now:
            continue
        for offset in range(len(clients)):
            idx = (_call_step + offset) % len(clients)
            key = GROQ_KEYS[idx] if idx < len(GROQ_KEYS) else ""
            if key and _key_cooldown.get((key, m_name), 0) > now:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0.3:
                _log(f"[Groq Router] 超過總時限 {budget:.0f}s，這次放棄（呼叫端自行降級）")
                return None
            client = clients[idx]
            try:
                # max_tokens 是 Groq 標示淘汰的舊名，送新名 max_completion_tokens
                limit = max_tokens + (REASONING_EXTRA_TOKENS if _is_reasoning_model(m_name) else 0)
                cap = (_models_cache.get("caps") or {}).get(m_name)
                kwargs: Dict[str, Any] = {
                    "model": m_name,
                    "messages": messages,
                    "temperature": temperature,
                    "max_completion_tokens": min(limit, cap) if cap else limit,
                }
                if _is_reasoning_model(m_name):
                    kwargs["extra_body"] = {"reasoning_effort": REASONING_EFFORT}
                if wire_tools:
                    kwargs["tools"] = wire_tools

                await asyncio.wait_for(throttle_rpm(), timeout=remaining)   # 每分鐘請求上限（GROQ_REQUESTS_PER_MINUTE）
                hard = max(0.3, min(timeout, deadline - time.monotonic()))
                with usage.timed(f"Groq/{m_name}", default_role="Groq") as u:
                    if wire_tools:   # 工具呼叫串流要自己拼參數，目前也沒人帶工具走 Groq：照舊一次拿
                        raw = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=hard)
                    else:
                        raw = await _stream_reply(client, kwargs, hard)
                    u.ok = bool(raw and raw.choices)
                    u.tokens = getattr(getattr(raw, "usage", None), "total_tokens", 0) or 0

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
                    break   # 這個模型回空的：換下一個模型（以前換下一把金鑰、同一個模型，全空時把金鑰輪完才換）
                if getattr(choice, "finish_reason", "") == "length":
                    # 到生成上限被切斷：講話會斷在半句、JSON 會解析失敗，至少留個紀錄找得到原因
                    _log(f"[Groq Router] {m_name} 寫到上限 {kwargs['max_completion_tokens']} 被切斷，呼叫端該給大一點")
                return GroqResponse(text=text, function_calls=fcs, raw=raw, model=m_name)

            except _Stalled as e:
                # 串流卡住馬上就知道，不用等到整段時限。偶爾一次是那台伺服器抖，換把金鑰；
                # 同一個模型這次卡第二次，多半是這個模型整個慢下來了，換下一個模型
                stalls[m_name] = stalls.get(m_name, 0) + 1
                gave_up = stalls[m_name] >= 2
                _log(f"[Groq Router] {m_name} {e}，{'換下一個模型' if gave_up else '換一把金鑰再試'}")
                if gave_up:
                    break
                continue
            except asyncio.TimeoutError:
                # 超時通常是單次抖動，換下一組金鑰即可
                continue
            except Exception as e:
                if _note_failure(m_name, key, e) == "next_model":
                    break
                continue

    return None


# ── 自動工具多輪：模型呼叫工具 -> 執行 -> 回填結果再問一次 ─────────────────────


# ── Google GenAI 內容 -> OpenAI 訊息（純文字） ───────────────────────────────


_RETRY_IN = re.compile(r"try again in\s+(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s|([\d.]+)ms)?", re.I)


def _retry_after(e: Exception, err: str) -> float:
    """Groq 叫我們等多久：先看 retry-after 標頭，再看訊息裡的「try again in 1m26.4s」；都沒有就 30 秒。"""
    try:
        v = getattr(getattr(e, "response", None), "headers", {}).get("retry-after")
        if v:
            return min(max(float(v), 1.0), 6 * 3600.0)
    except Exception:
        pass
    m = _RETRY_IN.search(err)
    if m and any(m.groups()):
        h, mi, se, ms = m.groups()
        wait = int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0) + float(ms or 0) / 1000
        return min(max(wait, 1.0), 6 * 3600.0)
    return 30.0


def _note_failure(model: str, key: str, e: Any) -> str:
    """依錯誤施加冷卻，回 "next_key"（換一把金鑰再試同一個模型）或 "next_model"（這個模型這次別試了）。"""
    err = str(e)
    now = time.time()
    low = err.lower()
    status = getattr(e, "status_code", None)
    if status == 413 or "request too large" in low:
        # 一次塞的字超過這個模型每分鐘的上限（2026-10-30 實測 qwen 輸入每分鐘 7000 token）：每把都一樣，換把只是再被拒一次。
        # 以前當成限流：29 把輪流撞完全部冷卻，Groq 整個停擺半分鐘，哨兵、點歌判斷一起掛
        _log(f"[Groq Router] {model} 一次塞太多字被拒，換下一個模型：{err[:160]}")
        return "next_model"
    if status == 429 or "429" in err or "rate limit" in low or "rate_limit" in low:
        if key:
            _key_cooldown[(key, model)] = now + _retry_after(e, err)
        return "next_key"
    if status == 404 or "model_not_found" in low or "model_decommissioned" in low or "does not exist" in low:
        # 模型名稱過期：整台下架 10 分鐘，避免每次都撞
        _model_cooldown[model] = now + 600.0
        return "next_model"
    if status == 400 or "invalid_request_error" in low:
        # 請求本身有問題（參數不支援、上限給太大）：換金鑰也一樣，也不是模型下架。
        # 以前訊息裡有 model 和 invalid 就整台冷卻 10 分鐘，生成上限給太大也會中
        _log(f"[Groq Router] {model} 不接受這個請求，換下一個模型：{err[:160]}")
        return "next_model"
    if "timeout" in low or "timed out" in low or "connection" in low:
        if key:
            _key_cooldown[(key, model)] = now + 3.0
    return "next_key"


