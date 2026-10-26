# -*- coding: utf-8 -*-
"""子智能體用腦路由（純函式、零依賴、可單元測試）。

背景：子智能體以前只會用 NV（Nemotron）。2026-10-09 起 Gemini 也能上桌：
兩邊額度疊起來大很多。NV 的推理模型深度思考要 60 秒，即時對話等不起，所以 auto 兩棒都 Gemini 先、
NV 只在 Gemini 報錯時接手（2026-10-24 改；之前深度思考是 NV 先）。
    auto   （預設）Gemini → NV 備援
    nv     舊行為：NV 工具判定 → NV 深度思考（不用 Gemini 一滴）
    gemini 全走 Gemini（不用 NV 一滴，NV 額度全留）
"""
from typing import List, Optional

SUBAGENT_BRAIN = "auto"   # 改這裡切換（以前讀環境變數；.env 只放金鑰）


def resolve_subagent_chain(mode: Optional[str] = None) -> List[str]:
    """把模式字串解成用腦順序。mode 缺省用本模組的 SUBAGENT_BRAIN。

    非法值一律視為 auto（= 預設行為），絕不炸、絕不回空鏈。
    """
    if mode is None:
        mode = SUBAGENT_BRAIN
    m = (mode or "auto").strip().lower()
    if m == "nv":
        return ["nv"]
    if m == "gemini":
        return ["gemini"]
    return ["gemini", "nv"]
