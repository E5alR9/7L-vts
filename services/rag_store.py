r"""
📚 RAG 向量知識庫 (RAG Store)
PROVIDER: LOCAL-chromadb（向量庫本地；嵌入走 services.embedder；見 docs/AI_SOURCES.md）

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


def _mode() -> str:
    m = (os.getenv("MODE") or "vtuber").strip().lower()
    return m if m in ("companion", "vtuber") else "vtuber"


COLLECTION = f"knowledge_{_mode()}"
LEGACY_COLLECTIONS = ["knowledge"]  # 舊混合庫：重建不相容，reset 時一併清除

_lock = threading.Lock()
_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    import chromadb
    os.makedirs(PERSIST_DIR, exist_ok=True)
    _client = chromadb.PersistentClient(path=PERSIST_DIR)
    try:
        _collection = _client.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        # 舊版 chromadb 不接受該 metadata 參數
        _collection = _client.get_or_create_collection(name=COLLECTION)
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
    from services.embedder import embed_one
    try:
        with _lock:
            col = _get_collection()
            if col.count() == 0:
                return []
            vec = embed_one(query)
            res = col.query(
                query_embeddings=[vec],
                n_results=max(1, min(k, 10)),
                include=["documents", "metadatas", "distances"],
            )
    except Exception as e:
        try:
            print(f"[RAG] 檢索失敗：{str(e)[:120]}")
        except Exception:
            pass
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


def rag_prompt_block(query: str, k: int = 3, min_score: float = None, budget_chars: int = 3500) -> str:
    """產生可直接拼進 system/user prompt 的【RAG 記憶檢索】段落；無命中回傳空字串。

    對標 groq-router 管線（api/chat.js retrieveRelevant＋ITPM 收斂器）：
    門檻 0.15＋最高分 60%（s > 0.15 and s >= best*0.6）→ 貪心塞 budget（上限 4 段）
    → 按時間序排回來（模型好讀）。budget 預設 3500 字，保 Groq 7K ITPM 內。
    可用環境變數 RAG_MIN_SCORE / RAG_BUDGET_CHARS 覆寫。
    """
    if min_score is None:
        try:
            min_score = float(os.getenv("RAG_MIN_SCORE") or "0.15")
        except Exception:
            min_score = 0.15
    try:
        budget_chars = int(os.getenv("RAG_BUDGET_CHARS") or str(budget_chars))
    except Exception:
        pass
    hits = search(query, k=max(k * 2, 8))
    if not hits:
        return ""
    best = max(h["score"] for h in hits)
    rel = [h for h in hits if h["score"] > 0.15 and h["score"] >= best * 0.6 and h["score"] >= min_score]
    # 同一段記憶常同時存在 unified_memory 與 dialogue_memory，去重避免 prompt 灌水
    seen = set()
    uniq = []
    for h in rel:
        key = re.sub(r"\s+", "", h["text"])[:80]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    picked = []
    used = 0
    for h in uniq:                                  # 貪心塞 budget，最多 4 段
        if len(picked) >= 4:
            break
        body = re.sub(r"\s+", " ", h["text"]).strip()[:600]
        if used + len(body) > budget_chars:
            continue
        used += len(body)
        picked.append(h)
    if not picked:
        return ""
    picked.sort(key=lambda h: str((h.get("metadata") or {}).get("timestamp", (h.get("metadata") or {}).get("time", ""))))  # 按時間序排回
    lines = []
    for i, h in enumerate(picked, 1):
        meta = h["metadata"] or {}
        src = meta.get("source", "")
        ts = meta.get("timestamp") or meta.get("time", "")
        
        tags = []
        if ts: tags.append(f"時間: {ts}")
        if src: tags.append(f"來源: {src}")
        tag_str = f"（{'，'.join(tags)}）" if tags else ""
        
        body = re.sub(r"\s+", " ", h["text"]).strip()[:300]
        lines.append(f"{i}. {body} {tag_str}")
    return (
        "【RAG 記憶檢索（與本題最相近的過往記憶，僅供參考、可引用但別生硬照唸）】\n"
        + "\n".join(lines)
    )


# ── Fold 摘要（對標 groq-router compressMessages）：舊記憶壓成一段，配摘要快取 ──
_SUMMARY_CACHE: Dict[str, str] = {}
_SUMMARY_CACHE_MAX = 128


async def fold_summary(texts: List[str], max_chars: int = 1200) -> str:
    """把舊記憶濃縮成一段摘要（Groq 快線；程序內快取；失敗回空字串不擋路）。
    PROVIDER: GROQ（見 docs/AI_SOURCES.md）"""
    import hashlib
    items = [re.sub(r"\s+", " ", str(t or "")).strip() for t in (texts or [])]
    items = [t for t in items if t]
    if not items:
        return ""
    key = hashlib.md5("\n".join(items).encode("utf-8")).hexdigest()[:16]
    if key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[key]
    contrato = "\n".join(items)[:20000]
    try:
        from core.groq_router import groq_chat
        resp = await groq_chat(
            [{"role": "user", "content": "把以下過往記憶濃縮成一段精簡摘要（保留人名、偏好、承诺與關鍵事件，不超过 600 字）：\n" + contrato}],
            timeout=15.0,
        )
        summary = (getattr(resp, "text", "") or "").strip()[:max_chars]
    except Exception:
        summary = ""
    if summary:
        if len(_SUMMARY_CACHE) >= _SUMMARY_CACHE_MAX:
            _SUMMARY_CACHE.pop(next(iter(_SUMMARY_CACHE)))
        _SUMMARY_CACHE[key] = summary
    return summary


def stats() -> dict:
    try:
        with _lock:
            col = _get_collection()
            return {"count": col.count(), "path": PERSIST_DIR, "collection": COLLECTION}
    except Exception as e:
        return {"count": -1, "error": str(e)[:120], "path": PERSIST_DIR}


def reset() -> int:
    """清空重來（僅測試/重建時使用）：清本模式庫＋舊混合庫。"""
    global _collection
    n = 0
    with _lock:
        import chromadb
        client = chromadb.PersistentClient(path=PERSIST_DIR)
        for name in [COLLECTION] + LEGACY_COLLECTIONS:
            try:
                client.delete_collection(name)
                n += 1
            except Exception:
                pass
        _collection = None
    return n


if __name__ == "__main__":
    import json
    print(json.dumps(stats(), ensure_ascii=False, indent=2))
