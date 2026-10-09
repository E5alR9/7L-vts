# -*- coding: utf-8 -*-
"""子智能體用腦路由（純函式、零依賴、可單元測試）。

背景：子智能體以前只會用 NV（Nemotron）。2026-10-09 起 Gemini 也能上桌：
NV 保留給真正要動腦的深度思考，Gemini 吃掉走量的工具判定——兩邊額度疊起來大很多。
    SUBAGENT_BRAIN=auto   （預設）Gemini 工具判定 → NV 深度思考
    SUBAGENT_BRAIN=nv     舊行為：NV 工具判定 → NV 深度思考（不用 Gemini 一滴）
    SUBAGENT_BRAIN=gemini 全走 Gemini（不用 NV 一滴，NV 額度全留）
"""
import os
from typing import List, Optional

VALID_MODES = ("auto", "nv", "gemini")


def resolve_subagent_chain(mode: Optional[str] = None) -> List[str]:
    """把模式字串解成用腦順序。mode 缺省讀環境變數 SUBAGENT_BRAIN（熱切換免重啟）。

    非法值一律視為 auto（= 預設行為），絕不炸、絕不回空鏈。
    """
    if mode is None:
        try:
            mode = os.getenv("SUBAGENT_BRAIN", "auto")
        except Exception:
            mode = "auto"
    m = (mode or "auto").strip().lower()
    if m == "nv":
        return ["nv"]
    if m == "gemini":
        return ["gemini"]
    return ["gemini", "nv"]
