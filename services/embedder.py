r"""
🔤 RAG 嵌入器 (Embedder)

兩條路徑、同一介面：
  1. 本地 fastembed (ONNX, BAAI/bge-small-zh-v1.5 約 130MB)
     - 完全離線、零 API 額度、CPU 上約 5~15ms/句
  2. Gemini embedding (gemini-embedding-001)
     - 本地模型載入失敗時的備援（需 GEMINI_API_KEY）

介面：
    embed_texts(["...", "..."])  ->  List[List[float]]   (同步，內部有執行緒鎖)
    dim()                        ->  int                 (向量維度)

注意：查詢端與文件端必須使用同一個 embedder，維度才能對得上；
      rag_store 會把目前使用的 model 名稱寫進 collection metadata。
"""

import os
import threading
from typing import List, Optional

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"   # 中英混合、檔案小、夠用
GEMINI_EMBED_MODEL = os.getenv("RAG_GEMINI_EMBED_MODEL") or "gemini-embedding-001"

_lock = threading.Lock()
_local_model = None
_local_model_name: Optional[str] = None
_local_failed = False
_dim_cache: Optional[int] = None


def use_local() -> bool:
    """是否走本地嵌入（環境變數 RAG_EMBED_BACKEND=gemini 可強制走 API）"""
    return (os.getenv("RAG_EMBED_BACKEND") or "local").strip().lower() != "gemini"


def _get_local_model():
    global _local_model, _local_model_name, _local_failed
    if _local_model is not None:
        return _local_model
    if _local_failed:
        return None
    name = os.getenv("RAG_EMBED_MODEL") or DEFAULT_LOCAL_MODEL
    try:
        from fastembed import TextEmbedding
        _local_model = TextEmbedding(model_name=name)
        _local_model_name = name
        return _local_model
    except Exception as e:
        _local_failed = True
        try:
            print(f"[Embedder] 本地嵌入模型載入失敗（{name}）：{str(e)[:120]} ➔ 改走 Gemini 備援")
        except Exception:
            pass
        return None


def _embed_local(texts: List[str]) -> List[List[float]]:
    model = _get_local_model()
    if model is None:
        raise RuntimeError("本地嵌入不可用")
    return [[float(x) for x in vec] for vec in model.embed(texts)]


def _embed_gemini(texts: List[str]) -> List[List[float]]:
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEYS", "").split(",")[0].strip()
    if not key:
        raise RuntimeError("缺少 GEMINI_API_KEY，無法使用 Gemini embedding")
    from google import genai
    client = genai.Client(api_key=key)
    resp = client.models.embed_content(model=GEMINI_EMBED_MODEL, contents=texts)
    out = []
    for emb in resp.embeddings:
        vals = [float(x) for x in (emb.values if hasattr(emb, "values") else emb)]
        out.append(vals)
    return out


def embed_texts(texts: List[str]) -> List[List[float]]:
    """把文字批次轉成向量。本地失敗會自動改用 Gemini。"""
    if not texts:
        return []
    with _lock:
        if use_local():
            try:
                vecs = _embed_local(texts)
                if vecs:
                    return vecs
            except Exception as e:
                try:
                    print(f"[Embedder] 本地嵌入失敗，改走 Gemini：{str(e)[:120]}")
                except Exception:
                    pass
        return _embed_gemini(texts)


def embed_one(text: str) -> List[float]:
    vecs = embed_texts([text])
    return vecs[0] if vecs else []


def dim() -> int:
    """向量維度（用於檢查查詢端與文件端一致）"""
    global _dim_cache
    if _dim_cache:
        return _dim_cache
    v = embed_one("維度探測")
    _dim_cache = len(v)
    return _dim_cache


def backend_name() -> str:
    if use_local() and _get_local_model() is not None:
        return _local_model_name or "local"
    return GEMINI_EMBED_MODEL


if __name__ == "__main__":
    import json
    t0 = __import__("time").time()
    vs = embed_texts(["老爸早安", "今天的直播要開始囉"])
    print(json.dumps({
        "backend": backend_name(),
        "dim": len(vs[0]) if vs else 0,
        "cosine": round(sum(a * b for a, b in zip(vs[0], vs[1])), 4) if len(vs) == 2 else None,
        "elapsed_s": round(__import__("time").time() - t0, 2),
    }, ensure_ascii=False))
