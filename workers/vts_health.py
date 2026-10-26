# -*- coding: utf-8 -*-
"""VTS 健康檢查：每幾秒確認 VTube Studio 還連著，斷了就重連、重新認證、把臉部追蹤接回來。

主程式的狀態經 host.<名稱> 即時讀寫（host＝主程式模組，主程式 import 本檔後 bind()）。
用到的名稱列在 HOST_ATTRS，tests/test_workers_host.py 核對主程式真的都有定義。
"""
import asyncio
import time

import services.vts_client as vc
from core.utils import log_print, spawn
from workers.face_tracking import ai_face_tracking_loop

HOST_ATTRS = (
    "GLOBAL_VTS_TRACKING_TASK",
)

host = None


def bind(main_module) -> None:
    global host
    host = main_module


_VTS_LAST_AUTH_TIME = 0.0
_VTS_LAST_RECONNECT_TIME = 0.0
_VTS_IS_RECONNECTING = False  # 防止重連競態

_VTS_PING_MSG = {
    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
    "requestID": "HealthPing", "messageType": "APIStateRequest", "data": {}
}


async def _vts_real_ping(vts):
    """真實 WebSocket ping：送 APIStateRequest 並等待回應。
    回傳 None = 連線已死；回傳 True/False = 連線活著，且本 session 是否已通過認證
    （APIStateRequest 不需認證也會回應，所以光「有回應」不代表 token 有效）"""
    try:
        async with vc.vts_lock:
            resp = await asyncio.wait_for(vts.request(_VTS_PING_MSG), timeout=1.5)
        if not isinstance(resp, dict) or resp.get("messageType") != "APIStateResponse":
            return None
        return bool(resp.get("data", {}).get("currentSessionAuthenticated", False))
    except Exception:
        return None


async def vts_health_worker(vts):
    global _VTS_LAST_AUTH_TIME, _VTS_LAST_RECONNECT_TIME, _VTS_IS_RECONNECTING
    while True:
        await asyncio.sleep(5.0)  # 5 秒心跳（比原本 3 秒寬鬆，減少 ping 佔用）
        if _VTS_IS_RECONNECTING:
            continue
        try:
            now = time.time()
            #  真實 ping 測試：不靠 is_connected() 假狀態，直接送 APIStateRequest
            authed = await _vts_real_ping(vts)
            if not authed:
                #  斷線，或連著但沒認證（token 失效 / request() 自動重連後沒重新認證）：10 秒冷卻
                if now - _VTS_LAST_RECONNECT_TIME >= 10.0:
                    _VTS_IS_RECONNECTING = True
                    try:
                        if authed is None:
                            log_print("🔌 [VTS 心跳] 偵測到連線中斷，正在重新連線...")
                            async with vc.vts_lock:
                                await vts.connect(retries=2)
                        else:
                            log_print("🔑 [VTS 心跳] 連線正常但未通過認證，正在重新認證...")
                        # 認證不持鎖：申請新 token 可能要等使用者在 VTS 按允許（最長 30 秒），
                        # 持鎖會卡住表情/追蹤等其他協程；request() 靠 requestID 配對，可並行
                        await vts.request_authenticate()
                        _VTS_LAST_RECONNECT_TIME = time.time()
                        if vts.is_authenticated:
                            _VTS_LAST_AUTH_TIME = time.time()
                            log_print("✅ [系統通知] VTube Studio 重新連線與授權成功！身體控制權已恢復！")
                            spawn(vc.sync_expression_state(vts))
                        else:
                            log_print("⚠️ [VTS 心跳] 認證未成功，稍後自動重試")
                    except Exception as reconn_err:
                        _VTS_LAST_RECONNECT_TIME = time.time()
                        log_print(f"⚠️ [VTS 重連失敗]: {reconn_err}")
                    finally:
                        _VTS_IS_RECONNECTING = False
            else:
                # 連線正常：重置時間戳，確保下次真正斷線能立刻重連
                _VTS_LAST_AUTH_TIME = now

            #  守護追蹤主協程：若協程因任何異常退出，即刻自動重啟
            if host.GLOBAL_VTS_TRACKING_TASK is None or host.GLOBAL_VTS_TRACKING_TASK.done():
                host.GLOBAL_VTS_TRACKING_TASK = asyncio.create_task(ai_face_tracking_loop(vts))
        except Exception:
            _VTS_IS_RECONNECTING = False
