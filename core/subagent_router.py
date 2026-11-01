# -*- coding: utf-8 -*-
"""子智能體用腦路由（純函式、零依賴、可單元測試）。

背景：子智能體以前只會用 NV（Nemotron）。2026-10-09 起 Gemini 也能上桌：
兩邊額度疊起來大很多。2026-10-24～10-31：auto 兩棒都 Gemini 先、NV 只在 Gemini 報錯時接手。
2026-11-01 起改成下面這樣——老爸：「輝達就不要用來計時，負責高智商任務」——auto 的工具判定只用 Gemini；
深度思考兩顆一起想、誰先想好用誰（實測 NV 免費端點單獨工具判定 6 題 3 題卡 12 秒逾時，
單獨深思 6 題只成 2 題，當主力會拖垮回應；並排想就不拖時間）。
    auto   （預設）工具判定 Gemini；深度思考 Gemini＋NV 並排
    nv     舊行為：NV 工具判定 → NV 深度思考（不用 Gemini 一滴）
    gemini 全走 Gemini（不用 NV 一滴，NV 額度全留）
"""
from typing import List, Optional

SUBAGENT_BRAIN = "auto"   # 改這裡切換（以前讀環境變數；.env 只放金鑰）


def resolve_subagent_chain(mode: Optional[str] = None, stage: str = "tool") -> List[str]:
    """把模式字串解成用腦清單。stage="tool"（工具判定，照順序試）或 "think"（深度思考，auto 時並排一起想）。
    mode 缺省用本模組的 SUBAGENT_BRAIN。非法值一律視為 auto（= 預設行為），絕不炸、絕不回空鏈。
    """
    if mode is None:
        mode = SUBAGENT_BRAIN
    m = (mode or "auto").strip().lower()
    if m == "nv":
        return ["nv"]
    if m == "gemini":
        return ["gemini"]
    return ["gemini"] if stage == "tool" else ["gemini", "nv"]
