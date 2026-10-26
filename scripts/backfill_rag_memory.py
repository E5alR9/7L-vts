# -*- coding: utf-8 -*-
"""把對話記憶檔（data/unified_memory_<模式>.json）裡老爸的話、她的回覆、熟客的留言補進向量記憶庫。

2026-10-26 以前向量庫只存老爸 text／voice 兩種來源：後台打字、麥克風的話、她的回覆、熟客的留言都沒進去。
規則跟現在即時寫入的一樣（core/memory.rag_memory_entry；熟客＝本機觀眾檔裡有的人）；已經在庫裡的（同一句）不重複寫。
用法：python scripts/backfill_rag_memory.py [--mode companion|vtuber] [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.env_config import load_project_env  # noqa: E402

load_project_env()

ap = argparse.ArgumentParser()
ap.add_argument("--mode", default="", help="companion／vtuber；不給就照 MODE 環境變數，再不然看哪個記憶檔存在")
ap.add_argument("--dry-run", action="store_true", help="只列出會補哪些，不寫")
args = ap.parse_args()

mode = args.mode or os.getenv("MODE") or ""
if not mode:
    mode = "companion" if os.path.exists(os.path.join(ROOT, "data", "unified_memory_companion.json")) else "vtuber"
os.environ["MODE"] = mode          # rag_store 的集合名、core.memory 的檔名都看這個，要在 import 之前定
import services.rag_store as rag_store                      # noqa: E402
from core.memory import rag_memory_entry, UNIFIED_MEMORY_FILE  # noqa: E402

print(f"模式 {mode}：記憶檔 {UNIFIED_MEMORY_FILE}，向量庫集合 {rag_store.COLLECTION}")
try:
    data = json.load(open(UNIFIED_MEMORY_FILE, encoding="utf-8"))
except Exception as e:
    print(f"讀不到記憶檔：{e}")
    sys.exit(1)
entries = data if isinstance(data, list) else (data.get("entries") or data.get("items") or [])

col = rag_store._get_collection()
have = set()
if col.count():
    got = col.get(limit=col.count(), include=["documents"])
    have = {d for d in (got.get("documents") or []) if d}

ids, texts, metas = [], [], []
skipped = {"不存的種類": 0, "已經在庫裡": 0}
for e in entries:
    if not isinstance(e, dict):
        continue
    try:
        t = float(e.get("time") or 0)
    except Exception:
        t = 0.0
    t_str = e.get("time_str") or (datetime.fromtimestamp(t).strftime("%H:%M:%S") if t else "")
    entry = rag_memory_entry(str(e.get("speaker", "")), str(e.get("target", "")), str(e.get("content", "")),
                             str(e.get("role", "")), str(e.get("source", "")), t_str)
    if not entry:
        skipped["不存的種類"] += 1
        continue
    text, meta = entry
    if text in have:
        skipped["已經在庫裡"] += 1
        continue
    have.add(text)
    ids.append(f"mem_bf_{int(t * 1000)}_{e.get('role')}")
    texts.append(text)
    metas.append({**meta, "timestamp": datetime.fromtimestamp(t).isoformat() if t else ""})

print(f"記憶檔 {len(entries)} 筆：要補 {len(texts)} 筆（老爸 {sum(m['source'] == 'user' and not m.get('viewer') for m in metas)}、"
      f"她 {sum(m['source'] == 'assistant' for m in metas)}、熟客 {sum(bool(m.get('viewer')) for m in metas)}）；跳過 {skipped}")
for txt in texts[:8]:
    print("  ", txt[:100])
if args.dry_run or not texts:
    print("（dry-run，沒寫）" if args.dry_run else "沒有要補的")
    sys.exit(0)
n = rag_store.upsert_documents(ids, texts, metas)
print(f"寫入 {n} 筆，向量庫現在 {col.count()} 筆")
