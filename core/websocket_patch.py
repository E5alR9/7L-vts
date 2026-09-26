# -*- coding: utf-8 -*-
"""
WebSocket 相容層補丁 (core/websocket_patch.py)
--------------------------------------------------
🎯 目的：
   修復 websockets 12.x 與 Google GenAI SDK (google-genai) 在 Live API 雙工連線時的相容性問題。
   
🔍 問題成因：
   在 websockets < 13.0 (如 websockets 12.0) 中，websockets.asyncio 不存在，
   google-genai.live 會 fallback 至 websockets.client.connect (即 websockets.legacy.client.Connect)。
   但 google-genai 傳入的是 websockets 14+ 的參數 `additional_headers`，
   舊版 websockets 將未識別的關鍵字參數全數打包傳給 `asyncio.BaseEventLoop.create_connection()`，
   引發 `TypeError: BaseEventLoop.create_connection() got an unexpected keyword argument 'additional_headers'`。

🛠️ 解決方案：
   攔截 Connect.__init__，在傳入 create_connection 前將 `additional_headers` 平滑轉為 `extra_headers`，
   使 Live API 順利完成握手並帶上身分驗證 Header，同時 100% 相容 gradio_client、pyvts 等舊依賴。
"""

def apply_websocket_compatibility_patch():
    try:
        import websockets.legacy.client
        if getattr(websockets.legacy.client, "_genai_live_patched", False):
            return
        
        _orig_connect_init = websockets.legacy.client.Connect.__init__

        def _compat_connect_init(self, uri, *args, **kwargs):
            if "additional_headers" in kwargs:
                extra = kwargs.pop("additional_headers")
                if "extra_headers" in kwargs and kwargs["extra_headers"]:
                    if isinstance(kwargs["extra_headers"], dict) and isinstance(extra, dict):
                        kwargs["extra_headers"] = {**kwargs["extra_headers"], **extra}
                    elif isinstance(kwargs["extra_headers"], list) and isinstance(extra, list):
                        kwargs["extra_headers"] = kwargs["extra_headers"] + extra
                else:
                    kwargs["extra_headers"] = extra
            return _orig_connect_init(self, uri, *args, **kwargs)

        websockets.legacy.client.Connect.__init__ = _compat_connect_init
        websockets.legacy.client._genai_live_patched = True
    except Exception:
        pass

# 模組載入時自動執行補丁
apply_websocket_compatibility_patch()
