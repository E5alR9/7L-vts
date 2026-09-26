r"""
📚 RAG 向量知識庫 (RAG Store)

- chromadb 持久化在 data/rag/chroma（原套件裝了 chromadb 卻完全沒用，這裡補上）
- 文件端與查詢端都走 services.embedder（本地 fastembed 主力 / Gemini 備援）
- 來源涵蓋：data/*.json 記憶 + knowledge/ 外部知識文件

介面：
    upsert_documents(ids, texts, metas)     # 建檔（scripts/ingest_rag.py 用）
    search(query, k=4) -> List[dict]        # 檢索：[{"text","score","metadata"}]
    search_multi(queries, k=4)              # 多查詢召回後去重
    rag_prompt_block(query, k=4) -> str     # 直接產生可注入 prompt 的片段
    stats() -> dict
"""

import os
import re
import threading
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSIST_DIR = os.path.join(BASE_DIR, "data", "rag", "chroma")
COLLECTION = "knowledge"

_lock = threading.Lock()
_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
    except ImportError:
        return None
    try:
        os.makedirs(PERSIST_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(path=PERSIST_DIR)
        try:
            _collection = _client.get_or_create_collection(
                name=COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            _collection = _client.get_or_create_collection(name=COLLECTION)
    except Exception:
        _collection = None
    return _collection


def upsert_documents(ids: List[str], texts: List[str], metas: Optional[List[dict]] = None) -> int:
    """嵌入並寫入（同 id 覆寫）。回傳實際寫入筆數。"""
    from services.embedder import embed_texts
    if not texts:
        return 0
    with _lock:
        col = _get_collection()
        vecs = embed_texts(texts)
        metas = metas or [{} for _ in texts]
        # chromadb metadata 只吃 bool/int/float/str
        safe_metas = []
        for m in metas:
            safe = {}
            for k, v in (m or {}).items():
                if isinstance(v, (bool, int, float, str)):
                    safe[k] = v
                elif v is not None:
                    safe[k] = str(v)[:500]
            safe_metas.append(safe)
        # 分批，避免單次過大
        step = 64
        for i in range(0, len(ids), step):
            col.upsert(
                ids=ids[i:i + step],
                documents=texts[i:i + step],
                embeddings=vecs[i:i + step],
                metadatas=safe_metas[i:i + step],
            )
        return len(ids)


def search(query: str, k: int = 4) -> List[Dict]:
    """向量相似度檢索，回傳依相關度排序的片段。"""
    if not query or not query.strip():
        return []
    try:
        with _lock:
            col = _get_collection()
            if col is None or col.count() == 0:
                return []
            from services.embedder import embed_one
            vec = embed_one(query)
            res = col.query(
                query_embeddings=[vec],
                n_results=max(1, min(k, 10)),
                include=["documents", "metadatas", "distances"],
            )
    except Exception:
        return []

    out = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        if not doc:
            continue
        # cosine distance -> 相似度 (0~1)
        score = 1.0 - float(dist)
        out.append({"text": doc, "score": round(score, 4), "metadata": meta or {}})
    return out


def search_multi(queries: List[str], k: int = 4) -> List[Dict]:
    """多組查詢 -> 合併去重（依分數取前 k 筆）"""
    seen: Dict[str, dict] = {}
    for q in queries:
        for hit in search(q, k=k):
            key = hit["text"][:120]
            if key not in seen or hit["score"] > seen[key]["score"]:
                seen[key] = hit
    return sorted(seen.values(), key=lambda x: -x["score"])[:k]


def rag_prompt_block(query: str, k: int = 3, min_score: float = None) -> str:
    """產生可直接拼進 system/user prompt 的【RAG 記憶檢索】段落；無命中回傳空字串。

    關於門檻：中文短句的 bge 向量 cosine 壓得很扁（實測相關 0.65 / 亂碼 0.66 /
    無關 0.48），單看分數無法區分相關性。因此這裡的 min_score 只用來擋掉
    明顯離群的遠端片段，真正的取捨靠「取前 k 筆 + 去重 + 截斷長度」。
    可用環境變數 RAG_MIN_SCORE 覆寫（預設 0.45）。
    """
    if min_score is None:
        try:
            min_score = float(os.getenv("RAG_MIN_SCORE") or "0.45")
        except Exception:
            min_score = 0.45
    hits = [h for h in search(query, k=max(k, k * 2)) if h["score"] >= min_score]
    # 同一段記憶常同時存在 unified_memory 與 dialogue_memory，去重避免 prompt 灌水
    seen = set()
    uniq = []
    for h in hits:
        key = re.sub(r"\s+", "", h["text"])[:80]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    hits = uniq[:k]
    if not hits:
        return ""
    lines = []
    for i, h in enumerate(hits, 1):
        src = (h["metadata"] or {}).get("source", "")
        src_tag = f"（來源: {src}）" if src else ""
        body = re.sub(r"\s+", " ", h["text"]).strip()[:300]
        lines.append(f"{i}. {body}{src_tag}")
    return (
        "【RAG 記憶檢索（與本題最相近的過往記憶，僅供參考、可引用但別生硬照唸）】\n"
        + "\n".join(lines)
    )


def stats() -> dict:
    try:
        with _lock:
            col = _get_collection()
            if col is None:
                return {"count": 0, "status": "chromadb_not_installed", "path": PERSIST_DIR}
            return {"count": col.count(), "path": PERSIST_DIR, "collection": COLLECTION}
    except Exception as e:
        return {"count": -1, "error": str(e)[:120], "path": PERSIST_DIR}


def reset() -> int:
    """清空重來（僅測試/重建時使用）"""
    global _collection
    with _lock:
        import chromadb
        client = chromadb.PersistentClient(path=PERSIST_DIR)
        try:
            client.delete_collection(COLLECTION)
            _collection = None
            return 1
        except Exception:
            return 0


if __name__ == "__main__":
    import json
    print(json.dumps(stats(), ensure_ascii=False, indent=2))
