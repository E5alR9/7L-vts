# -*- coding: utf-8 -*-
"""運行模式開機決定一次（2026-10-26，docs/REDESIGN.md 順手項）。

模式（companion＝1 對 1 伴侶、vtuber＝只對觀眾）決定兩件事：記憶檔用哪一份（core.memory 一 import 就把路徑定了），
和開哪些工作。以前開機先照 .env 的 MODE import 一堆模組（記憶路徑跟著定了），之後才讀後台存的模式開關
（MODE_TOGGLE）改環境變數——後台切過模式的話，下次開機記憶檔跟著 .env、工作跟著開關，兩邊錯開。
現在主程式一載入 .env 就呼叫 boot()：看本機知識庫裡存的模式開關，一次定好，之後才 import 其他模組。

切模式（後台的 MODE_TOGGLE）也只經 apply_mode() 改，跟模式綁在一起的老爸輸入／發聲開關一起設。
"""
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

MODES = ("companion", "vtuber")


@dataclass(frozen=True)
class Settings:
    mode: str
    operator_input: bool
    operator_speech: bool
    source: str          # 模式從哪來：".env" 或 "後台開關"


def apply_mode(mode: str) -> str:
    """設定運行模式：伴侶模式開老爸輸入、發聲，VTuber 模式關。回實際套用的模式。"""
    mode = mode if mode in MODES else "vtuber"
    on = "1" if mode == "companion" else "0"
    os.environ["MODE"] = mode
    os.environ["OPERATOR_INPUT"] = on
    os.environ["OPERATOR_SPEECH"] = on
    return mode


def saved_mode_switch(data_dir: str, env_mode: str) -> Optional[str]:
    """後台存的模式開關（本機知識庫 system_switches.MODE_TOGGLE）；沒存過回 None。
    知識庫照模式分檔，看的是 .env 模式那一份（後台切換時寫進的就是當時模式那份）。"""
    path = os.path.join(data_dir, f"cloud_knowledge_local_{env_mode}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            switches = (json.load(f) or {}).get("system_switches") or {}
    except Exception:
        return None
    if "MODE_TOGGLE" not in switches:
        return None
    return "companion" if switches["MODE_TOGGLE"] else "vtuber"


def boot(data_dir: str) -> Settings:
    """開機一次：.env 的 MODE，後台存過模式開關就照開關。要在 import core.memory 之前呼叫。"""
    env_mode = (os.getenv("MODE") or "vtuber").strip().lower()
    env_mode = env_mode if env_mode in MODES else "vtuber"
    saved = saved_mode_switch(data_dir, env_mode)
    if saved:
        mode, source = apply_mode(saved), "後台開關"
    else:
        mode, source = env_mode, ".env"
    mem = sys.modules.get("core.memory")
    if mem is not None and getattr(mem, "MODE", mode) != mode:
        print(f"⚠️ [運行模式] core.memory 已經用 {mem.MODE} 的記憶檔載入，跟這次的模式 {mode} 不同（settings.boot 要更早呼叫）")
    flag = lambda k: (os.getenv(k, "0") or "0").strip().lower() in ("1", "true", "yes")
    return Settings(mode=mode, operator_input=flag("OPERATOR_INPUT") and mode == "companion",
                    operator_speech=flag("OPERATOR_SPEECH"), source=source)
