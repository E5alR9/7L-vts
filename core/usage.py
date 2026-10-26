# -*- coding: utf-8 -*-
"""模型用量（2026-10-26，docs/REDESIGN.md 順手項）：每次呼叫模型記一筆——誰叫的、哪個模型、成功沒、
是不是被限流、花多久、幾個 token。後台「系統監控」有一張最近一小時的表（/api/model_usage）。

以前只有一個總數和金鑰健康，閒著一小時燒多少、哪個角色在燒，沒人知道。

誰叫的用 ContextVar 帶下去，底層的共用函式（live_one_shot、rest_chat、groq_chat）自己記，不用改函式簽名：
    with usage.as_role("看板哨兵"):
        await live_one_shot(...)
沒標的照底層函式的預設名字記（「Live 單次」「REST」「Groq」）。只記在記憶體，重開歸零。
"""
import contextlib
import contextvars
import functools
import time
from collections import deque
from typing import Optional

_ROLE: contextvars.ContextVar = contextvars.ContextVar("model_role", default="")
_CALLS: deque = deque(maxlen=50000)     # (時間, 角色, 模型, 成功, 限流, 毫秒, token)
_STARTED = time.time()


@contextlib.contextmanager
def as_role(role: str):
    token = _ROLE.set(role)
    try:
        yield
    finally:
        _ROLE.reset(token)


def role_scope(role: str):
    """裝飾 async 函式：裡面呼叫的模型都算這個角色（例：@usage.role_scope("看板哨兵")）。"""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **k):
            with as_role(role):
                return await fn(*a, **k)
        return wrapper
    return deco


def current_role(default: str = "") -> str:
    return _ROLE.get() or default


def is_rate_limited(err) -> bool:
    s = str(err).lower()
    return any(w in s for w in ("429", "quota", "exhausted", "rate limit", "rate_limit"))


def note(model: str, ok: bool = True, *, role: str = "", default_role: str = "", rate_limited: bool = False,
         ms: float = 0.0, tokens: int = 0, ts: Optional[float] = None) -> None:
    _CALLS.append((time.time() if ts is None else ts, role or current_role(default_role) or "未標",
                   model or "?", bool(ok), bool(rate_limited), float(ms), int(tokens or 0)))


@contextlib.contextmanager
def timed(model: str, *, role: str = "", default_role: str = ""):
    """包住一次呼叫：正常結束算成功、丟例外算失敗（限流另外標），花的時間一起記。
    回傳的物件可以設 .ok（例：回空字串算失敗）和 .tokens。"""
    t0 = time.perf_counter()
    r = type("UsageCall", (), {"ok": True, "tokens": 0})()
    try:
        yield r
    except BaseException as e:
        note(model, False, role=role, default_role=default_role, rate_limited=is_rate_limited(e),
             ms=(time.perf_counter() - t0) * 1000)
        raise
    else:
        note(model, r.ok, role=role, default_role=default_role, ms=(time.perf_counter() - t0) * 1000, tokens=r.tokens)


def summary(window: float = 3600.0, now: Optional[float] = None) -> list:
    """最近 window 秒，照（角色、模型）分組：次數、失敗、限流、平均毫秒、token。次數多的在前。"""
    now = time.time() if now is None else now
    groups = {}
    for ts, role, model, ok, limited, ms, tokens in list(_CALLS):
        if ts < now - window:
            continue
        g = groups.setdefault((role, model), {"role": role, "model": model, "calls": 0, "fails": 0,
                                              "rate_limited": 0, "ms_total": 0.0, "tokens": 0})
        g["calls"] += 1
        g["fails"] += 0 if ok else 1
        g["rate_limited"] += 1 if limited else 0
        g["ms_total"] += ms
        g["tokens"] += tokens
    rows = []
    for g in groups.values():
        g["avg_ms"] = round(g.pop("ms_total") / g["calls"]) if g["calls"] else 0
        rows.append(g)
    return sorted(rows, key=lambda g: (-g["calls"], g["role"], g["model"]))


def report(window: float = 3600.0) -> dict:
    """給後台：最近 window 秒的表，加上開機到現在的總數。"""
    return {"window_sec": window, "rows": summary(window), "total_since_start": len(_CALLS),
            "started_at": _STARTED}


def reset() -> None:
    _CALLS.clear()
