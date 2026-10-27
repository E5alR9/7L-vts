import os
import json
import time
import asyncio
import websockets
import random
import re
from core.utils import log_print, log_swallowed

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
CURRENT_ACTIVE_EXP = None
CURRENT_ACTIVE_EXPS = set()  # 目前開在臉上的表情檔（小本本）
EXPRESSION_HOLD_SECONDS = 3.5  #  說完話後表情持續保留的秒數（保持自然情緒餘韻）

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
    "興奮": "星星眼.exp3.json",
    "兴奋": "星星眼.exp3.json",
    "激動": "星星眼.exp3.json",
    "激动": "星星眼.exp3.json",

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

    # 委屈 / 哭哭 
    "難過": "哭哭.exp3.json",
    "难过": "哭哭.exp3.json",
    "哭哭": "哭哭.exp3.json",
    "哭": "哭哭.exp3.json",
    "委屈": "哭哭.exp3.json",
    "sad": "哭哭.exp3.json",

    # 生氣 / 黑臉 / 翻白眼 / 傲慢 (僅限真正生氣)
    "生氣": "生气.exp3.json",
    "生气": "生气.exp3.json",
    "黑臉": "黑脸.exp3.json",
    "黑脸": "黑脸.exp3.json",
    "哼": "生气.exp3.json",
    "傲慢": "生气.exp3.json",
    "angry": "生气.exp3.json",
    "不爽": "生气.exp3.json",
    "憤怒": "生气.exp3.json",
    "愤怒": "生气.exp3.json",
    "陰沉": "黑脸.exp3.json",
    "阴沉": "黑脸.exp3.json",
    "黑化": "黑化.exp3.json",
    "病嬌": "黑化.exp3.json",
    "翻白眼": "黑脸.exp3.json",
    "白眼": "黑脸.exp3.json",
    "無語": "流汗.exp3.json",
    "无语": "流汗.exp3.json",
    "鄙視": "黑脸.exp3.json",
    "鄙视": "黑脸.exp3.json",

    # 暈暈 / 流汗 / 著急
    "暈暈": "晕晕.exp3.json",
    "暈": "晕晕.exp3.json",
    "流汗": "流汗.exp3.json",
    "汗": "流汗.exp3.json",
    "著急": "着急.exp3.json",
    "着急": "着急.exp3.json",
    "慌張": "着急.exp3.json",

    # 可愛附加
    "吐舌": "吐舌.exp3.json",
    "略": "吐舌.exp3.json",
    "調皮": "吐舌.exp3.json",   # 主腦常寫 [EXPRESSION: 調皮]（選單裡「調皮→吐舌」，她直接寫情境名）
    "比心": "比心.exp3.json",
    "愛你": "比心.exp3.json",
    "花花": "花花.exp3.json",
    "花": "花花.exp3.json",
    "問號": "问号.exp3.json",
    "问号": "问号.exp3.json",
    "疑惑": "问号.exp3.json",
    "思考": "问号.exp3.json",   # 主腦常寫 [EXPRESSION: 思考]，舊表沒有就整個被忽略
    "？": "问号.exp3.json",

    # 道具與動作 (麥克風、遊戲機、抬手、雙馬尾)
    "麥克風": "话筒.exp3.json",
    "麦克风": "话筒.exp3.json",
    "唱歌": "话筒.exp3.json",
    "話筒": "话筒.exp3.json",
    "打遊戲": "打游戏.exp3.json",
    "打游戏": "打游戏.exp3.json",
    "遊戲機": "打游戏.exp3.json",
    "手把": "打游戏.exp3.json",
    "雙馬尾": "双马尾.exp3.json",
    "双马尾": "双马尾.exp3.json",
    "抬手": "右抬手.exp3.json",
    "右抬手": "右抬手.exp3.json",
    "左抬手": "左抬手.exp3.json",
    "打招呼": "右抬手.exp3.json"
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
    """ 高效能非同步 VTube Studio WebSocket 通訊引擎（支援無阻塞極速參數注入與 RequestID 精準匹配）"""
    TOKEN_REQ_COOLDOWN = 60.0  # 申請 Token 失敗後的冷卻秒數

    def __init__(self, plugin_info=None, port=None):
        self.plugin_info = plugin_info or {
            "plugin_name": "7L_AI_VTuber",
            "developer": "e5_Studio",
            "authentication_token_path": "./vts_token.txt"
        }
        self.token_file = self.plugin_info.get("authentication_token_path", "./vts_token.txt")
        # 埠號：參數 > 8001；連不上時會自動掃 8001~8010（VTS 設定裡的 API 埠可能被改過）
        self.port = int(port or 8001)
        self.uri = f"ws://127.0.0.1:{self.port}"
        self.ws = None
        self.authentic_token = None
        self.pending_requests = {}
        self.reader_task = None
        self.req_counter = 0
        self.is_authenticated = False
        self._last_token_req = 0.0
        self._connect_lock = asyncio.Lock()

    def is_connected(self):
        if self.ws is None:
            return False
        if hasattr(self.ws, 'closed'):
            return not self.ws.closed
        return getattr(self.ws, 'close_code', None) is None

    async def connect(self, retries=5, retry_delay=2.0):
        # 序列化：VTS 重開時心跳和其他協程可能同時重連，會開出多條連線、互相取消 reader
        async with self._connect_lock:
            return await self._connect_locked(retries, retry_delay)

    async def _connect_locked(self, retries, retry_delay):
        self.is_authenticated = False
        for attempt in range(1, retries + 1):
            if self.is_connected():
                try: await self.ws.close()
                except Exception: pass
            # 先試上次成功/設定的埠，不行再掃其他常見埠
            ports = [self.port] + [p for p in range(8001, 8011) if p != self.port]
            last_err = None
            for p in ports:
                try:
                    ws = await websockets.connect(
                        f"ws://127.0.0.1:{p}",
                        max_size=10*1024*1024,
                        open_timeout=10.0 if p == self.port else 2.0,
                        ping_interval=20.0
                    )
                except Exception as e:
                    if p == self.port:
                        last_err = e
                    continue
                if p != self.port and not await self._looks_like_vts(ws):
                    try: await ws.close()
                    except Exception: pass
                    continue
                if p != self.port:
                    log_print(f"🔎 [VTS] Port {self.port} 連不上，在 Port {p} 找到 VTube Studio，改用這個埠")
                    self.port = p
                    self.uri = f"ws://127.0.0.1:{p}"
                self.ws = ws
                if self.reader_task and not self.reader_task.done():
                    self.reader_task.cancel()
                self.reader_task = asyncio.create_task(self._socket_reader(ws))
                return True
            if attempt < retries:
                await asyncio.sleep(retry_delay)
            else:
                raise ConnectionError(f"Cannot connect to VTube Studio at {self.uri} (也掃過 8001~8010): {last_err}")

    @staticmethod
    async def _looks_like_vts(ws) -> bool:
        """掃到的埠要先確認真的是 VTS API，避免連到別的 WebSocket 服務"""
        try:
            await ws.send(json.dumps({"apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                                      "requestID": "PortProbe", "messageType": "APIStateRequest", "data": {}}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            return resp.get("apiName") == "VTubeStudioPublicAPI"
        except Exception:
            return False

    async def _socket_reader(self, ws):
        try:
            async for raw_msg in ws:
                try:
                    data = json.loads(raw_msg)
                    req_id = data.get("requestID")
                    if req_id and req_id in self.pending_requests:
                        future = self.pending_requests.pop(req_id)
                        if not future.done():
                            future.set_result(data)
                except Exception:
                    log_swallowed()
        except asyncio.CancelledError:
            pass
        except Exception:
            log_swallowed()
        finally:
            # 連線斷了：還在等回應的請求立刻失敗，不必各自乾等 timeout。
            # 若 connect() 已換上新連線，pending 裡可能是新連線的請求，不能動。
            if self.ws is ws:
                code = getattr(ws, "close_code", None)
                reason = getattr(ws, "close_reason", "") or ""
                log_print(f"🔌 [VTS] 連線被關閉（code={code} {reason}）")
                self._fail_pending(ConnectionError("VTS 連線已中斷"))

    def _fail_pending(self, exc):
        pending, self.pending_requests = self.pending_requests, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(exc)

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

    async def request_authenticate_token(self, timeout: float = 30.0):
        """向 VTube Studio 申請新 Token。
         重要：request() 的 timeout 必須足夠長（預設 30 秒），讓使用者有時間在 VTS 視窗點允許！
        需要更久（例如手動領取腳本）可傳入 timeout=300。"""
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
        }, timeout=timeout)  #  讓使用者有時間在 VTS 視窗點允許
        token = resp.get("data", {}).get("authenticationToken")
        if token:
            self.authentic_token = token
            log_print("✅ [VTS 授權] 成功取得新 Token！")
        else:
            err_msg = resp.get("data", {}).get("message", str(resp))
            log_print(f"❌ [VTS 授權] Token 申請失敗: {err_msg}")
        return token

    async def _send_auth(self, req_id: str = "AuthReq") -> dict:
        resp = await self.request({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": req_id,
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": self.plugin_info.get("plugin_name", "7L_AI_VTuber"),
                "pluginDeveloper": self.plugin_info.get("developer", "e5_Studio"),
                "authenticationToken": self.authentic_token
            }
        })
        self.is_authenticated = bool(resp.get("data", {}).get("authenticated", False))
        return resp

    async def _claim_new_token(self) -> bool:
        """申請新 Token 並寫檔。冷卻 TOKEN_REQ_COOLDOWN 秒，避免心跳重連時每 10 秒狂彈授權視窗。"""
        now = time.time()
        if now - self._last_token_req < self.TOKEN_REQ_COOLDOWN:
            wait = int(self.TOKEN_REQ_COOLDOWN - (now - self._last_token_req))
            log_print(f"⏳ [VTS 授權] 上次申請 Token 未成功，{wait} 秒後再試（請到 VTS 視窗按【允許】）")
            return False
        self._last_token_req = now
        new_token = await self.request_authenticate_token()
        if not new_token:
            return False
        self._last_token_req = 0.0
        await self.write_token()
        return True

    async def request_authenticate(self):
        """使用現有 Token 向 VTS 認證；沒有 Token 或 Token 已失效就自動申請新的並寫回檔案。"""
        # 每次都重讀檔案：外部（如 claim_vts_token.py）換了 token，這裡會直接吃到新的
        await self.read_token()
        if not self.authentic_token:
            # 完全沒有 token，需要重新向 VTS 申請（會彈授權視窗）
            if not await self._claim_new_token():
                log_print("❌ [VTS 認證] 無法取得 Token，VTS 連線跳過。")
                return {}

        resp = await self._send_auth()
        if self.is_authenticated:
            log_print("✅ [VTS 認證] Token 驗證成功！")
            return resp

        # VTS 對失效/被撤銷的 token 回的是 AuthenticationResponse(authenticated=false, reason=...)，
        # 不是 APIError。只有 VTS 真的回了「認證失敗」才換 token；
        # 逾時（errorID=408、沒有 messageType）或 APIError 等其他情況保留舊 token，下次心跳再試。
        msg_type = resp.get("messageType", "")
        data = resp.get("data", {}) or {}
        if msg_type != "AuthenticationResponse":
            log_print(f"⚠️ [VTS 認證] authenticated=False（非 token 失效，可能是暫時性問題）: {resp}")
            return resp

        reason = data.get("reason") or data.get("message") or msg_type
        log_print(f"⚠️ [VTS 認證] Token 已失效（{reason}），正在自動申請新 Token...")
        self.authentic_token = None
        if not await self._claim_new_token():
            log_print("❌ [VTS 認證] 新 Token 申請未成功，請確認在 VTS 視窗點選了【允許】。")
            return resp

        resp2 = await self._send_auth("AuthReqRetry")
        if self.is_authenticated:
            log_print("✅ [VTS 認證] 重新認證成功！Token 已更新並儲存。")
        else:
            log_print(f"❌ [VTS 認證] 新 Token 認證仍失敗: {resp2}")
        return resp2

    async def request(self, req_dict: dict, timeout: float = 2.0) -> dict:
        # 不在這裡偷偷重連：舊版重連後沒重新認證，且多個協程會同時重連互相踩。
        # 斷線一律快速失敗，重連＋認證交給 vts_health_worker 統一處理。
        if not self.is_connected():
            raise ConnectionError("VTS 未連線（等待心跳自動重連）")

        # 每個請求配唯一 requestID：呼叫端常用固定 ID（如 "ActivateExpression"），
        # 同名請求逾時後晚到的回應會被錯配給下一個同名請求
        self.req_counter += 1
        req_id = f"{str(req_dict.get('requestID') or 'Req')[:40]}_{self.req_counter}"
        payload = dict(req_dict, requestID=req_id)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_requests[req_id] = future
        try:
            await self.ws.send(json.dumps(payload))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return {"errorID": 408, "message": f"Request {req_id} timed out"}
        finally:
            # 外層 wait_for 取消、send 失敗時也要清掉，避免 pending 越積越多
            self.pending_requests.pop(req_id, None)
            # send 途中斷線：reader 已把 future 標成 ConnectionError，send 又自己丟錯，
            # 這個 future 就沒人讀 → asyncio 會印「Future exception was never retrieved」
            if future.done() and not future.cancelled():
                future.exception()

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
    global CURRENT_VTS_MODEL_X, CURRENT_VTS_MODEL_Y, CURRENT_VTS_MODEL_SIZE
    target_vts = GLOBAL_VTS
    if not target_vts:
        return False
        
    clean_pos = str(target_pos or "").strip().lower()
    
    # 1. 檢查是否為重置/記憶指令
    if any(k == clean_pos or k in clean_pos for k in ["記住位置", "記住大小", "記住現在大小", "記住現在位置", "記錄位置", "記錄大小", "記住模型位置", "記住當前位置", "記住基準", "記錄基準", "save_pos", "save_position"]):
        await fetch_vts_base_model_pos(target_vts)
        return True

    #  每次位移/縮放前，即時向 VTS 查詢「當下真實模型位置與大小」
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
    *args, is_instinct: bool = False, **kwargs
) -> str:
    """統一 Live2D 模型走位與縮放控制器（支援絕對位置、預設位置與全向相對數值微調）
    is_instinct：本能腦的走位，跟表情一樣讓「意識優先 6 秒」（剛被主腦叫去走位就先別亂動）。"""
    global CURRENT_SPATIAL_LOCATION, LAST_CONSCIOUS_ACTION_TIME
    if not is_instinct:
        LAST_CONSCIOUS_ACTION_TIME = time.time()
    elif time.time() - LAST_CONSCIOUS_ACTION_TIME < 6.0:
        return "意識動作剛做完，本能走位先不動"
    clean_pos = str(position_name).strip()
    
    d_size = delta_size
    if d_size is None and (delta_w is not None or delta_h is not None):
        d_size = ((delta_w or 0) + (delta_h or 0)) / 25.0
        
    ok = await move_vts_spatial(
        target_pos=clean_pos,
        target_x=target_x, target_y=target_y,
        delta_x=delta_x, delta_y=delta_y,
        target_size=target_size,
        delta_size=d_size,
        scale_factor=scale_factor,
        duration=duration
    )
    if ok is False:
        log_print(f"⚠️ [模型走位] 沒移成「{clean_pos}」（VTS 沒連線或拒絕）")
        return f"沒移成「{clean_pos}」：VTube Studio 沒連線或拒絕了移動"
    CURRENT_SPATIAL_LOCATION = clean_pos
    log_print(f"🚀 [模型走位] 7L 模型平滑位移至: 「{clean_pos}」 (dx={delta_x}, dy={delta_y}, d_sz={d_size})")
    return f"已成功平滑移動模型至「{clean_pos}」！"

LAST_CONSCIOUS_ACTION_TIME = 0.0


def _vts_ok(resp) -> bool:
    """request() 逾時/VTS 報錯時是回錯誤 dict 而不是丟例外，要看內容才知道成功沒"""
    return isinstance(resp, dict) and "errorID" not in resp and resp.get("messageType") != "APIError"


def _vts_err(resp) -> str:
    if not isinstance(resp, dict):
        return str(resp)
    data = resp.get("data") or {}
    return str(data.get("message") or resp.get("message") or resp)


async def set_vts_expression(vts, exp_tag, is_instinct=False):
    global CURRENT_ACTIVE_EXP, shock_timer, wink_timer, wink_side, frown_timer, eye_roll_timer, is_tracking_mouse, LAST_CONSCIOUS_ACTION_TIME
    
    if not is_instinct:
        LAST_CONSCIOUS_ACTION_TIME = time.time()
    elif time.time() - LAST_CONSCIOUS_ACTION_TIME < 6.0:
        return  # 意識權限高於本能，短暫屏蔽本能動作

    try:
        clean_tag = str(exp_tag).strip().replace("[", "").replace("]", "").replace("EXPRESSION:", "").replace("EXPRESSION：", "").strip().lower()
        if clean_tag in ["_reset_", "_reset", "預設", "重置", "關閉", "正常", "恢復", "無", "取消", "reset", "default", "none", "close", "off", "0"]:
            # 先問 VTS 要 ground truth（2026-10-11：小本本不同步／重啟殘留／超時靜吞都會讓
            # reset 發個寂寞還撒謊說關掉了。直接問誰在臉上，逐個關，失敗大聲講。）
            to_close = {f for f in CURRENT_ACTIVE_EXPS if not _is_protected_exp(f)}
            try:
                st = await asyncio.wait_for(vts.request({
                    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "QueryExpState",
                    "messageType": "ExpressionStateRequest", "data": {"details": True}
                }), timeout=1.5)
                data = (st or {}).get("data", {}) or {}
                exprs = data.get("expressions", []) or []
                for e in exprs:
                    if isinstance(e, dict) and e.get("active"):
                        f = e.get("file") or e.get("expressionFile", "")
                        if f and str(f).endswith(".exp3.json") and not _is_protected_exp(f):
                            to_close.add(f)
            except Exception as qe:
                log_print(f"⚠️ [Live2D 表情] 查臉失敗（用小本本硬關）: {type(qe).__name__} {qe}".rstrip())  # 逾時的訊息是空字串，只印名字
            failed = []
            if to_close:
                async with vts_lock:
                    for exp in list(to_close):
                        try:
                            resp = await asyncio.wait_for(vts.request({
                                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ResetExp",
                                "messageType": "ExpressionActivationRequest", "data": {"expressionFile": exp, "active": False}
                            }), timeout=1.0)
                            if not _vts_ok(resp):
                                raise RuntimeError(_vts_err(resp))
                        except Exception as de:
                            failed.append(exp)
                            log_print(f"❌ [Live2D 表情] 關閉 {exp} 失敗: {de}")
                CURRENT_ACTIVE_EXPS.clear()
            elif CURRENT_ACTIVE_EXPS:
                CURRENT_ACTIVE_EXPS.clear()
            elif CURRENT_ACTIVE_EXP:
                async with vts_lock:
                    try:
                        await asyncio.wait_for(vts.request({
                            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ResetExp",
                            "messageType": "ExpressionActivationRequest", "data": {"expressionFile": CURRENT_ACTIVE_EXP, "active": False}
                        }), timeout=0.2)
                    except Exception: pass
            CURRENT_ACTIVE_EXP = None
            shock_timer = 0.0
            wink_timer = 0.0
            frown_timer = 0.0
            eye_roll_timer = 0.0
            is_tracking_mouse = True
            if failed:
                log_print(f"⚠️ [Live2D 表情] 重置未完成，還掛在臉上：{', '.join(failed)}（下次 reset 會重試）")
            elif to_close:
                log_print(f"✨ [Live2D 表情] 表情已重置為預設自然狀態（關閉 {len(to_close)} 個）")
            else:
                log_print("✨ [Live2D 表情] 臉上本來就乾淨，無需重置")
            return

        import re
        raw_tags = re.split(r'[+/, 、，&]+', clean_tag)
        
        target_filenames = set()
        action_hit = False  # 眨眼／驚訝／皺眉／白眼是動作不是表情檔，有觸發就不算「未知表情」
        for t in raw_tags:
            t = t.strip()
            if not t: continue
            
            # 處理特殊動作 (Wink, Shock, Frown)
            if any(k in t for k in ["wink", "眨眼", "單眼", "眨單眼", "单眼", "眨单眼"]):
                wink_timer = time.time() + 0.55
                wink_side = random.choice(["left", "right"])
                action_hit = True
                log_print(f"😉 [Live2D 動作] 觸發 Wink 單邊眨一下眼放電 ({wink_side})")
            if any(k in t for k in ["shock", "surprise", "驚訝", "惊讶", "震驚", "震惊", "驚", "惊", "瞳孔", "縮小", "缩小", "嚇到", "吓到", "恐懼", "害怕"]):
                shock_timer = time.time() + 4.0
                action_hit = True
                log_print("😱 [Live2D 動作] 觸發驚訝縮瞳瞪大雙眼與物理顫抖")
            if any(k in t for k in ["frown", "皺眉", "皱眉", "八字眉", "困擾", "困扰", "委屈"]):
                frown_timer = time.time() + 4.0
                action_hit = True
                log_print("🥺 [Live2D 動作] 觸發傲嬌八字皺眉/委屈表情")
            if any(k in t for k in ["eye_roll", "白眼", "翻白眼", "鄙視", "不屑", "無語"]):
                eye_roll_timer = time.time() + 3.0
                is_tracking_mouse = False
                action_hit = True
                log_print("🙄 [Live2D 動作] 觸發 7L 鄙視翻白眼")

            found = VTS_EXPRESSION_MAP.get(t)
            if not found:
                for k, v in VTS_EXPRESSION_MAP.items():
                    if k in t or t in k:
                        found = v
                        break
            if found:
                target_filenames.add(found)

        if not target_filenames:
            if not action_hit:
                log_print(f"⚠️ [Live2D 表情] 未知表情標籤：「{clean_tag}」，已忽略（請確認模型內有對應 .exp3.json 或在 VTS_EXPRESSION_MAP 新增映射）")
            return

        CURRENT_ACTIVE_EXP = list(target_filenames)[0] if target_filenames else None
        log_print(f"✨ [Live2D 表情] 成功啟動表情檔組合: 《{', '.join(target_filenames)}》 (標籤: {clean_tag})")
        
        async with vts_lock:
            # 疊加開啟：已開著的再下一次照樣送 active=True（VTS 冪等），不再反向關掉——
            # 舊 toggle 會讓連續兩句同表情時第二句把表情關掉。要關一律走 _RESET_。
            for exp_file in target_filenames:
                try:
                    resp = await asyncio.wait_for(vts.request({
                        "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "ActivateExpression",
                        "messageType": "ExpressionActivationRequest", "data": {"expressionFile": exp_file, "active": True}
                    }), timeout=1.0)
                    if _vts_ok(resp):
                        CURRENT_ACTIVE_EXPS.add(exp_file)
                    else:
                        log_print(f"⚠️ [Live2D 表情] 開啟 {exp_file} 失敗: {_vts_err(resp)}")
                except Exception as ae:
                    log_print(f"⚠️ [Live2D 表情] 開啟 {exp_file} 失敗: {ae}")
    except Exception as e:
        log_print(f"\n❌ [表情系統] 發生錯誤: {e}")

async def sync_expression_state(vts=None) -> set:
    """開機/重連同步（2026-10-11：VTS 重開時表情殘留臉上，小本本卻是空的→幽靈不同步）。

    問 VTS 臉上誰在，種回 CURRENT_ACTIVE_EXPS 並打出來。只同步不動臉
    （要清臉請調 set_vts_expression(_RESET_)）。查不到就保持現狀、不炸。
    回傳同步後的集合。
    """
    global CURRENT_ACTIVE_EXPS
    target = vts or globals().get("GLOBAL_VTS")
    if target is None:
        return set(CURRENT_ACTIVE_EXPS)
    try:
        st = await asyncio.wait_for(target.request({
            "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "SyncExpState",
            "messageType": "ExpressionStateRequest", "data": {"details": True}
        }), timeout=1.5)
        data = (st or {}).get("data", {}) or {}
        on_face = set()
        for e in data.get("expressions", []) or []:
            if isinstance(e, dict) and e.get("active"):
                f = e.get("file") or e.get("expressionFile", "")
                if f and str(f).endswith(".exp3.json") and not _is_protected_exp(f):
                    on_face.add(f)
        CURRENT_ACTIVE_EXPS = on_face
        if on_face:
            log_print(f"🔄 [Live2D 表情] 開機同步：臉上還掛著 {', '.join(sorted(on_face))}（已同步進小本本）")
        else:
            log_print("🔄 [Live2D 表情] 開機同步：臉上乾淨，與小本本一致")
        return set(on_face)
    except Exception as e:
        log_print(f"⚠️ [Live2D 表情] 開機同步查不到（保持現狀）: {e}")
        return set(CURRENT_ACTIVE_EXPS)


async def trigger_vts_expression(expression_name: str, is_instinct: bool = False) -> str:
    """切換 7L (Live2D 模型) 的臉部表情以表達情感或關閉表情。"""
    clean_name = expression_name.strip().replace("[", "").replace("]", "").replace("EXPRESSION:", "").replace("EXPRESSION：", "").strip()
    if not is_instinct:
        print(f"\n🎭 [Tool 調用] 7L 正在切換表情至: 「{clean_name}」")
    if GLOBAL_VTS:
        if clean_name in ["預設", "重置", "reset", "default", "_RESET_", "關閉", "正常", "恢復", "無", "取消", "none", "close", "off"]:
            await set_vts_expression(GLOBAL_VTS, "_RESET_", is_instinct=is_instinct)
            return "已成功關閉表情，恢復預設狀態。"
        else:
            await set_vts_expression(GLOBAL_VTS, clean_name, is_instinct=is_instinct)
            return f"已成功切換 Live2D 模型表情至：{clean_name}"
    return f"已記錄表情切換：{clean_name}"

# ── 受保護表情（2026-10-11：水印常駐，reset/sync 絕對不碰）──
# anti_watermark_worker 開機常駐開啟水印.exp3.json；之前 ground-truth reset
# 會把它當殘留關掉（開機每講完一句就滅一次）。這裡白名單，兩條路都跳過。
PROTECTED_EXPRESSIONS = frozenset({"水印.exp3.json"})


def _is_protected_exp(filename: str) -> bool:
    f = str(filename or "")
    return f in PROTECTED_EXPRESSIONS or "水印" in f or "watermark" in f.lower()


# ── 表情選單唯一真相（2026-10-10：主腦 responses.md＋本能 prompt 都從這裡自動帶，改一處即全改）──
# 名單只收「查表/計時器命中字」；tests/test_expression_dedupe.py 強制每個名都可落地。
EXPRESSION_MENU = (
    ("被誇/撒嬌", ("愛心", "比心")),
    ("崇拜/期待", ("星星眼",)),
    ("害羞/傲嬌", ("臉紅",)),
    ("難過/委屈", ("哭哭",)),
    ("開心", ("笑", "開心")),
    ("不爽/吐槽", ("生氣",)),
    ("傻眼", ("黑臉",)),
    ("病嬌", ("黑化",)),
    ("暈/醉", ("暈",)),
    ("尷尬", ("流汗",)),
    ("慌", ("著急",)),
    ("調皮", ("吐舌",)),
    ("夢幻", ("花花",)),
    ("疑惑", ("問號",)),
    ("嚇到", ("震驚",)),
    ("鄙視", ("翻白眼", "皺眉")),
    ("打招呼", ("抬手", "雙馬尾")),
    ("眨眼", ("WINK",)),
)
EXPRESSION_MENU_TEXT = "；".join(f"{ctx}→{'、'.join(names)}" for ctx, names in EXPRESSION_MENU)


# ── 表情去重查詢（2026-10-10：本能腦主做表情、NV 子代理備用）──
# 2026-10-17 起同檔再下一次＝維持開啟（不再 toggle 關掉）；NV 動手前查臉仍可省掉重複請求。
_RESET_WORDS = {"_reset_", "_reset", "預設", "重置", "關閉", "正常",
                "恢復", "無", "取消", "reset", "default", "none", "close", "off", "0"}
_WINK_WORDS = ("wink", "眨眼", "單眼", "眨單眼", "单眼", "眨单眼")
_SHOCK_WORDS = ("shock", "surprise", "驚訝", "惊讶", "震驚", "震惊", "瞳孔", "縮小", "缩小", "嚇到", "吓到", "恐懼", "害怕")
_FROWN_WORDS = ("frown", "皺眉", "皱眉", "八字眉", "困擾", "困扰", "委屈")
_EYEROLL_WORDS = ("eye_roll", "白眼", "翻白眼", "鄙視", "不屑", "無語")


def _expression_targets(expression_name: str):
    """把表情名正規化成 (files, timer_kind, is_reset)，與 set_vts_expression 同一套關鍵字。"""
    clean = str(expression_name or "").strip().replace("[", "").replace("]", "") \
        .replace("EXPRESSION:", "").replace("EXPRESSION：", "").strip().lower()
    if not clean:
        return set(), None, False
    if clean in _RESET_WORDS:
        return set(), None, True
    for kind, words in (("wink", _WINK_WORDS), ("shock", _SHOCK_WORDS),
                        ("frown", _FROWN_WORDS), ("eye_roll", _EYEROLL_WORDS)):
        if any(k in clean for k in words):
            return set(), kind, False
    found = VTS_EXPRESSION_MAP.get(clean)
    if not found:
        for k, v in VTS_EXPRESSION_MAP.items():
            if k in clean or clean in k:
                found = v
                break
    return ({found} if found else set()), None, False


def is_expression_active(expression_name: str) -> bool:
    """查臉：該表情是否已經在臉上（檔案在 CURRENT_ACTIVE_EXPS 或計時器未過期；重置＝臉上沒東西）。"""
    import time as _time
    files, kind, is_reset = _expression_targets(expression_name)
    now = _time.time()
    try:
        active = set(CURRENT_ACTIVE_EXPS)
    except NameError:
        active = set()
    if is_reset:
        timers = [globals().get(t, 0.0) for t in
                  ("wink_timer", "shock_timer", "frown_timer", "eye_roll_timer")]
        return (not active) and all((t or 0.0) <= now for t in timers)
    if kind:
        return (globals().get(f"{kind}_timer", 0.0) or 0.0) > now
    return bool(files) and bool(files & active)


async def wait_expression_active(expression_name: str, timeout: float = 2.5) -> bool:
    """等臉：輪詢 is_expression_active，最多等 timeout 秒（給本能腦一個 Live turn 的時間）。"""
    import asyncio as _aio
    import time as _time
    if is_expression_active(expression_name):
        return True
    deadline = _time.time() + max(0.0, timeout)
    while _time.time() < deadline:
        await _aio.sleep(0.3)
        if is_expression_active(expression_name):
            return True
    return False

# ── 高階動作封裝 (High-Level Actions) ───────────────────────────────────────────
async def trigger_wink(side=None, is_instinct=False):
    """觸發眨眼放電"""
    global wink_timer, wink_side, LAST_CONSCIOUS_ACTION_TIME
    if not is_instinct:
        LAST_CONSCIOUS_ACTION_TIME = time.time()
    elif time.time() - LAST_CONSCIOUS_ACTION_TIME < 6.0:
        return
    wink_timer = time.time() + 0.55
    wink_side = side or random.choice(["left", "right"])

async def trigger_shock(is_instinct=False):
    """觸發驚訝縮瞳與物理顫抖"""
    global shock_timer, LAST_CONSCIOUS_ACTION_TIME
    if not is_instinct:
        LAST_CONSCIOUS_ACTION_TIME = time.time()
    elif time.time() - LAST_CONSCIOUS_ACTION_TIME < 6.0:
        return
    shock_timer = time.time() + 4.0

async def trigger_frown(is_instinct=False):
    """觸發傲嬌八字皺眉/委屈表情"""
    global frown_timer, LAST_CONSCIOUS_ACTION_TIME
    if not is_instinct:
        LAST_CONSCIOUS_ACTION_TIME = time.time()
    elif time.time() - LAST_CONSCIOUS_ACTION_TIME < 6.0:
        return
    frown_timer = time.time() + 4.0

async def trigger_eye_roll(is_instinct=False):
    """觸發翻白眼"""
    global eye_roll_timer, is_tracking_mouse, LAST_CONSCIOUS_ACTION_TIME
    if not is_instinct:
        LAST_CONSCIOUS_ACTION_TIME = time.time()
    elif time.time() - LAST_CONSCIOUS_ACTION_TIME < 6.0:
        return
    is_tracking_mouse = False
    eye_roll_timer = time.time() + 3.8

async def set_tracking_mouse(enabled: bool):
    """開關滑鼠追蹤"""
    global is_tracking_mouse
    is_tracking_mouse = enabled

async def set_target_look(x: float, y: float):
    """設定視線目標座標"""
    global target_look_x, target_look_y, is_tracking_mouse
    is_tracking_mouse = False
    target_look_x = x
    target_look_y = y

async def update_vts_window_center(sw: float, sh: float):
    """自動偵測 VTube Studio 視窗位置，計算相對於螢幕中心的偏移量 (每 3 秒自動更新)"""
    import time
    now = time.time()
    
    # 避免短時間內重複偵測
    if hasattr(update_vts_window_center, "_last_update") and now - update_vts_window_center._last_update < 3.0:
        return getattr(update_vts_window_center, "_cx", 0.5), getattr(update_vts_window_center, "_cy", 0.5)

    found_win = None
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            if w.visible and w.width > 150 and w.height > 150:
                win_t = (w.title or "").lower()
                # 只認 "VTube Studio"：舊的 'vts' 會先撞到「vts_7L_test.py - Visual Studio Code」或終端機
                if 'vtube studio' in win_t:
                    found_win = (w.left + w.width / 2, w.top + w.height / 2)
                    break
    except Exception:
        pass
    
    if not found_win:
        try:
            import ctypes, ctypes.wintypes
            user32 = ctypes.windll.user32
            found = []
            def enum_cb(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, buf, 256)
                    title = (buf.value or "").lower()
                    if 'vtube studio' in title:
                        rect = ctypes.wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        if w > 150 and h > 150:
                            cx = (rect.left + rect.right) / 2
                            cy = (rect.top + rect.bottom) / 2
                            found.append((cx, cy))
                return 1
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
            if found:
                found_win = found[0]
        except Exception:
            pass

    if found_win:
        cx = found_win[0] / sw
        cy = found_win[1] / sh
    else:
        cx = getattr(update_vts_window_center, "_cx", 0.5)
        cy = getattr(update_vts_window_center, "_cy", 0.5)

    update_vts_window_center._cx = cx
    update_vts_window_center._cy = cy
    update_vts_window_center._last_update = now
    return cx, cy

