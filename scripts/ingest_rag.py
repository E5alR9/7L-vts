# -*- coding: utf-8 -*-
r"""
🧺 RAG 建檔腳本 (Ingest)

把兩類來源切 chunk、嵌入、寫進 data/rag/chroma：
  1. data/*.json 的既有記憶
     - unified_memory / dialogue_memory / thought_memory（逐筆 content）
     - cloud_knowledge_local（persona、meme、規則、few-shot…攤平）
     - viewer_profiles_local（每位觀眾一份檔案）
  2. knowledge/**.md|.txt 的外部知識文件（依標題/段落切 chunk）

用法：
    python scripts/ingest_rag.py                 # 全量
    python scripts/ingest_rag.py --source memory # 只索引記憶
    python scripts/ingest_rag.py --source knowledge
    python scripts/ingest_rag.py --reset         # 先清空再重建
"""

import os
import re
import sys
import json
import glob
import argparse

# Windows 主控台多為 cp950，emoji 會拋 UnicodeEncodeError，統一轉 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
KNOW_DIR = os.path.join(BASE_DIR, "knowledge")

MEM_FILES = {
    "unified_memory.json": "unified_memory",
    "dialogue_memory.json": "dialogue_memory",
    "thought_memory.json": "thought_memory",
}
VIEWER_FILE = "viewer_profiles_local.json"
KNOW_FILE = "cloud_knowledge_local.json"

MAX_CHUNK = 400        # 單 chunk 上限字數
MIN_CHUNK = 30         # 太短的碎片不收


# ── 切 chunk ────────────────────────────────────────────────────────────────
def chunk_text(text: str, max_len: int = MAX_CHUNK) -> list:
    """先按句子切，再把過短的句子合併成 <= max_len 的塊"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text] if len(text) >= MIN_CHUNK else []

    sents = re.split(r"(?<=[。！？!?；;])", text)
    chunks, buf = [], ""
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if len(buf) + len(s) <= max_len:
            buf += s
        else:
            if len(buf) >= MIN_CHUNK:
                chunks.append(buf.strip())
            buf = s
    if len(buf) >= MIN_CHUNK:
        chunks.append(buf.strip())
    # 單句超過 max_len 的硬切（含重疊避免邊界斷義）
    final = []
    for c in chunks:
        if len(c) <= max_len:
            final.append(c)
        else:
            step = max_len - 60
            for i in range(0, len(c), step):
                piece = c[i:i + max_len].strip()
                if len(piece) >= MIN_CHUNK:
                    final.append(piece)
    return final


# ── 各來源 → (id, text, metadata) ──────────────────────────────────────────
def _ts(meta: dict) -> str:
    return str(meta.get("time_str") or meta.get("time") or "")[:40]


def load_memory_items() -> list:
    items = []
    for fname, tag in MEM_FILES.items():
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            rows = json.load(open(path, "r", encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️ 讀取失敗 {fname}: {e}")
            continue
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            meta = {
                "source": tag,
                "speaker": str(row.get("speaker") or ""),
                "target": str(row.get("target") or ""),
                "role": str(row.get("role") or ""),
                "time": _ts(row),
            }
            # 短訊息直接一筆；長訊息切塊
            chunks = chunk_text(content, MAX_CHUNK)
            for j, c in enumerate(chunks):
                uid = f"mem:{tag}:{i}:{j}"
                items.append((uid, c, meta))
    return items


def load_cloud_knowledge_items() -> list:
    path = os.path.join(DATA_DIR, KNOW_FILE)
    if not os.path.exists(path):
        return []
    try:
        data = json.load(open(path, "r", encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️ 讀取失敗 {KNOW_FILE}: {e}")
        return []
    items = []
    updated = str(data.get("last_updated") or "")
    for key, val in data.items():
        if key == "last_updated":
            continue
        if isinstance(val, list):
            pieces = []
            for e in val:
                if isinstance(e, dict):
                    pieces.append("，".join(f"{k}: {v}" for k, v in e.items() if v))
                else:
                    pieces.append(str(e))
            text = "\n".join(p for p in pieces if p)
        elif isinstance(val, dict):
            text = "\n".join(f"{k}: {v}" for k, v in val.items() if v)
        else:
            text = str(val)
        for j, c in enumerate(chunk_text(text)):
            items.append((f"cloud:{key}:{j}", c, {"source": f"cloud_knowledge:{key}", "time": updated}))
    return items


def load_viewer_items() -> list:
    path = os.path.join(DATA_DIR, VIEWER_FILE)
    if not os.path.exists(path):
        return []
    try:
        data = json.load(open(path, "r", encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️ 讀取失敗 {VIEWER_FILE}: {e}")
        return []
    items = []
    if not isinstance(data, dict):
        return items
    for name, prof in data.items():
        if isinstance(prof, dict):
            text = f"觀眾「{name}」：" + "，".join(
                f"{k}: {v}" for k, v in prof.items() if v not in (None, "", [])
            )
        else:
            text = f"觀眾「{name}」：{prof}"
        for j, c in enumerate(chunk_text(text, 300)):
            items.append((f"viewer:{name}:{j}", c, {"source": "viewer_profile", "viewer": name}))
    return items


def load_knowledge_files() -> list:
    items = []
    if not os.path.isdir(KNOW_DIR):
        return items
    files = sorted(glob.glob(os.path.join(KNOW_DIR, "**", "*"), recursive=True))
    for path in files:
        if not os.path.isfile(path):
            continue
        if not path.lower().endswith((".md", ".txt")):
            continue
        if os.path.basename(path).lower() == "readme.md":
            continue
        try:
            raw = open(path, "r", encoding="utf-8", errors="replace").read()
        except Exception as e:
            print(f"  ⚠️ 讀取失敗 {os.path.basename(path)}: {e}")
            continue
        rel = os.path.relpath(path, KNOW_DIR).replace("\\", "/")
        title = os.path.splitext(os.path.basename(path))[0]

        # 有 markdown 標題就按標題分段，否則按段落
        sections = re.split(r"\n(?=#{1,4}\s)", raw) if raw.count("\n#") >= 1 else re.split(r"\n\s*\n", raw)
        idx = 0
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            head = sec.split("\n", 1)[0].strip("# ").strip() or title
            for j, c in enumerate(chunk_text(sec)):
                uid = f"kb:{rel}:{idx}"
                idx += 1
                items.append((uid, c, {"source": f"knowledge/{rel}", "title": f"{title} / {head}"}))
    return items


def collect(sources) -> list:
    items = []
    if "memory" in sources:
        items += load_memory_items()
        items += load_cloud_knowledge_items()
        items += load_viewer_items()
        print(f"  記憶類來源：{len(items)} 筆")
    if "knowledge" in sources:
        kb = load_knowledge_files()
        print(f"  knowledge/ 文件：{len(kb)} 筆")
        items += kb
    return items


def main():
    ap = argparse.ArgumentParser(description="RAG 建檔")
    ap.add_argument("--source", choices=["all", "memory", "knowledge"], default="all")
    ap.add_argument("--reset", action="store_true", help="先清空向量庫")
    ap.add_argument("--dry-run", action="store_true", help="只列出建檔內容，不真的嵌入")
    args = ap.parse_args()

    sources = ["memory", "knowledge"] if args.source == "all" else [args.source]

    print("=" * 64)
    print("🧺 RAG 建檔 (Ingest)")
    print("=" * 64)

    if args.reset:
        from services import rag_store
        n = rag_store.reset()
        print(f"  🧹 已清空向量庫: {n}")

    items = collect(sources)
    if not items:
        print("  ❌ 沒有任何來源可建檔")
        return 1

    ids = [i[0] for i in items]
    texts = [i[1] for i in items]
    metas = [i[2] for i in items]

    if args.dry_run:
        for uid, txt, meta in items[:8]:
            print(f"  [{uid}] {txt[:70]}...  <- {meta.get('source')}")
        print(f"  (dry-run 共 {len(items)} 筆，未嵌入)")
        return 0

    from services import rag_store
    from services import embedder
    print(f"  🔤 嵌入後端：{embedder.backend_name()} (dim={embedder.dim()})")
    n = rag_store.upsert_documents(ids, texts, metas)
    st = rag_store.stats()
    print(f"  ✅ 寫入 {n} 筆；向量庫共 {st.get('count')} 筆 @ {st.get('path')}")

    # 抽檢：用一句常見問題測召回
    probe = search_probe()
    if probe:
        print("  🔍 抽檢召回：")
        for h in probe:
            print(f"     {h['score']:.3f}  {h['text'][:60]}")
    return 0


def search_probe():
    try:
        from services import rag_store
        return rag_store.search("7L 是誰？老爸的偏好", k=3)
    except Exception:
        return []


if __name__ == "__main__":
    sys.exit(main())
