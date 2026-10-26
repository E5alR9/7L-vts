import os
import re
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

async def add_rag_memory(content: str, source: str = "dialogue", viewer: str = ""):
    """
    新增一筆 RAG 記憶，會自動計算向量，存入本地 ChromaDB 並同步至雲端 Firestore。
    viewer：熟客的留言帶觀眾名，之後可以只查他說過的。
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
    if viewer:
        metadata["viewer"] = viewer
    
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

async def search_rag_memory(query: str, top_k: int = 3, where: dict = None) -> list:
    """
    搜尋最相關的歷史記憶 (使用本地 ChromaDB)；where 只在 metadata 符合的裡面找（{"viewer": 名字}）
    """
    def _do_search():
        return rag_store.search(query, k=top_k, where=where)
        
    try:
        results = await asyncio.to_thread(_do_search)
        return results
    except Exception as e:
        print(f"⚠️ [RAG 檢索失敗]: {e}")
        return []

# ── 回話前查相關舊記憶（2026-10-26）：以前每句對話都存進向量庫，從來沒有人查 ──
# 實機量過（bge-small-zh 餘弦）：真的相關 0.64～0.89；但短句的「表面像」也有 0.60～0.69
# （「幫我數到三」↔「幫我想三個晚餐的選項」0.65、「有彈過匈牙利狂想曲」↔「他自己彈的」0.60）。
# 所以：很像（≥ 0.70）直接收；普通像（≥ 0.55）要跟這句話有共同的實字才收；招呼、「數到三」這種沒內容（實字不到 3 個）的話不查、
# 沒內容的記憶（「他自己彈的」）也不給；
# 跟這句話一模一樣的（老爸常說的招呼、剛剛才問的）不算記憶。
RELATED_MIN_SCORE = 0.55
RELATED_STRONG_SCORE = 0.70
RELATED_SKIP_RECENT_SEC = 3600  # 一小時內講的主腦自己還記得（最近對話本來就在她的上下文），不用再給
RELATED_MAX = 3
_TIME_PREFIX = re.compile(r"^\[\d\d:\d\d:\d\d\]\s*")        # 存進去的長相是「[HH:MM:SS] 誰對誰說: …」
_SPEAKER_PREFIX = re.compile(r"^\S+?對\S+?說[:：]\s*")
# 這些字組成的字對不算實詞（代名詞、助詞、繫詞、說想類動詞、數量詞）；這些詞先整個拿掉再切（時間詞、連接詞、稱呼）
_WEAK = set("我你妳他她它們的了嗎呢吧啊喔嘛呀啦是有在不很就也都要會能這那個什麼怎樣哪裡還再又跟和與把被給對說講想覺得到去來過著"
            "一二三幾多少請幫")
_STOP_WORDS = ["是不是", "有沒有", "之前", "以前", "剛剛", "剛才", "今天", "明天", "昨天", "現在", "等等", "一下", "上次", "下次", "這次",
               "每次", "時候", "然後", "因為", "所以", "可是", "但是", "如果", "應該", "真的", "好像", "已經", "可能", "自己", "大家",
               "主播", "老爸", "知道", "比較", "時間", "記得", "覺得", "可以"]
_STOP_RE = re.compile("|".join(sorted(_STOP_WORDS, key=len, reverse=True)))


def _body(text: str) -> str:
    return _SPEAKER_PREFIX.sub("", _TIME_PREFIX.sub("", (text or "").strip()))


def _norm(text: str) -> str:
    return re.sub(r"7L|[^\u4e00-\u9fffA-Za-z0-9]+", "", _body(text), flags=re.I).lower()


MIN_CONTENT = 3   # 一句話至少要有幾個實字才算有內容


def content_chars(text: str) -> set:
    """一句話裡的實字：中文每個不是虛字的字、英數整個詞（先拿掉時間詞、連接詞那些）。
    拿來看兩句話有沒有真的在講同一件事（「貓」「歌」這種單字名詞用字對切會切不出來，所以算字）。"""
    t = _STOP_RE.sub(" ", re.sub(r"7L", " ", _body(text), flags=re.I))
    out = set()
    for w in re.findall(r"[一-鿿]+|[A-Za-z0-9]+", t):
        if re.match(r"[A-Za-z0-9]+$", w):
            if len(w) >= 2:
                out.add(w.lower())
        else:
            out.update(ch for ch in w if ch not in _WEAK)
    return out


def _parse_ts(iso):
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except Exception:
        return None


def pick_related(hits, query: str, now=None, k=RELATED_MAX, min_score=RELATED_MIN_SCORE,
                 strong_score=RELATED_STRONG_SCORE, skip_recent_sec=RELATED_SKIP_RECENT_SEC,
                 min_query_content=MIN_CONTENT, need_overlap=True):
    """純函數：檢索結果 → 值得附給主腦的幾筆（規則見檔頭）。最後照時間排（好讀）。
    只查某個熟客說過的（hits 已經是他的）時，放寬：一個實字就查、不用共同實字（本來就是他的話）。"""
    qg = content_chars(query)
    if len(qg) < min_query_content:
        return []   # 「早安」「幫我數到三」：沒東西可查
    now = time.time() if now is None else now
    qn = _norm(query)
    out, seen = [], set()
    for h in sorted(hits or [], key=lambda x: -float(x.get("score") or 0)):
        score = float(h.get("score") or 0)
        if score < min_score:
            continue
        text = (h.get("text") or "").strip()
        ts = _parse_ts((h.get("metadata") or {}).get("timestamp"))
        if ts and now - ts < skip_recent_sec:
            continue
        key = _norm(text)[:80]
        if not key or key in seen or key == qn[:80] or score >= 0.95:
            continue   # 空的、重複的、跟這句一模一樣的
        hg = content_chars(text)
        if len(hg) < MIN_CONTENT or (need_overlap and score < strong_score and not (qg & hg)):
            continue   # 記憶本身沒內容（「他自己彈的」）、或只是表面像
        seen.add(key)
        out.append({"text": text, "ts": ts, "score": score})
        if len(out) >= k:
            break
    out.sort(key=lambda x: x["ts"] or 0)
    return out


def format_related(picked) -> str:
    """挑好的幾筆 → 接在紙條後面的一段；空的回空字串。"""
    if not picked:
        return ""
    lines = []
    for p in picked:
        when = datetime.fromtimestamp(p["ts"]).strftime("%m/%d %H:%M") if p.get("ts") else "以前"
        lines.append(f"- {when} {_TIME_PREFIX.sub('', p['text'])[:160]}")
    return "[相關的舊記憶（向量比對找的，可能不相關，自己判斷要不要提）：\n" + "\n".join(lines) + "]"


VIEWER_MIN_SCORE = 0.50     # 只在熟客自己的話裡找：本來就是他說的，門檻放低
VIEWER_LATEST = 2           # 找不到相關的，就給他最近說過的兩句


def viewer_where(viewer: str) -> dict:
    """向量庫裡「這位熟客說過的話」：他的留言（source=user）。觀眾檔片段（ingest_rag）也標了 viewer，不算。"""
    return {"$and": [{"viewer": viewer}, {"source": "user"}]}


def latest_viewer_lines(viewer: str, query: str = "", now=None, n=VIEWER_LATEST, skip_recent_sec=RELATED_SKIP_RECENT_SEC):
    """熟客最近說過的幾句（一小時內的、跟這句一樣的、招呼這種沒內容的、重複的都不算），新的在前。"""
    now = time.time() if now is None else now
    qn = _norm(query)[:80]
    rows = []
    for h in rag_store.get_where(viewer_where(viewer), limit=200):
        ts = _parse_ts((h.get("metadata") or {}).get("timestamp"))
        if ts and now - ts < skip_recent_sec:
            continue
        rows.append({"text": (h.get("text") or "").strip(), "ts": ts or 0.0, "score": 0.0})
    rows.sort(key=lambda x: -x["ts"])
    out, seen = [], set()
    for r in rows:
        key = _norm(r["text"])[:80]
        if not key or key in seen or key == qn or len(content_chars(r["text"])) < MIN_CONTENT:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= n:
            break
    return out


async def related_memories_block(query: str, k: int = RELATED_MAX, timeout: float = 1.5, viewers=()) -> str:
    """回話前查一次：search → pick → format。查不到、整段超過 timeout 秒、RAG 沒起來都回空字串，絕不擋住回話。
    viewers：這批留言裡的熟客，另外只在他們自己說過的話裡找（找不到相關的就給最近說過的兩句）。
    向量模型預載過的話一次約 5～10 毫秒（第一次要載模型，1 秒多，所以設時限）。"""
    query = (query or "").strip()[:300]

    async def _collect():
        got = []
        if query and len(content_chars(query)) >= MIN_CONTENT:
            hits = await search_rag_memory(query, top_k=max(k * 3, 8))
            got += pick_related(hits, query, k=k)
        for v in list(viewers or [])[:2]:
            mine = []
            if query and content_chars(query):
                vh = await search_rag_memory(query, top_k=6, where=viewer_where(v))
                mine = pick_related(vh, query, k=VIEWER_LATEST, min_score=VIEWER_MIN_SCORE,
                                    min_query_content=1, need_overlap=False)
            if not mine:
                mine = await asyncio.to_thread(latest_viewer_lines, v, query)
            got += mine
        return got

    try:
        picked = await asyncio.wait_for(_collect(), timeout)   # 整段一個時限（以前每次查各算 1.5 秒）
    except asyncio.TimeoutError:
        print("⚠️ [RAG 檢索] 超過時限，這次不附舊記憶")
        return ""
    except Exception as e:
        print(f"⚠️ [RAG 檢索失敗]: {e}")
        return ""
    seen, uniq = set(), []
    for p in picked:
        key = _norm(p["text"])[:80]
        if key and key not in seen:
            seen.add(key)
            uniq.append(p)
    uniq.sort(key=lambda x: x["ts"] or 0)
    return format_related(uniq[:k + VIEWER_LATEST * 2])

