# -*- coding: utf-8 -*-
"""
7L 實時任務與雲端狀態同步模組 (Realtime Tasks Hub)
提供所有 AI 協程與外部大腦自主抓取 7L 即時狀態、進行中任務、鋼琴曲目、視覺感知與對話上下文的能力。
"""

from .task_manager import RealtimeTaskManager, realtime_task_mgr

__all__ = ["RealtimeTaskManager", "realtime_task_mgr"]
