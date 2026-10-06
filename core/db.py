import os
import json
import time
import asyncio
import aiohttp
import copy
from typing import Any, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from core.utils import log_print

QUOTA_EXCEEDED = False
OFFLINE_QUEUE_FILE = os.path.join("data", "firestore_offline_queue.json")

def _handle_quota_exceeded(collection_id: str, document_id: str, data: dict, merge: bool):
    global QUOTA_EXCEEDED
    if not QUOTA_EXCEEDED:
        log_print("⚠️ [Firestore 警告] 遇到 429 Quota Exceeded。寫入已暫存到本地，等明天配額重置後重新開機時再傳上雲端。")
        QUOTA_EXCEEDED = True
    
    try:
        os.makedirs(os.path.dirname(OFFLINE_QUEUE_FILE), exist_ok=True)
        if os.path.exists(OFFLINE_QUEUE_FILE):
            with open(OFFLINE_QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
        else:
            queue = {}
            
        if collection_id not in queue:
            queue[collection_id] = {}
            
        if merge and document_id in queue[collection_id]:
            queue[collection_id][document_id].update(data)
        else:
            queue[collection_id][document_id] = data
            
        with open(OFFLINE_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_print(f"❌ [Firestore 本地暫存錯誤]: {e}")

async def flush_offline_queue():
    global QUOTA_EXCEEDED
    if not os.path.exists(OFFLINE_QUEUE_FILE):
        return
        
    try:
        with open(OFFLINE_QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
            
        if not queue:
            return
            
        log_print("☁️ [Firestore 雲端同步] 發現先前因配額不足未上傳的本地資料，正在補傳上雲端...")
        
        success_count = 0
        quota_hit = False
        
        for col_id, docs in list(queue.items()):
            for doc_id, data in list(docs.items()):
                if quota_hit:
                    break
                if db is None:
                    return
                status = await db.collection(col_id).document(doc_id).set(data, merge=True)
                if status == 429:
                    quota_hit = True
                    break
                elif status in (200, 201):
                    success_count += 1
                    del queue[col_id][doc_id]
                
            if not queue[col_id]:
                del queue[col_id]
                
            if quota_hit:
                break
                
        with open(OFFLINE_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
            
        if quota_hit:
            QUOTA_EXCEEDED = True
            log_print("⚠️ [Firestore 雲端同步] 補傳中途再次遇到配額不足，剩餘資料將保留在本地。")
        elif success_count > 0:
            QUOTA_EXCEEDED = False
            log_print(f"✅ [Firestore 雲端同步] 成功將 {success_count} 筆暫存資料上傳至雲端！")
            
    except Exception as e:
        log_print(f"❌ [Firestore 補傳錯誤]: {e}")

def val_to_firestore(val: Any) -> dict:
    """將 Python 原生資料型態（str, int, dict, list 等）轉換為 Firestore REST API 的欄位格式"""
    if val is None: return {"nullValue": None}
    elif isinstance(val, bool): return {"booleanValue": val}
    elif isinstance(val, int): return {"integerValue": str(val)}
    elif isinstance(val, float): return {"doubleValue": val}
    elif isinstance(val, str): return {"stringValue": val}
    elif isinstance(val, (list, tuple)): return {"arrayValue": {"values": [val_to_firestore(x) for x in val]}}
    elif isinstance(val, dict): return {"mapValue": {"fields": {k: val_to_firestore(v) for k, v in val.items()}}}
    return {"stringValue": str(val)}

def firestore_to_val(val_dict: Any) -> Any:
    """將 Firestore REST API 回傳的欄位字典轉換回 Python 原生資料型態"""
    if not isinstance(val_dict, dict): return val_dict
    if "stringValue" in val_dict: return val_dict["stringValue"]
    elif "integerValue" in val_dict:
        try: return int(val_dict["integerValue"])
        except Exception: return val_dict["integerValue"]
    elif "doubleValue" in val_dict: return float(val_dict["doubleValue"])
    elif "booleanValue" in val_dict: return bool(val_dict["booleanValue"])
    elif "nullValue" in val_dict: return None
    elif "arrayValue" in val_dict: return [firestore_to_val(x) for x in val_dict["arrayValue"].get("values", [])]
    elif "mapValue" in val_dict: return {k: firestore_to_val(v) for k, v in val_dict["mapValue"].get("fields", {}).items()}
    elif "timestampValue" in val_dict: return val_dict["timestampValue"]
    return val_dict

class PureFirestoreDocumentSnapshot:
    def __init__(self, exists: bool, data: dict):
        self.exists = exists
        self._data = data
    def to_dict(self) -> Optional[dict]:
        return self._data if self.exists else None

class PureFirestoreDocumentRef:
    def __init__(self, client: "PureAsyncFirestoreClient", collection_id: str, document_id: str):
        self.client = client
        self.collection_id = collection_id
        self.document_id = document_id
        self.doc_path = f"projects/{client.project_id}/databases/(default)/documents/{collection_id}/{document_id}"
        self.url = f"https://firestore.googleapis.com/v1/{self.doc_path}"

    async def get(self) -> PureFirestoreDocumentSnapshot:
        try:
            headers = await self.client.get_headers()
            session = await self.client.get_session()
            async with session.get(self.url, headers=headers, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                if resp.status == 200:
                    raw_json = await resp.json()
                    fields = raw_json.get("fields", {})
                    data = {k: firestore_to_val(v) for k, v in fields.items()}
                    return PureFirestoreDocumentSnapshot(True, data)
                elif resp.status == 404:
                    return PureFirestoreDocumentSnapshot(False, {})
                else:
                    err_txt = await resp.text()
                    log_print(f"❌ [Firestore GET 錯誤] HTTP {resp.status}: {err_txt}")
                    return PureFirestoreDocumentSnapshot(False, {})
        except Exception as e:
            log_print(f"❌ [Firestore GET 異常]: {e}")
            return PureFirestoreDocumentSnapshot(False, {})

    async def set(self, data: dict, merge: bool = False):
        try:
            headers = await self.client.get_headers()
            session = await self.client.get_session()
            fields = {k: val_to_firestore(v) for k, v in data.items()}
            mask = "&".join([f"updateMask.fieldPaths={k}" for k in fields.keys()]) if merge else ""
            req_url = f"{self.url}?{mask}" if mask else self.url
            async with session.patch(req_url, json={"fields": fields}, headers=headers, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                if resp.status not in (200, 201):
                    if resp.status == 429:
                        _handle_quota_exceeded(self.collection_id, self.document_id, data, merge)
                    else:
                        err_txt = await resp.text()
                        log_print(f"❌ [Firestore REST API 錯誤] HTTP {resp.status}: {err_txt}")
                return resp.status
        except Exception as e:
            log_print(f"❌ [Firestore REST API 異常]: {e}")
            return 500

    async def delete(self):
        try:
            headers = await self.client.get_headers()
            session = await self.client.get_session()
            async with session.delete(self.url, headers=headers, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                return resp.status
        except Exception:
            return 500

class PureFirestoreCollectionRef:
    def __init__(self, client: "PureAsyncFirestoreClient", collection_id: str):
        self.client = client
        self.collection_id = collection_id

    def document(self, document_id: str) -> PureFirestoreDocumentRef:
        return PureFirestoreDocumentRef(self.client, self.collection_id, document_id)

class PureAsyncFirestoreClient:
    def __init__(self, cred_dict: dict):
        from google.oauth2 import service_account
        self.project_id = cred_dict.get("project_id", "lll-c6dea")
        self.sa_creds = service_account.Credentials.from_service_account_info(
            cred_dict,
            scopes=["https://www.googleapis.com/auth/datastore"]
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._token_expire_time: float = 0.0

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_headers(self) -> dict:
        now = time.time()
        if not self.sa_creds.valid or now >= self._token_expire_time - 60:
            import google.auth.transport.requests
            loop = asyncio.get_running_loop()
            req = google.auth.transport.requests.Request()
            await loop.run_in_executor(None, self.sa_creds.refresh, req)
            self._token_expire_time = now + 3500
        return {
            "Authorization": f"Bearer {self.sa_creds.token}",
            "Content-Type": "application/json"
        }

    def collection(self, collection_id: str) -> PureFirestoreCollectionRef:
        return PureFirestoreCollectionRef(self, collection_id)


# Singleton DB instance
db: Optional[PureAsyncFirestoreClient] = None

def init_firestore(cred_dict: dict) -> PureAsyncFirestoreClient:
    global db
    db = PureAsyncFirestoreClient(cred_dict)
    return db
