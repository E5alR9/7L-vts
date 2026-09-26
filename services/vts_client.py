import os
import json
import time
import asyncio
import websockets
import random
import re
from core.utils import log_print

# ── VTS 相關全域狀態與鎖 ────────────────────────────────────────────────────────
vts_lock = asyncio.Lock()
target_look_x = 0.0
target_look_y = 0.0
current_look_x = 0.0
current_look_y = 0.0
is_tracking_mouse = False
force_blink_trigger = 0
eye_roll_timer = 0.0
shock_timer = 0.0
wink_timer = 0.0
wink_side = "left"
frown_timer = 0.0

GLOBAL_VTS = None
MY_CONTROLLED_EXPS = ["黑脸.exp3.json", "爱心.exp3.json", "星星眼.exp3.json", "红脸.exp3.json"]
CURRENT_ACTIVE_EXP = None
EXPRESSION_HOLD_SECONDS = 3.5  # 🎭 說完話後表情持續保留的秒數（保持自然情緒餘韻）

VTS_EXPRESSION_MAP = {
    # 愛心 / 笑意
    "愛心": "爱心.exp3.json",      
    "爱心": "爱心.exp3.json",      
    "heart": "爱心.exp3.json",
    "love": "爱心.exp3.json",
    "喜歡": "爱心.exp3.json",
    "喜欢": "爱心.exp3.json",
    "開心": "爱心.exp3.json",
    "开心": "爱心.exp3.json",
    "happy": "爱心.exp3.json",
    "笑": "爱心.exp3.json",
    "微笑": "爱心.exp3.json",
    "大笑": "星星眼.exp3.json",

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

    # 委屈 / 哭哭 (改用紅臉，避免黑臉蓋住五官)
    "難過": "红脸.exp3.json",
    "难过": "红脸.exp3.json",
    "哭哭": "红脸.exp3.json",
    "哭": "红脸.exp3.json",
    "委屈": "红脸.exp3.json",
    "sad": "红脸.exp3.json",

    # 生氣 / 黑臉 / 翻白眼 / 傲慢 (僅限真正生氣黑化)
    "生氣": "黑脸.exp3.json",
    "生气": "黑脸.exp3.json",
    "黑臉": "黑脸.exp3.json",
    "黑脸": "黑脸.exp3.json",
    "哼": "黑脸.exp3.json",
    "傲慢": "黑脸.exp3.json",
    "angry": "黑脸.exp3.json",
    "不爽": "黑脸.exp3.json",
    "憤怒": "黑脸.exp3.json",
    "愤怒": "黑脸.exp3.json",
    "陰沉": "黑脸.exp3.json",
    "阴沉": "黑脸.exp3.json",
    "黑化": "黑脸.exp3.json",
    "翻白眼": "黑脸.exp3.json",
    "白眼": "黑脸.exp3.json",
    "無語": "黑脸.exp3.json",
    "无语": "黑脸.exp3.json",
    "鄙視": "黑脸.exp3.json",
    "鄙视": "黑脸.exp3.json"
}

CURRENT_SPATIAL_LOCATION = "center"
IS_AUTO_WANDER_ENABLED = True
LAST_WANDER_TIME = time.time()

BASE_VTS_MODEL_X = 0.65
BASE_VTS_MODEL_Y = -1.28
BASE_VTS_MODEL_SIZE = -54.8
CURRENT_VTS_MODEL_X = None
CURRENT_VTS_MODEL_Y = None
CURRENT_VTS_MODEL_SIZE = None


class RobustVTSClient:
    """🌟 高效能非同步 VTube Studio WebSocket 通訊引擎（支援無阻塞極速參數注入與 RequestID 精準匹配）"""
    def __init__(self, plugin_info=None, port=8001):
        self.plugin_info = plugin_info or {
            "plugin_name": "7L_AI_VTuber",
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
        self.is_authenticated = False
        for attempt in range(1, retries + 1):
            try:
                if self.is_connected():
                    try: await self.ws.close()
                    except Exception: pass
                self.ws = await websockets.connect(
                    self.uri, 
                    max_size=10*1024*1024,
                    open_timeout=10.0,
                    ping_interval=20.0
                )
                if self.reader_task and not self.reader_task.done():
                    self.reader_task.cancel()
                self.reader_task = asyncio.create_task(self._socket_reader())
                return True
            except Exception as e:
                if attempt < retries:
                    await asyncio.sleep(retry_delay)
                else:
                    raise ConnectionError(f"Cannot connect to VTube Studio at {self.uri}: {e}")

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
        """向 VTube Studio 申請新 Token。
        ⚠️ 重要：request() 的 timeout 必須足夠長（30秒），讓使用者有時間在 VTS 視窗點允許！"""
        log_print("⏳ [VTS 授權] 正在向 VTube Studio 申請新授權 Token...")
        log_print("   ➡️  請在 VTube Studio 視窗中找到「允許插件連線」彈窗並點選【允許】！")
        resp = await self.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "TokenReq",
            "messageType": "AuthenticationTokenRequest",
            "data": {
                "pluginName": self.plugin_info.get("plugin_name", "7L_AI_VTuber"),
                "pluginDeveloper": self.plugin_info.get("developer", "e5_Studio")
            }
        }, timeout=30.0)  # ⚠️ 必須用 30 秒！讓使用者有時間在 VTS 視窗點允許
        token = resp.get("data", {}).get("authenticationToken")
        if token:
            self.authentic_token = token
            log_print("✅ [VTS 授權] 成功取得新 Token！")
        else:
            err_msg = resp.get("data", {}).get("message", str(resp))
            log_print(f"❌ [VTS 授權] Token 申請失敗: {err_msg}")
        return token

    async def request_authenticate(self):
        """使用現有 Token 向 VTS 認證。若 Token 失效（APIError），才重申請。"""
        if not self.authentic_token:
            await self.read_token()
        if not self.authentic_token:
            # 完全沒有 token，需要重新向 VTS 申請（會彈授權視窗）
            new_token = await self.request_authenticate_token()
            if new_token:
                await self.write_token()
            else:
                log_print("❌ [VTS 認證] 無法取得 Token，VTS 連線跳過。")
                return {}

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

        if self.is_authenticated:
            log_print("✅ [VTS 認證] Token 驗證成功！")
            return resp

        # 認證失敗 → 只有在 VTS 明確回傳 APIError（token 被撤銷/無效）才重申請
        # 其他情況（如網路暫時超時）不刪 token，避免健康檢查重連時無限循環彈授權視窗
        msg_type = resp.get("messageType", "")
        err_id = resp.get("data", {}).get("errorID", -1)
        is_token_revoked = (msg_type == "APIError" and err_id in [50, 51, 52, 53, 54, 55, 0])

        if is_token_revoked:
            log_print(f"⚠️ [VTS 認證] Token 已被 VTS 撤銷（errorID={err_id}），正在清空並重新申請...")
            self.authentic_token = None
            try:
                if os.path.exists(self.token_file):
                    os.remove(self.token_file)
            except Exception:
                pass
            new_token = await self.request_authenticate_token()
            if new_token:
                await self.write_token()
                resp2 = await self.request({
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "AuthReqRetry",
                    "messageType": "AuthenticationRequest",
                    "data": {
                        "pluginName": self.plugin_info.get("plugin_name", "7L_AI_VTuber"),
                        "pluginDeveloper": self.plugin_info.get("developer", "e5_Studio"),
                        "authenticationToken": self.authentic_token
                    }
                })
                self.is_authenticated = resp2.get("data", {}).get("authenticated", False)
                if self.is_authenticated:
                    log_print("✅ [VTS 認證] 重新認證成功！Token 已更新並儲存。")
                else:
                    log_print("❌ [VTS 認證] 重新認證仍失敗，請確認在 VTS 視窗點選了【允許】。")
                return resp2
        else:
            log_print(f"⚠️ [VTS 認證] authenticated=False（非 token 撤銷，可能是暫時性問題）: {resp}")

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
        """極速非同步注入參數，不阻塞接收佇列"""
        if not self.is_connected():
            return
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
        except Exception:
            pass

    async def close(self):
        if self.reader_task:
            self.reader_task.cancel()
        if self.is_connected():
            try: await self.ws.close()
            except Exception: pass


async def fetch_vts_base_model_pos(vts=None):
    """主動從 VTube Studio 讀取並記錄老爸自訂之模型大小與座標基準（保證半身構圖與比例永不失真）"""
    global BASE_VTS_MODEL_X, BASE_VTS_MODEL_Y, BASE_VTS_MODEL_SIZE, CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE
    target_vts = vts or GLOBAL_VTS
    if not target_vts:
        return
    try:
        async with vts_lock:
            resp = await asyncio.wait_for(target_vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "GetModelInfoReq",
                "messageType": "CurrentModelRequest"
            }), timeout=1.5)
        pos = resp.get("data", {}).get("modelPosition", {})
        if pos and "size" in pos:
            x = float(pos.get("positionX", 0.65))
            y = float(pos.get("positionY", -1.28))
            sz = float(pos.get("size", -54.8))
            BASE_VTS_MODEL_Y = y
            BASE_VTS_MODEL_SIZE = sz
            if x > 0.1:
                BASE_VTS_MODEL_X = x
            CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE = x, y, sz
            log_print(f"📐 [VTS 模型記憶] 成功記錄老爸自訂基準大小: {sz:.1f}, 基準座標: ({x:.2f}, {y:.2f})")
    except Exception:
        pass

async def fetch_vts_current_model_pos(vts=None):
    """即時向 VTube Studio 查詢當前實際模型座標與大小（確保手動拖曳或縮放後，相對走位依然以「當下畫面狀態」為基準）"""
    global BASE_VTS_MODEL_X, BASE_VTS_MODEL_Y, BASE_VTS_MODEL_SIZE, CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE
    target_vts = vts or GLOBAL_VTS
    if not target_vts:
        return CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE
    try:
        async with vts_lock:
            resp = await asyncio.wait_for(target_vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "GetCurrentModelPosReq",
                "messageType": "CurrentModelRequest"
            }), timeout=1.0)
        pos = resp.get("data", {}).get("modelPosition", {})
        if pos and "size" in pos:
            x = float(pos.get("positionX", CURRENT_VTS_MODEL_X if CURRENT_VTS_MODEL_X is not None else 0.65))
            y = float(pos.get("positionY", CURRENT_VTS_MODEL_Y if CURRENT_VTS_MODEL_Y is not None else -1.28))
            sz = float(pos.get("size", CURRENT_VTS_MODEL_SIZE if CURRENT_VTS_MODEL_SIZE is not None else -54.8))
            CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE = x, y, sz
            if BASE_VTS_MODEL_SIZE is None:
                BASE_VTS_MODEL_X, BASE_VTS_MODEL_Y, BASE_VTS_MODEL_SIZE = x, y, sz
            return x, y, sz
    except Exception:
        pass
    return CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE

def parse_relative_spatial_offsets(clean_pos: str):
    """從走位字串中解析相對微調量 (dx, dy, d_sz)"""
    if not clean_pos:
        return None, None, None
        
    p = clean_pos.lower().strip()
    
    # 0. 排除純命名預設站位
    pure_named_presets = [
        "正中間", "置中", "中間", "center", 
        "鋼琴", "鋼琴旁", "鋼琴旁邊", "鋼琴前", "彈琴", "彈鋼琴", 
        "躲角落", "角落", "hide", 
        "原位", "回到原位", "原本位置", "復原", "home", "reset"
    ]
    if any(p == k for k in pure_named_presets):
        return None, None, None
    if re.match(r'^(?:去|到|站|在|移到|走至)?(?:正中間|中間|鋼琴旁|角落|原位|原本位置)$', p):
        return None, None, None

    dx, dy, d_sz = 0.0, 0.0, 0.0
    has_match = False
    
    m_dx = re.search(r'dx\s*[:=]\s*([+-]?\d+(?:\.\d+)?)', p)
    if m_dx:
        v = float(m_dx.group(1))
        dx += (v * 0.02 if abs(v) > 2 else v)
        has_match = True
        
    m_dy = re.search(r'dy\s*[:=]\s*([+-]?\d+(?:\.\d+)?)', p)
    if m_dy:
        v = float(m_dy.group(1))
        dy += (v * 0.02 if abs(v) > 2 else v)
        has_match = True

    m_dsz = re.search(r'(?:size|sz|d_?size)\s*[:=]\s*([+-]?\d+(?:\.\d+)?)', p)
    if m_dsz:
        v = float(m_dsz.group(1))
        d_sz += (v * 1.0 if abs(v) <= 50 else v * 0.5)
        has_match = True

    is_large_step = any(k in p for k in ["多一點", "多一些", "大一點", "一大步", "大幅", "再過去", "更過去", "多點", "再過去一點"])

    m_r = re.search(r'(?:往右|向右|右移|再右|右邊一點|往右邊|右側一點|再過去右邊|過去右邊|右邊多一點|再過去一點|過去一點)\s*(?:走|移|動|去)?\s*([+-]?\d+(?:\.\d+)?)?', p)
    if m_r and not m_dx:
        raw_num = m_r.group(1)
        if raw_num is not None:
            num = float(raw_num)
            dx += (num * 0.02 if abs(num) > 2 else num * 0.20 if abs(num) > 0 else (0.35 if is_large_step else 0.22))
        else:
            dx += (0.35 if is_large_step else 0.22)
        has_match = True

    m_l = re.search(r'(?:往左|向左|左移|再左|左邊一點|往左邊|左側一點|再過去左邊|過去左邊|左邊多一點)\s*(?:走|移|動|去)?\s*([+-]?\d+(?:\.\d+)?)?', p)
    if m_l and not m_dx:
        raw_num = m_l.group(1)
        if raw_num is not None:
            num = abs(float(raw_num))
            dx -= (num * 0.02 if num > 2 else num * 0.20 if num > 0 else (0.35 if is_large_step else 0.22))
        else:
            dx -= (0.35 if is_large_step else 0.22)
        has_match = True

    m_u = re.search(r'(?:往上|向上|上移|再上|上邊一點|往上邊|上方一點)\s*(?:走|移|動|去)?\s*([+-]?\d+(?:\.\d+)?)?', p)
    if m_u and not m_dy:
        raw_num = m_u.group(1)
        if raw_num is not None:
            num = float(raw_num)
            dy += (num * 0.02 if abs(num) > 2 else num * 0.15 if abs(num) > 0 else (0.25 if is_large_step else 0.15))
        else:
            dy += (0.25 if is_large_step else 0.15)
        has_match = True

    m_d = re.search(r'(?:往下|向下|下移|再下|下邊一點|往下邊|下方一點)\s*(?:走|移|動|去)?\s*([+-]?\d+(?:\.\d+)?)?', p)
    if m_d and not m_dy:
        raw_num = m_d.group(1)
        if raw_num is not None:
            num = abs(float(raw_num))
            dy -= (num * 0.02 if num > 2 else num * 0.15 if num > 0 else (0.25 if is_large_step else 0.15))
        else:
            dy -= (0.25 if is_large_step else 0.15)
        has_match = True

    m_big = re.search(r'(?:放大|變大|变大|大一點|大一点|靠近|貼近|贴近|zoom\s*in)\s*([+-]?\d+(?:\.\d+)?)?', p)
    if m_big and not m_dsz:
        raw_num = m_big.group(1)
        if raw_num is not None:
            num = float(raw_num)
            d_sz += (num * 1.0 if abs(num) > 0 else (16.0 if is_large_step else 10.0))
        else:
            d_sz += (16.0 if is_large_step else 10.0)
        has_match = True

    m_small = re.search(r'(?:縮小|缩小|變小|变小|小一點|小一点|遠離|远离|zoom\s*out)\s*([+-]?\d+(?:\.\d+)?)?', p)
    if m_small and not m_dsz:
        raw_num = m_small.group(1)
        if raw_num is not None:
            num = abs(float(raw_num))
            d_sz -= (num * 1.0 if num > 0 else (16.0 if is_large_step else 10.0))
        else:
            d_sz -= (16.0 if is_large_step else 10.0)
        has_match = True

    if has_match:
        return dx, dy, d_sz
    return None, None, None

async def move_vts_spatial(
    target_pos=None, 
    target_x=None, target_y=None, 
    delta_x=None, delta_y=None, 
    target_size=None, delta_size=None, scale_factor=None, 
    duration=2.0,
    *args, **kwargs
):
    """【VTS Live2D 模型平滑走位與縮放控制器】透過 WebSocket 官方 API 驅動 7L 在 VTS 畫布內平滑走位、相對微調與縮放"""
    global BASE_VTS_MODEL_X, BASE_VTS_MODEL_Y, BASE_VTS_MODEL_SIZE, CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE
    target_vts = GLOBAL_VTS
    if not target_vts:
        return False
        
    clean_pos = str(target_pos or "").strip().lower()
    
    # 1. 檢查是否為重置/記憶指令
    if any(k == clean_pos or k in clean_pos for k in ["記住位置", "記住大小", "記住現在大小", "記住現在位置", "記錄位置", "記錄大小", "記住模型位置", "記住當前位置", "記住基準", "記錄基準", "save_pos", "save_position"]):
        await fetch_vts_base_model_pos(target_vts)
        return True

    # 🎯 每次位移/縮放前，即時向 VTS 查詢「當下真實模型位置與大小」
    # 徹底解決老爸在 VTS 手動縮放或拖曳模型後，相對位移/放大縮小仍以舊紀錄為基準的突兀跳變問題
    await fetch_vts_current_model_pos(target_vts)
        
    base_x = BASE_VTS_MODEL_X if BASE_VTS_MODEL_X is not None else 0.65
    base_y = BASE_VTS_MODEL_Y if BASE_VTS_MODEL_Y is not None else -1.28
    base_sz = BASE_VTS_MODEL_SIZE if BASE_VTS_MODEL_SIZE is not None else -54.8
    
    cur_x = CURRENT_VTS_MODEL_X if CURRENT_VTS_MODEL_X is not None else base_x
    cur_y = CURRENT_VTS_MODEL_Y if CURRENT_VTS_MODEL_Y is not None else base_y
    cur_sz = CURRENT_VTS_MODEL_SIZE if CURRENT_VTS_MODEL_SIZE is not None else base_sz
    if clean_pos in ["復原", "原位", "原本位置", "回到原位", "home", "reset", "原本大小", "重設大小", "恢復大小", "再回去", "回去吧"]:
        dest_x = base_x
        dest_y = base_y
        dest_sz = base_sz
    elif scale_factor is not None and float(scale_factor) > 0:
        factor = float(scale_factor)
        dest_sz = base_sz + (factor - 1.0) * 35.0
        dest_x = cur_x
        dest_y = cur_y
    else:
        parsed_dx, parsed_dy, parsed_dsz = parse_relative_spatial_offsets(clean_pos)
        
        calc_dx = 0.0
        calc_dy = 0.0
        calc_dsz = 0.0
        
        if delta_x is not None:
            calc_dx += float(delta_x) * 0.008 if abs(delta_x) > 2 else float(delta_x)
        elif parsed_dx is not None:
            calc_dx += parsed_dx

        if delta_y is not None:
            calc_dy += float(delta_y) * 0.008 if abs(delta_y) > 2 else float(delta_y)
        elif parsed_dy is not None:
            calc_dy += parsed_dy

        min_allow_sz = base_sz - 16.0
        max_allow_sz = base_sz + 35.0

        if delta_size is not None:
            calc_dsz += float(delta_size)
        elif parsed_dsz is not None:
            calc_dsz += parsed_dsz

        if calc_dsz < 0 and cur_sz <= min_allow_sz:
            log_print(f"📐 [VTS 走位防護] 7L 當前體型已處於縮小安靜陪伴極限 (sz={cur_sz:.1f})，已阻斷重複縮小成螞蟻！")
            calc_dsz = 0.0
            dest_sz = cur_sz
        elif target_size is not None:
            dest_sz = float(target_size)
        elif calc_dsz != 0.0:
            dest_sz = cur_sz + calc_dsz
        else:
            dest_sz = cur_sz

        dest_sz = max(min_allow_sz, min(max_allow_sz, dest_sz))

        if calc_dx != 0.0 or calc_dy != 0.0:
            dest_x = cur_x + calc_dx
            dest_y = cur_y + calc_dy
        else:
            if any(k in clean_pos for k in ["鋼琴", "鋼琴旁", "鋼琴旁邊", "鋼琴前", "彈琴", "彈鋼琴"]):
                dest_x = cur_x
                dest_y = base_y + 0.06
                dest_sz = base_sz
            elif any(k in clean_pos for k in ["靠近", "貼近", "大模型", "大一點"]):
                dest_x = cur_x
                dest_y = cur_y + 0.08
                dest_sz = min(max_allow_sz, cur_sz + 12.0)
            elif any(k in clean_pos for k in ["遠離", "小模型", "小一點"]):
                dest_x = cur_x
                dest_y = cur_y - 0.08
                dest_sz = max(min_allow_sz, cur_sz - 12.0)
            elif any(k in clean_pos for k in ["躲角落", "角落", "hide"]):
                dest_x = 0.85
                dest_y = base_y - 0.15
                dest_sz = base_sz - 12.0
            elif any(k in clean_pos for k in ["center", "中間", "正中間", "置中", "過來中間"]):
                dest_x = 0.0 + random.uniform(-0.03, 0.03)
                dest_y = base_y + random.uniform(-0.03, 0.03)
                dest_sz = base_sz
            elif any(k in clean_pos for k in ["左邊", "左側", "left", "去左邊", "左下", "左下角", "左上", "左上角"]):
                dest_x = -0.65 + random.uniform(-0.04, 0.04)
                dest_y = base_y + random.uniform(-0.03, 0.03)
            elif any(k in clean_pos for k in ["右邊", "右側", "right", "去右邊", "右下", "右下角", "右上", "右上角"]):
                dest_x = 0.65 + random.uniform(-0.04, 0.04)
                dest_y = base_y + random.uniform(-0.03, 0.03)
            elif clean_pos in ["原位", "回到原位", "原本位置", "復原"]:
                dest_x = base_x
                dest_y = base_y
                dest_sz = base_sz
            elif clean_pos and clean_pos != "random":
                dest_x = cur_x
                dest_y = cur_y
            else:
                dest_x = random.choice([-0.65, -0.30, 0.0, 0.35, 0.65]) + random.uniform(-0.05, 0.05)
                dest_y = base_y + random.uniform(-0.06, 0.06)
                
    dest_sz = max(-95.0, min(80.0, dest_sz))
    dest_x = max(-1.8, min(1.8, dest_x))
    dest_y = max(-3.0, min(1.5, dest_y))
    
    if clean_pos in ["原位", "回到原位", "原本位置", "復原"] and abs(dest_x - cur_x) < 0.03 and abs(dest_y - cur_y) < 0.03 and abs(dest_sz - cur_sz) < 1.5:
        return True

    req_data = {
        "timeInSeconds": float(duration),
        "valuesAreRelativeToModel": False,
        "positionX": float(dest_x),
        "positionY": float(dest_y),
        "size": float(dest_sz),
        "rotation": 0.0
    }
    
    async with vts_lock:
        try:
            await asyncio.wait_for(target_vts.request({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "MoveModelReq",
                "messageType": "MoveModelRequest",
                "data": req_data
            }), timeout=1.5)
            CURRENT_VTS_MODEL_X = dest_x
            CURRENT_VTS_MODEL_Y = dest_y
            CURRENT_VTS_MODEL_SIZE = dest_sz
            return True
        except Exception:
            return False

async def apply_spatial_position(
    position_name: str = "random", 
    target_x: float = None, target_y: float = None, 
    delta_x: float = None, delta_y: float = None,
    target_size: float = None, delta_size: float = None,
    target_w: int = None, target_h: int = None,
    delta_w: int = None, delta_h: int = None,
    scale_factor: float = None,
    duration: float = 2.0,
    *args, **kwargs
) -> str:
    """統一 Live2D 模型走位與縮放控制器（支援絕對位置、預設位置與全向相對數值微調）"""
    global CURRENT_SPATIAL_LOCATION
    clean_pos = str(position_name).strip()
    
    d_size = delta_size
    if d_size is None and (delta_w is not None or delta_h is not None):
        d_size = ((delta_w or 0) + (delta_h or 0)) / 25.0
        
    await move_vts_spatial(
        target_pos=clean_pos,
        target_x=target_x, target_y=target_y,
        delta_x=delta_x, delta_y=delta_y,
        target_size=target_size,
        delta_size=d_size,
        scale_factor=scale_factor,
        duration=duration
    )
    CURRENT_SPATIAL_LOCATION = clean_pos
    log_print(f"🚀 [模型走位] 7L 模型平滑位移至: 「{clean_pos}」 (dx={delta_x}, dy={delta_y}, d_sz={d_size})")
    return f"已成功平滑移動模型至「{clean_pos}」！"

async def set_vts_expression(vts, exp_tag):
    global CURRENT_ACTIVE_EXP, shock_timer, wink_timer, wink_side, frown_timer
    try:
        clean_tag = str(exp_tag).strip().replace("[", "").replace("]", "").replace("EXPRESSION:", "").strip().lower()
        if clean_tag in ["_reset_", "_reset", "預設", "重置", "關閉", "正常", "恢復", "無", "取消", "reset", "default", "none", "close", "off", "0"]:
            CURRENT_ACTIVE_EXP = None
            shock_timer = 0.0
            wink_timer = 0.0
            frown_timer = 0.0
            log_print("✨ [Live2D 表情] 表情已重置為預設自然狀態")
            async with vts_lock:
                for exp_file in MY_CONTROLLED_EXPS:
                    try:
                        await asyncio.wait_for(vts.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ResetExp",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": exp_file, "active": False}
                        }), timeout=0.3)
                    except Exception: pass
            return

        if any(k in clean_tag for k in ["wink", "眨眼", "單眼", "眨單眼", "单眼", "眨单眼"]):
            wink_timer = time.time() + 0.55
            wink_side = random.choice(["left", "right"])
            log_print(f"😉 [Live2D 動作] 觸發 Wink 單邊眨一下眼放電 ({wink_side})")
            return
        elif any(k in clean_tag for k in ["shock", "surprise", "驚訝", "惊讶", "震驚", "震惊", "驚", "惊", "瞳孔", "縮小", "缩小", "嚇到", "吓到", "恐懼", "害怕"]):
            shock_timer = time.time() + 4.0
            log_print("😱 [Live2D 動作] 觸發驚訝縮瞳瞪大雙眼與物理顫抖")
            return
        elif any(k in clean_tag for k in ["frown", "皺眉", "皱眉", "八字眉", "困擾", "困扰", "委屈"]):
            frown_timer = time.time() + 4.0
            log_print("🥺 [Live2D 動作] 觸發傲嬌八字皺眉/委屈表情")
            return

        target_filename = VTS_EXPRESSION_MAP.get(clean_tag)
        if not target_filename:
            for k, v in VTS_EXPRESSION_MAP.items():
                if k in clean_tag or clean_tag in k:
                    target_filename = v
                    break
        if not target_filename:
            log_print(f"⚠️ [Live2D 表情] 未知表情標籤: 「{clean_tag}」，已忽略。")
            return

        CURRENT_ACTIVE_EXP = target_filename  
        log_print(f"✨ [Live2D 表情] 成功啟動表情檔: 《{target_filename}》 (標籤: {clean_tag})")
        async with vts_lock:
            for exp_file in MY_CONTROLLED_EXPS:
                if exp_file != target_filename:
                    try:
                        await asyncio.wait_for(vts.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "DeactivateExp",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": exp_file, "active": False}
                        }), timeout=0.3)
                    except Exception: pass

            try:
                await asyncio.wait_for(vts.request({
                    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ActivateExpression",
                    "messageType": "ExpressionActivationRequest", "data": {"expressionFile": target_filename, "active": True}
                }), timeout=0.5)
            except Exception: pass
    except Exception as e:
        log_print(f"\n❌ [表情系統] 發生錯誤: {e}")

async def trigger_vts_expression(expression_name: str) -> str:
    """切換 7L (Live2D 模型) 的臉部表情以表達情感或關閉表情。"""
    global GLOBAL_VTS
    clean_name = expression_name.strip().replace("[", "").replace("]", "").replace("EXPRESSION:", "").strip()
    print(f"\n🎭 [Tool 調用] 7L 正在切換表情至: 「{clean_name}」")
    if GLOBAL_VTS:
        if clean_name in ["預設", "重置", "reset", "default", "_RESET_", "關閉", "正常", "恢復", "無", "取消", "none", "close", "off"]:
            await set_vts_expression(GLOBAL_VTS, "_RESET_")
            return "已成功關閉表情，恢復預設狀態。"
        else:
            await set_vts_expression(GLOBAL_VTS, clean_name)
            return f"已成功切換 Live2D 模型表情至：{clean_name}"
    return f"已記錄表情切換：{clean_name}"
