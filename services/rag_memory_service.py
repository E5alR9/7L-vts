import os
import time
import asyncio
from datetime import datetime
import uuid

# Firebase DB integration
import core.db as db_module
import services.rag_store as rag_store

_initialized = False

def init_rag(api_key: str):
    global _initialized
    # We do not strictly need the gemini api key here if embedder.py handles it,
    # but we will just pass it to the environment in case embedder.py needs fallback.
    os.environ["GEMINI_API_KEY"] = api_key
    _initialized = True
    print("🧠 [RAG 記憶中樞] 已準備完畢 (本地 ChromaDB + 雲端 Firestore 同步)")

async def add_rag_memory(content: str, source: str = "dialogue"):
    """
    新增一筆 RAG 記憶，會自動計算向量，存入本地 ChromaDB 並同步至雲端 Firestore
    """
    if not content or not content.strip():
        return
        
    timestamp = datetime.now().isoformat()
    # Generate unique ID
    mem_id = f"mem_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    
    metadata = {
        "source": source,
        "timestamp": timestamp
    }
    
    # 1. Update Local ChromaDB Store
    # We use asyncio.to_thread because upsert_documents is synchronous
    def _do_upsert():
        rag_store.upsert_documents(
            ids=[mem_id],
            texts=[content],
            metas=[metadata]
        )
    try:
        await asyncio.to_thread(_do_upsert)
    except Exception as e:
        print(f"⚠️ [RAG 本地寫入失敗]: {e}")
    
    # 2. Sync to Cloud Firestore (Without dense vectors to save space, just content & metadata)
    # We use firestore for exact match or general backup of RAG data.
    if db_module.db:
        try:
            cloud_record = {
                "id": mem_id,
                "content": content,
                "source": source,
                "timestamp": timestamp
            }
            # Add to firestore collection
            await db_module.db.collection("rag_memories").document(mem_id).set(cloud_record)
            # print(f"☁️ [RAG 雲端同步] 記憶已備份至 Firestore")
        except Exception as e:
            print(f"⚠️ [RAG 雲端同步失敗]: {e}")

async def search_rag_memory(query: str, top_k: int = 3) -> list:
    """
    搜尋最相關的歷史記憶 (使用本地 ChromaDB)
    """
    def _do_search():
        return rag_store.search(query, k=top_k)
        
    try:
        results = await asyncio.to_thread(_do_search)
        return results
    except Exception as e:
        print(f"⚠️ [RAG 檢索失敗]: {e}")
        return []

def clear_rag_memory():
    """清除所有 RAG 記憶 (本地)"""
    try:
        rag_store.reset()
        print("🗑️ [RAG 記憶庫] 本地向量資料庫已清空")
    except Exception as e:
        print(f"⚠️ [RAG 清空失敗]: {e}")
