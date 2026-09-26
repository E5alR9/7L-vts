# -*- coding: utf-8 -*-
"""
==============================================================================
🎭 VTube Studio 7L Live2D 動作與表情獨立測試工具 (test_vts_actions.py v4.0 正確版)
==============================================================================
說明：
  本工具採用 VTS 官方嚴格標準 Tracking Parameter 格式，排除了所有非法的 Live2D
  原生參數名稱（如 ParamAngleX / BodyAngleX），確保 VTS 100% 接收並驅動模型轉頭、眨眼、對嘴！
"""

import os
import sys
import time
import json
import math
import random
import asyncio
import websockets
import pyautogui

vts_lock = asyncio.Lock()

class RobustVTSClient:
    """高效能非同步 VTube Studio WebSocket 通訊引擎"""
    def __init__(self, plugin_info=None, port=8001):
        self.plugin_info = plugin_info or {
            "plugin_name": "7L_AI_VTuber_Tester",
            "developer": "e5_Studio",
            "authentication_token_path": "./vts_token.txt"
        }
        self.token_file = self.plugin_info.get("authentication_token_path", "./vts_token.txt")
        self.port = port
        self.uri = f"ws://127.0.0.1:{self.port}"
        self.ws = None
        self.authentic_token = None
        self.pending_requests = {}
        self.reader_task = None
        self.req_counter = 0
        self.is_authenticated = False

    def is_connected(self):
        if self.ws is None:
            return False
        if hasattr(self.ws, 'closed'):
            return not self.ws.closed
        return getattr(self.ws, 'close_code', None) is None

    async def connect(self, retries=5, retry_delay=2.0):
        for attempt in range(1, retries + 1):
            try:
                if self.is_connected():
                    try: await self.ws.close()
                    except Exception: pass
                print(f"🔌 正在連線至 VTube Studio ({self.uri}) [嘗試 {attempt}/{retries}]...")
                self.ws = await websockets.connect(
                    self.uri, 
                    max_size=10*1024*1024,
                    open_timeout=10.0,
                    ping_interval=20.0
                )
                if self.reader_task and not self.reader_task.done():
                    self.reader_task.cancel()
                self.reader_task = asyncio.create_task(self._socket_reader())
                print("✅ WebSocket 握手成功！")
                return True
            except Exception as e:
                print(f"⚠️ 連線失敗 ({e})，{retry_delay} 秒後重試...")
                if attempt < retries:
                    await asyncio.sleep(retry_delay)
                else:
                    raise ConnectionError(f"無法連線到 VTube Studio ({self.uri}): {e}\n請確認：\n1. VTube Studio 軟體已開啟\n2. VTS 設定 (齒輪) ->「Start API (允許插件連線)」已開啟且 Port 為 {self.port}")

    async def _socket_reader(self):
        try:
            async for raw_msg in self.ws:
                try:
                    data = json.loads(raw_msg)
                    req_id = data.get("requestID")
                    if req_id and req_id in self.pending_requests:
                        future = self.pending_requests.pop(req_id)
                        if not future.done():
                            future.set_result(data)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def read_token(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "r", encoding="utf-8") as f:
                    self.authentic_token = f.read().strip()
            except Exception:
                self.authentic_token = None
        return self.authentic_token

    async def write_token(self):
        if self.authentic_token:
            try:
                with open(self.token_file, "w", encoding="utf-8") as f:
                    f.write(self.authentic_token)
            except Exception:
                pass

    async def request_authenticate_token(self):
        print("🔑 正在向 VTube Studio 申請插件授權權限 (請在 VTS 畫面點選「允許/Allow」)...")
        resp = await self.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "TokenReq",
            "messageType": "AuthenticationTokenRequest",
            "data": {
                "pluginName": self.plugin_info.get("plugin_name", "7L_AI_VTuber"),
                "pluginDeveloper": self.plugin_info.get("developer", "e5_Studio")
            }
        }, timeout=30.0)
        token = resp.get("data", {}).get("authenticationToken")
        if token:
            self.authentic_token = token
            print("✅ 成功取得 VTS 授權 Token！")
        return token

    async def request_authenticate(self):
        if not self.authentic_token:
            await self.read_token()
        if not self.authentic_token:
            await self.request_authenticate_token()
            await self.write_token()

        resp = await self.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "AuthReq",
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": self.plugin_info.get("plugin_name", "7L_AI_VTuber"),
                "pluginDeveloper": self.plugin_info.get("developer", "e5_Studio"),
                "authenticationToken": self.authentic_token
            }
        })
        self.is_authenticated = resp.get("data", {}).get("authenticated", False)
        if not self.is_authenticated:
            print("⚠️ Token 認證未通過，正在重新請求授權...")
            await self.request_authenticate_token()
            await self.write_token()
            resp = await self.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "AuthReq2",
                "messageType": "AuthenticationRequest",
                "data": {
                    "pluginName": self.plugin_info.get("plugin_name", "7L_AI_VTuber"),
                    "pluginDeveloper": self.plugin_info.get("developer", "e5_Studio"),
                    "authenticationToken": self.authentic_token
                }
            })
            self.is_authenticated = resp.get("data", {}).get("authenticated", False)
        return resp

    async def request(self, req_dict: dict, timeout: float = 2.0) -> dict:
        if not self.is_connected():
            await self.connect()

        if "requestID" not in req_dict:
            self.req_counter += 1
            req_dict["requestID"] = f"Req_{self.req_counter}_{int(time.time()*1000)}"
        req_id = req_dict["requestID"]

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_requests[req_id] = future

        await self.ws.send(json.dumps(req_dict))
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.pending_requests.pop(req_id, None)
            return {"errorID": 408, "message": f"Request {req_id} timed out"}

    async def inject_parameters(self, param_values: list, face_found: bool = True, mode: str = "set"):
        """【VTS 官方標準參數注入】使用標準 faceFound 與 set 模式"""
        if not self.is_connected():
            return
        
        # 僅保留合法 VTS 輸入參數
        formatted_values = []
        for p in param_values:
            formatted_values.append({
                "id": p["id"],
                "value": float(p["value"]),
                "weight": float(p.get("weight", 1.0))
            })
            
        msg = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "StreamInject",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "faceFound": face_found,
                "mode": mode,
                "parameterValues": formatted_values
            }
        }
        try:
            await self.ws.send(json.dumps(msg))
        except Exception as e:
            print(f"\n❌ [注入參數異常]: {e}")

    async def close(self):
        if self.reader_task:
            self.reader_task.cancel()
        if self.is_connected():
            try: await self.ws.close()
            except Exception: pass


# 表情對照表
VTS_EXPRESSION_MAP = {
    # 愛心
    "愛心": "爱心.exp3.json",      
    "爱心": "爱心.exp3.json",      
    "heart": "爱心.exp3.json",
    "love": "爱心.exp3.json",
    "喜歡": "爱心.exp3.json",
    "喜欢": "爱心.exp3.json",
    "開心": "爱心.exp3.json",
    "开心": "爱心.exp3.json",
    "happy": "爱心.exp3.json",

    # 星星眼
    "星星": "星星眼.exp3.json",    
    "星星眼": "星星眼.exp3.json",
    "star": "星星眼.exp3.json",
    "sparkle": "星星眼.exp3.json",
    "崇拜": "星星眼.exp3.json",
    "期待": "星星眼.exp3.json",
    "亮晶晶": "星星眼.exp3.json",

    # 臉紅 / 紅臉
    "臉紅": "红脸.exp3.json",      
    "臉红": "红脸.exp3.json",
    "红脸": "红脸.exp3.json",
    "紅臉": "红脸.exp3.json",
    "shy": "红脸.exp3.json",
    "blush": "红脸.exp3.json",
    "傲嬌": "红脸.exp3.json",
    "傲娇": "红脸.exp3.json",
    "害羞": "红脸.exp3.json",
    "尷尬": "红脸.exp3.json",
    "尴尬": "红脸.exp3.json",

    # 生氣 / 黑臉
    "生氣": "黑脸.exp3.json",
    "生气": "黑脸.exp3.json",
    "黑臉": "黑脸.exp3.json",
    "黑脸": "黑脸.exp3.json",
    "angry": "黑脸.exp3.json",
    "不爽": "黑脸.exp3.json",
    "憤怒": "黑脸.exp3.json",
    "愤怒": "黑脸.exp3.json",
    "陰沉": "黑脸.exp3.json",
    "阴沉": "黑脸.exp3.json",
    "黑化": "黑脸.exp3.json",
    "難過": "黑脸.exp3.json",
    "难过": "黑脸.exp3.json",
    "sad": "黑脸.exp3.json",

    # 水印
    "水印": "水印.exp3.json"
}

BASE_MODEL_POS = {"x": 0.65, "y": -1.28, "size": -54.8}

async def fetch_current_model_info(vts):
    """讀取當前模型資訊與基準座標"""
    global BASE_MODEL_POS
    try:
        async with vts_lock:
            resp = await vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "GetModelInfoReq",
                "messageType": "CurrentModelRequest"
            })
        data = resp.get("data", {})
        model_name = data.get("modelName", "未知模型")
        pos = data.get("modelPosition", {})
        if pos:
            BASE_MODEL_POS["x"] = float(pos.get("positionX", 0.65))
            BASE_MODEL_POS["y"] = float(pos.get("positionY", -1.28))
            BASE_MODEL_POS["size"] = float(pos.get("size", -54.8))
        print(f"📦 偵測到當前模型: 【{model_name}】")
        print(f"📐 基準位置: X={BASE_MODEL_POS['x']:.2f}, Y={BASE_MODEL_POS['y']:.2f}, Size={BASE_MODEL_POS['size']:.1f}")
    except Exception as e:
        print(f"⚠️ 讀取模型資訊失敗: {e}")

async def set_expression(vts, exp_name):
    """設定表情"""
    if exp_name == "_RESET_":
        for file_name in set(VTS_EXPRESSION_MAP.values()):
            if "水印" in file_name: continue
            try:
                async with vts_lock:
                    await vts.request({
                        "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                        "requestID": "ResetExp",
                        "messageType": "ExpressionActivationRequest",
                        "data": {"expressionFile": file_name, "active": False}
                    })
            except Exception: pass
        print("🔄 已重置所有表情！")
        return

    target_file = VTS_EXPRESSION_MAP.get(exp_name, exp_name)
    print(f"🎭 觸發表情: {exp_name} ({target_file})")
    async with vts_lock:
        resp = await vts.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "SetExp",
            "messageType": "ExpressionActivationRequest",
            "data": {"expressionFile": target_file, "active": True}
        })
    print(f"   回應: {resp.get('messageType', 'OK')}")

async def move_model(vts, x=None, y=None, size=None, duration=1.5):
    """移動模型走位與縮放"""
    target_x = x if x is not None else BASE_MODEL_POS["x"]
    target_y = y if y is not None else BASE_MODEL_POS["y"]
    target_sz = size if size is not None else BASE_MODEL_POS["size"]
    print(f"🚶 走位移動至: X={target_x:.2f}, Y={target_y:.2f}, Size={target_sz:.1f} (耗時 {duration}s)")
    
    async with vts_lock:
        resp = await vts.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "MoveModelReq",
            "messageType": "MoveModelRequest",
            "data": {
                "timeInSeconds": float(duration),
                "valuesAreRelativeToModel": False,
                "positionX": float(target_x),
                "positionY": float(target_y),
                "size": float(target_sz),
                "rotation": 0.0
            }
        })
    return resp

# ────────────────────────────────────────────────────────
# 🎬 動作測試單元（全標準 VTS 參數 + 超絲滑阻尼）
# ────────────────────────────────────────────────────────

async def test_head_x_turn(vts, seconds=6.0):
    """測試 1-1：慢速平滑測試 FaceAngleX (左右轉頭)"""
    print(f"\n▶️ [測試 1-1] 【左右微幅溫和轉頭】 (左轉 -> 右轉 -> 慢慢回正) [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_x = 0.0
    while time.time() - start < seconds:
        target_x = math.sin(t * 1.2) * 8.0
        curr_x += (target_x - curr_x) * 0.14
        
        print(f"\r  👉 當前 FaceAngleX = {curr_x:+5.1f}° (左 <-> 右)", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": curr_x, "weight": 1.0},
            {"id": "FaceAngleY", "value": 0.0, "weight": 1.0},
            {"id": "FaceAngleZ", "value": 0.0, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
    
    # 溫柔回正
    for _ in range(20):
        curr_x += (0.0 - curr_x) * 0.18
        await vts.inject_parameters([{"id": "FaceAngleX", "value": curr_x, "weight": 1.0}])
        await asyncio.sleep(0.033)
    print("\n✅ 左右轉頭測試完畢！")

async def test_head_y_nod(vts, seconds=6.0):
    """測試 1-2：慢速平滑測試 FaceAngleY (上下點頭)"""
    print(f"\n▶️ [測試 1-2] 【上下微幅溫和點頭】 (微抬頭 -> 微低頭 -> 慢慢回正) [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_y = 0.0
    while time.time() - start < seconds:
        target_y = math.sin(t * 1.2) * 4.5
        curr_y += (target_y - curr_y) * 0.14
        
        print(f"\r  👉 當前 FaceAngleY = {curr_y:+5.1f}° (微低頭 <-> 微抬頭)", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": 0.0, "weight": 1.0},
            {"id": "FaceAngleY", "value": curr_y, "weight": 1.0},
            {"id": "FaceAngleZ", "value": 0.0, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    for _ in range(20):
        curr_y += (0.0 - curr_y) * 0.18
        await vts.inject_parameters([{"id": "FaceAngleY", "value": curr_y, "weight": 1.0}])
        await asyncio.sleep(0.033)
    print("\n✅ 上下點頭測試完畢！")

async def test_head_z_tilt(vts, seconds=6.0):
    """測試 1-3：慢速平滑測試 FaceAngleZ (可愛歪頭)"""
    print(f"\n▶️ [測試 1-3] 【可愛微幅歪頭】 (左微歪 -> 右微歪 -> 慢慢回正) [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_z = 0.0
    while time.time() - start < seconds:
        target_z = math.sin(t * 1.2) * 5.0
        curr_z += (target_z - curr_z) * 0.14
        
        print(f"\r  👉 當前 FaceAngleZ = {curr_z:+5.1f}° (左歪 <-> 右歪)", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": 0.0, "weight": 1.0},
            {"id": "FaceAngleY", "value": 0.0, "weight": 1.0},
            {"id": "FaceAngleZ", "value": curr_z, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    for _ in range(20):
        curr_z += (0.0 - curr_z) * 0.18
        await vts.inject_parameters([{"id": "FaceAngleZ", "value": curr_z, "weight": 1.0}])
        await asyncio.sleep(0.033)
    print("\n✅ 可愛歪頭測試完畢！")

async def test_head_angles_combined(vts, seconds=7.0):
    """測試 1-5：綜合三軸平滑自然轉動與呼吸"""
    print(f"\n▶️ [測試 1-5] 【綜合自然微幅靈動呼吸與轉頭】 [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_x, curr_y, curr_z = 0.0, 0.0, 0.0
    while time.time() - start < seconds:
        tgt_x = math.sin(t * 0.8) * 5.0
        tgt_y = math.cos(t * 0.6) * 2.8
        tgt_z = math.sin(t * 0.7) * 3.5
        
        curr_x += (tgt_x - curr_x) * 0.14
        curr_y += (tgt_y - curr_y) * 0.14
        curr_z += (tgt_z - curr_z) * 0.14
        
        print(f"\r  👉 X: {curr_x:+5.1f}° | Y: {curr_y:+5.1f}° | Z: {curr_z:+5.1f}°", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": curr_x, "weight": 1.0},
            {"id": "FaceAngleY", "value": curr_y, "weight": 1.0},
            {"id": "FaceAngleZ", "value": curr_z, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
            {"id": "MouthSmile", "value": 0.65, "weight": 1.0}
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 綜合轉頭測試完畢！")

async def test_eyes_and_blink(vts, seconds=6.0):
    """測試 2：眼睛視線環視與真實眨眼"""
    print(f"\n▶️ [測試 2] 【眼睛溫和環視與自然眨眼】 [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    eye_open = 1.0
    blink_timer = time.time() + 2.0
    is_blinking = False
    
    while time.time() - start < seconds:
        now = time.time()
        eye_x = math.sin(t * 1.5) * 0.65
        eye_y = math.cos(t * 1.2) * 0.50
        
        if not is_blinking and now > blink_timer:
            is_blinking = True
            blink_start = now
        
        if is_blinking:
            if now - blink_start < 0.14:
                eye_open = 0.0
            else:
                eye_open = 1.0
                is_blinking = False
                blink_timer = now + 2.5
        else:
            eye_open = 1.0
        
        print(f"\r  👉 視線 EyeX: {eye_x:+4.2f}, EyeY: {eye_y:+4.2f} | 狀態: {'[閉眼眨眼]' if eye_open==0.0 else '[睜眼]'}  ", end="", flush=True)
        await vts.inject_parameters([
            {"id": "EyeLeftX", "value": eye_x, "weight": 1.0},
            {"id": "EyeLeftY", "value": eye_y, "weight": 1.0},
            {"id": "EyeRightX", "value": eye_x, "weight": 1.0},
            {"id": "EyeRightY", "value": eye_y, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": eye_open, "weight": 1.0},
            {"id": "EyeOpenRight", "value": eye_open, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 眼睛動作測試完畢！")

async def test_eye_rolling(vts, seconds=3.0):
    """測試 2.5：招牌動作 - 快速靈動轉動眼珠環視 (LOOK: ROLL)"""
    print(f"\n▶️ [測試 2.5] 【招牌動作 - 快速靈動轉動眼珠環視】 (俐落 360° 圓周軌跡) [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    while time.time() - start < seconds:
        eye_x = math.sin(t * 6.0) * 0.75
        eye_y = math.cos(t * 6.0) * 0.60
        
        print(f"\r  👉 快速轉眼中... EyeX: {eye_x:+4.2f}, EyeY: {eye_y:+4.2f}  ", end="", flush=True)
        await vts.inject_parameters([
            {"id": "EyeLeftX", "value": eye_x, "weight": 1.0},
            {"id": "EyeLeftY", "value": eye_y, "weight": 1.0},
            {"id": "EyeRightX", "value": eye_x, "weight": 1.0},
            {"id": "EyeRightY", "value": eye_y, "weight": 1.0},
            {"id": "FaceAngleZ", "value": math.sin(t * 2.5) * 1.8, "weight": 1.0},
            {"id": "MouthSmile", "value": 0.65, "weight": 1.0}
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 轉眼珠招牌動作測試完畢！")

async def test_mouse_tracking(vts, seconds=8.0):
    """測試 3：平滑阻尼滑鼠游標追隨"""
    print(f"\n▶️ [測試 3] 【平滑滑鼠游標追隨】 (請移動滑鼠，頭部與視線會溫柔跟隨) [持續 {seconds} 秒]")
    start = time.time()
    sw, sh = pyautogui.size()
    curr_look_x, curr_look_y = 0.0, 0.0
    
    while time.time() - start < seconds:
        px, py = pyautogui.position()
        nx, ny = (px / sw) - 0.5, (py / sh) - 0.5
        tgt_look_x = nx * 26.0
        tgt_look_y = ny * -20.0
        
        curr_look_x += (tgt_look_x - curr_look_x) * 0.12
        curr_look_y += (tgt_look_y - curr_look_y) * 0.12
        eye_x = max(-0.8, min(0.8, curr_look_x / 26.0))
        eye_y = max(-0.8, min(0.8, curr_look_y / 20.0))
        
        print(f"\r  👉 視線跟隨: X={curr_look_x:+5.1f}°, Y={curr_look_y:+5.1f}°", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": curr_look_x, "weight": 1.0},
            {"id": "FaceAngleY", "value": curr_look_y, "weight": 1.0},
            {"id": "EyeLeftX", "value": eye_x, "weight": 1.0},
            {"id": "EyeLeftY", "value": eye_y, "weight": 1.0},
            {"id": "EyeRightX", "value": eye_x, "weight": 1.0},
            {"id": "EyeRightY", "value": eye_y, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
        ])
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 滑鼠追隨測試完畢！")

async def test_mouth_and_talking(vts, seconds=6.0):
    """測試 4：真實口型節奏對嘴與自然微笑"""
    print(f"\n▶️ [測試 4] 【自然對嘴開口與說話韻律】 [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_mouth = 0.0
    while time.time() - start < seconds:
        raw_mouth = abs(math.sin(t * 4.5)) * 0.65 + abs(math.sin(t * 9.0)) * 0.25
        curr_mouth += (raw_mouth - curr_mouth) * 0.28
        mouth_smile = 0.65 + math.sin(t * 1.5) * 0.15
        
        nod_y = math.sin(t * 1.8) * 1.2
        nod_x = math.cos(t * 1.2) * 1.5
        
        print(f"\r  👉 嘴巴開合 MouthOpen: {curr_mouth:.2f} | 微笑: {mouth_smile:.2f}  ", end="", flush=True)
        await vts.inject_parameters([
            {"id": "MouthOpen", "value": curr_mouth, "weight": 1.0},
            {"id": "MouthSmile", "value": mouth_smile, "weight": 1.0},
            {"id": "FaceAngleX", "value": nod_x, "weight": 1.0},
            {"id": "FaceAngleY", "value": nod_y, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 說話開嘴測試完畢！")

async def test_thinking_pose(vts, seconds=5.0):
    """測試 5：思考中可愛微幅歪頭姿態"""
    print(f"\n▶️ [測試 5] 【思考姿態】 (可愛微幅歪頭 5° + 視線斜上方看) [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_z = 0.0
    while time.time() - start < seconds:
        tgt_z = 5.0 + math.sin(t * 0.8) * 1.0
        curr_z += (tgt_z - curr_z) * 0.12
        eye_x = -0.35
        eye_y = 0.55
        
        print(f"\r  👉 思考微幅歪頭: {curr_z:+4.1f}° | 視線朝斜上方注視", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": -2.0, "weight": 1.0},
            {"id": "FaceAngleY", "value": 2.5, "weight": 1.0},
            {"id": "FaceAngleZ", "value": curr_z, "weight": 1.0},
            {"id": "EyeLeftX", "value": eye_x, "weight": 1.0},
            {"id": "EyeLeftY", "value": eye_y, "weight": 1.0},
            {"id": "EyeRightX", "value": eye_x, "weight": 1.0},
            {"id": "EyeRightY", "value": eye_y, "weight": 1.0},
            {"id": "MouthSmile", "value": 0.50, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 思考姿態測試完畢！")

async def test_piano_pose(vts, seconds=5.0):
    """測試 6：彈琴專注低頭與眼神看琴鍵姿態"""
    print(f"\n▶️ [測試 6] 【彈琴姿態】 (低頭看琴鍵 -15° + 眼神朝下 + 左右重心律動) [持續 {seconds} 秒]")
    start = time.time()
    t = 0.0
    curr_x = 0.0
    while time.time() - start < seconds:
        tgt_x = math.sin(t * 1.5) * 10.0
        curr_x += (tgt_x - curr_x) * 0.12
        
        print(f"\r  👉 低頭 -15.0° | 身體重心: {curr_x:+4.1f}° | 眼神看琴鍵", end="", flush=True)
        await vts.inject_parameters([
            {"id": "FaceAngleX", "value": curr_x, "weight": 1.0},
            {"id": "FaceAngleY", "value": -15.0, "weight": 1.0},
            {"id": "FaceAngleZ", "value": curr_x * 0.4, "weight": 1.0},
            {"id": "EyeLeftY", "value": -0.80, "weight": 1.0},
            {"id": "EyeRightY", "value": -0.80, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
        ])
        t += 0.04
        await asyncio.sleep(0.033)
        
    await reset_parameters(vts)
    print("\n✅ 彈琴姿態測試完畢！")

async def test_all_expressions(vts):
    """測試 7：依序切換所有表情"""
    print("\n▶️ [測試 7] 依序切換 4 大自訂表情 (exp3)...")
    exps = ["臉紅", "星星眼", "愛心", "生氣"]
    for exp in exps:
        await set_expression(vts, exp)
        await asyncio.sleep(2.0)
    await set_expression(vts, "_RESET_")
    print("✅ exp3 表情測試完畢！")

async def test_shock_and_pupil_shrink(vts, seconds=3.5):
    """測試 7.5：物理動力學縮小瞳孔 (EyeOpen=2.0) + 高頻恐懼細微顫抖"""
    print(f"\n▶️ [測試 7.5] 物理驅動縮小瞳孔 + 細微高頻恐懼顫抖 ({seconds} 秒)...")
    start = time.time()
    t = 0.0
    while time.time() - start < seconds:
        shiver_x = math.sin(t * 38.0) * 0.35
        shiver_y = math.sin(t * 34.0) * 0.30
        shiver_z = math.cos(t * 36.0) * 0.40
        shiver_eye = math.sin(t * 30.0) * 0.03

        await vts.inject_parameters([
            {"id": "EyeOpenLeft", "value": 2.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 2.0, "weight": 1.0},
            {"id": "Brows", "value": 1.0, "weight": 1.0},
            {"id": "MouthSmile", "value": 0.50, "weight": 1.0},
            {"id": "MouthOpen", "value": 0.0, "weight": 1.0},
            {"id": "FaceAngleX", "value": shiver_x, "weight": 1.0},
            {"id": "FaceAngleY", "value": shiver_y, "weight": 1.0},
            {"id": "FaceAngleZ", "value": shiver_z, "weight": 1.0},
            {"id": "EyeLeftX", "value": shiver_eye, "weight": 1.0},
            {"id": "EyeLeftY", "value": shiver_eye, "weight": 1.0},
            {"id": "EyeRightX", "value": shiver_eye, "weight": 1.0},
            {"id": "EyeRightY", "value": shiver_eye, "weight": 1.0}
        ])
        t += 0.04
        await asyncio.sleep(0.033)

    await vts.inject_parameters([
        {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
        {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
        {"id": "FaceAngleX", "value": 0.0, "weight": 1.0},
        {"id": "FaceAngleY", "value": 0.0, "weight": 1.0},
        {"id": "FaceAngleZ", "value": 0.0, "weight": 1.0},
        {"id": "EyeLeftX", "value": 0.0, "weight": 1.0},
        {"id": "EyeLeftY", "value": 0.0, "weight": 1.0},
        {"id": "EyeRightX", "value": 0.0, "weight": 1.0},
        {"id": "EyeRightY", "value": 0.0, "weight": 1.0},
        {"id": "Brows", "value": 0.55, "weight": 1.0},
        {"id": "MouthSmile", "value": 0.48, "weight": 1.0},
        {"id": "MouthOpen", "value": 0.0, "weight": 1.0}
    ])
    print("✅ 物理縮瞳與顫抖測試完畢！")

async def test_wink_expression(vts, seconds=3.5):
    """測試 7.6：俏皮單眼眨眼放電 (Wink) 動力學測試"""
    print(f"\n▶️ [測試 7.6] 俏皮單邊眨眼放電 (Wink) 測試 ({seconds} 秒)...")
    start = time.time()
    t = 0.0
    while time.time() - start < seconds:
        await vts.inject_parameters([
            {"id": "EyeOpenLeft", "value": 0.0, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
            {"id": "FaceAngleZ", "value": 4.5, "weight": 1.0},
            {"id": "MouthSmile", "value": 0.85, "weight": 1.0},
            {"id": "FaceAngleY", "value": 1.0, "weight": 1.0}
        ])
        t += 0.04
        await asyncio.sleep(0.033)
    await reset_parameters(vts)
    print("✅ Wink 單邊眨眼測試完畢！")

async def test_frown_expression(vts, seconds=4.0):
    """測試 7.7：超可愛傲嬌皺眉/八字眉困擾表情 (Brows=0.0 + 微嘟嘴/微撇嘴)"""
    print(f"\n▶️ [測試 7.7] 超可愛傲嬌皺眉 / 八字眉困擾表情 (Brows=0.0) 測試 ({seconds} 秒)...")
    start = time.time()
    t = 0.0
    while time.time() - start < seconds:
        await vts.inject_parameters([
            {"id": "Brows", "value": 0.0, "weight": 1.0},
            {"id": "EyeOpenLeft", "value": 0.95, "weight": 1.0},
            {"id": "EyeOpenRight", "value": 0.95, "weight": 1.0},
            {"id": "FaceAngleZ", "value": math.sin(t * 1.5) * 2.0, "weight": 1.0},
            {"id": "FaceAngleY", "value": -1.5, "weight": 1.0},
            {"id": "MouthSmile", "value": 0.25, "weight": 1.0},
            {"id": "MouthOpen", "value": 0.0, "weight": 1.0}
        ])
        t += 0.04
        await asyncio.sleep(0.033)
    await reset_parameters(vts)
    print("✅ 皺眉/八字眉表情測試完畢！")

async def test_spatial_movements(vts):
    """測試 8：走位與縮放測試"""
    print("\n▶️ [測試 8] 走位與縮放巡檢...")
    print(" 1. 走位到【左邊】...")
    await move_model(vts, x=-0.65, y=BASE_MODEL_POS["y"], duration=1.5)
    await asyncio.sleep(1.8)

    print(" 2. 走位到【右邊】...")
    await move_model(vts, x=0.65, y=BASE_MODEL_POS["y"], duration=1.5)
    await asyncio.sleep(1.8)

    print(" 3. 走位到【中間 + 放大貼近】...")
    await move_model(vts, x=0.0, y=BASE_MODEL_POS["y"] + 0.15, size=BASE_MODEL_POS["size"] + 15.0, duration=1.5)
    await asyncio.sleep(1.8)

    print(" 4. 鋼琴站位 (調高高度，完整露出上半身與彈琴姿態)...")
    await move_model(vts, x=-0.60, y=BASE_MODEL_POS["y"] + 0.06, size=BASE_MODEL_POS["size"], duration=1.5)
    await asyncio.sleep(1.8)

    print(" 5. 回到【基準原位】...")
    await move_model(vts, x=BASE_MODEL_POS["x"], y=BASE_MODEL_POS["y"], size=BASE_MODEL_POS["size"], duration=1.5)
    await asyncio.sleep(1.8)
    print("✅ 走位與縮放測試完畢！")

async def reset_parameters(vts):
    """溫和回正所有參數"""
    await vts.inject_parameters([
        {"id": "FaceAngleX", "value": 0.0, "weight": 1.0},
        {"id": "FaceAngleY", "value": 0.0, "weight": 1.0},
        {"id": "FaceAngleZ", "value": 0.0, "weight": 1.0},
        {"id": "EyeLeftX", "value": 0.0, "weight": 1.0},
        {"id": "EyeLeftY", "value": 0.0, "weight": 1.0},
        {"id": "EyeRightX", "value": 0.0, "weight": 1.0},
        {"id": "EyeRightY", "value": 0.0, "weight": 1.0},
        {"id": "EyeOpenLeft", "value": 1.0, "weight": 1.0},
        {"id": "EyeOpenRight", "value": 1.0, "weight": 1.0},
        {"id": "Brows", "value": 0.50, "weight": 1.0},
        {"id": "MouthOpen", "value": 0.0, "weight": 1.0},
        {"id": "MouthSmile", "value": 0.50, "weight": 1.0},
    ])

# ────────────────────────────────────────────────────────
# 🌟 主選單與互動迴圈
# ────────────────────────────────────────────────────────
async def main():
    print("=========================================================")
    print("🎭 7L Live2D / VTube Studio 動作與表情獨立測試工具 (v4.0)")
    print("=========================================================")
    
    plugin_info = {"plugin_name": "7L_AI_VTuber", "developer": "e5_Studio", "authentication_token_path": "./vts_token.txt"}
    vts = RobustVTSClient(plugin_info=plugin_info)
    try:
        await vts.connect(retries=5, retry_delay=2.0)
        await vts.request_authenticate()
        print("✅ 成功連線並認證 VTube Studio！\n")
        await fetch_current_model_info(vts)
    except Exception as e:
        print(f"\n❌ 連線失敗: {e}")
        return

    menu = """
---------------------------------------------------------
👉 請輸入數字選擇要單獨測試的項目：
 [1] 🎯 頭部單軸測試 (絲滑溫和速度)
   [11] 單獨測試 左右轉頭 (FaceAngleX)
   [12] 單獨測試 上下點頭 (FaceAngleY)
   [13] 單獨測試 可愛歪頭 (FaceAngleZ)
   [15] 綜合三軸自然轉動與呼吸

 [2] 眼睛視線與眨眼 (溫柔環視 / 自然閉眼眨眼)
 [25] 招牌動作：靈動轉動眼珠環視 (Signature Eye-Rolling [LOOK: ROLL])
 [3] 平滑滑鼠游標追蹤 (Mouse Follow)
 [4] 說話對嘴開合與笑容 (Mouth Lip Sync & Smile)
 [5] 思考狀態可愛歪頭姿態 (Thinking Pose - 20° Tilt)
 [6] 鋼琴演奏專注低頭眼神姿態 (Piano Playing Pose)
 [7] 四大表情依序切換 (Expressions: 臉紅/星星/愛心/生氣)
 [75] 瞳孔縮小 / 震驚姿態動力學 (Dynamic Pupil Shrink & Shock)
 [76] 俏皮單邊眨眼放電 (Cute Single-Eye Wink)
 [77] 傲嬌皺眉 / 八字眉困擾表情 (Furrowed Brows / Frown [Brows=-1.0])
 [8] 走位移動與大小縮放 (Spatial Movement & Zoom)
 [9] 🚀 一鍵自動全動作大巡檢 (Run Full Showcase)
 [0] 退出程式
---------------------------------------------------------
"""
    while True:
        print(menu)
        try:
            choice = await asyncio.to_thread(input, "請輸入選項: ")
            choice = choice.strip().upper()
            
            if choice in ["1", "15"]:
                await test_head_angles_combined(vts, seconds=7.0)
            elif choice == "11":
                await test_head_x_turn(vts, seconds=6.0)
            elif choice == "12":
                await test_head_y_nod(vts, seconds=6.0)
            elif choice == "13":
                await test_head_z_tilt(vts, seconds=6.0)
            elif choice == "2":
                await test_eyes_and_blink(vts, seconds=6.0)
            elif choice in ["25", "2.5", "ROLL"]:
                await test_eye_rolling(vts, seconds=4.5)
            elif choice == "3":
                await test_mouse_tracking(vts, seconds=8.0)
            elif choice == "4":
                await test_mouth_and_talking(vts, seconds=6.0)
            elif choice == "5":
                await test_thinking_pose(vts, seconds=6.0)
            elif choice == "6":
                await test_piano_pose(vts, seconds=6.0)
            elif choice == "7":
                await test_all_expressions(vts)
            elif choice in ["75", "7.5", "SHOCK"]:
                await test_shock_and_pupil_shrink(vts, seconds=4.5)
            elif choice in ["76", "7.6", "WINK"]:
                await test_wink_expression(vts, seconds=3.5)
            elif choice in ["77", "7.7", "FROWN"]:
                await test_frown_expression(vts, seconds=4.0)
            elif choice == "8":
                await test_spatial_movements(vts)
            elif choice == "9":
                print("\n🚀 開始執行全動作完整巡檢...")
                await test_head_x_turn(vts, seconds=3.5)
                await test_head_y_nod(vts, seconds=3.5)
                await test_head_z_tilt(vts, seconds=3.5)
                await test_eyes_and_blink(vts, seconds=4.0)
                await test_eye_rolling(vts, seconds=3.5)
                await test_mouth_and_talking(vts, seconds=4.0)
                await test_thinking_pose(vts, seconds=4.0)
                await test_piano_pose(vts, seconds=4.0)
                await test_all_expressions(vts)
                await test_shock_and_pupil_shrink(vts, seconds=3.5)
                await test_wink_expression(vts, seconds=3.0)
                await test_frown_expression(vts, seconds=3.5)
                await test_spatial_movements(vts)
                print("\n🎉 全動作完整巡檢完畢！")
            elif choice == "0":
                print("👋 正在退出測試工具...")
                await reset_parameters(vts)
                await vts.close()
                break
            else:
                print("⚠️ 無效的選項，請重新輸入！")
        except (KeyboardInterrupt, EOFError):
            print("\n👋 收到中斷信號，退出...")
            break
        except Exception as e:
            print(f"\n❌ 執行動作時發生錯誤: {e}")

if __name__ == "__main__":
    asyncio.run(main())
