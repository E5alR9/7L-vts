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
                    return PureFirestoreDocumentSnapshot(False, {})
        except Exception:
            return PureFirestoreDocumentSnapshot(False, {})

    async def set(self, data: dict, merge: bool = False):
        try:
            headers = await self.client.get_headers()
            session = await self.client.get_session()
            fields = {k: val_to_firestore(v) for k, v in data.items()}
            mask = "&".join([f"updateMask.fieldPaths={k}" for k in fields.keys()]) if merge else ""
            req_url = f"{self.url}?{mask}" if mask else self.url
            async with session.patch(req_url, json={"fields": fields}, headers=headers, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                return resp.status
        except Exception:
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
