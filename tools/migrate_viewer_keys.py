"""把舊的觀眾檔（用顯示名稱當 key）搬到「平台:帳號」當 key（老爸 2026-10-31）。

用法：
    python tools/migrate_viewer_keys.py --dry    只列出會怎麼搬，不動任何檔案
    python tools/migrate_viewer_keys.py          正式搬（先備份到 data/backup_viewer_key_migration_<日期>/）

怎麼對帳號：事件紀錄（data/events_<模式>.sqlite）每則觀眾留言都記了顯示名稱和平台帳號（platform_uid）。
一個名字只對到一個真的帳號才搬；對不到、或同一個名字對到好幾個帳號的照舊用名字當 key，
那位觀眾下次帶帳號留言時，主程式會自己把舊檔接過去（core/memory.note_viewer_seen）。
測試包裝送的帳號是「名字＋01」，不算真的帳號。

會動的：本機觀眾檔（照模式）、Firestore viewer_profiles（只新增帳號 key 的文件，舊的名字文件留著）、
向量庫裡觀眾說過的話（補上 viewer_key 欄位）。重跑不會重複搬。7L 開著的時候不要跑。
"""
import argparse
import collections
import json
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)


def _atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def account_map(db_path, neutralize) -> dict:
    """事件紀錄裡「顯示名稱（中和過的，跟觀眾檔一樣）→ (平台, 帳號)」：只有一個真的帳號的才算。"""
    seen = collections.defaultdict(set)
    if not os.path.exists(db_path):
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for (meta,) in con.execute("SELECT meta FROM events WHERE kind='input'"):
            try:
                md = json.loads(meta or "{}")
            except ValueError:
                continue
            name = (md.get("viewer") or "").strip()
            uid = (md.get("platform_uid") or "").strip()
            plat = (md.get("source") or "").split("_")[0]
            if not name or not uid or plat not in ("tiktok", "twitch", "youtube") or uid == f"{name}01":
                continue
            seen[neutralize(name, 60)].add((plat, uid))
    finally:
        con.close()
    return {n: next(iter(accts)) for n, accts in seen.items() if len(accts) == 1}


def plan(profiles: dict, accounts: dict) -> list:
    """[(舊 key, 新 key, 新的觀眾檔)]：舊 key 是名字、對得到帳號、新 key 還沒有檔的才搬。"""
    out = []
    for name, prof in profiles.items():
        if ":" in name or name not in accounts:
            continue
        plat, uid = accounts[name]
        new_key = f"{plat}:{uid}"
        if new_key in profiles:
            continue
        new = dict(prof, name=name, tiktok_name=name, names=[name], platform=plat, uid=uid)
        out.append((name, new_key, new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    from dotenv import load_dotenv
    from core.env_config import ENV_PATH
    load_dotenv(ENV_PATH, override=True)
    from core.prompts import neutralize_viewer_text
    import core.memory as mem

    mode = mem.MODE if hasattr(mem, "MODE") else "companion"
    profiles = mem._load_viewer_profiles(strict=True)
    accounts = account_map(mem.mode_path("events.sqlite"), neutralize_viewer_text)
    moves = plan(profiles, accounts)
    stay = [k for k in profiles if ":" not in k and k not in {m[0] for m in moves}]
    print(f"模式 {mode}：觀眾檔 {len(profiles)} 位，搬 {len(moves)} 位，照舊用名字 {len(stay)} 位")
    for old, new, _ in moves:
        print(f"  搬：{old} → {new}")
    for k in stay:
        print(f"  照舊（事件紀錄對不到唯一的真帳號，下次他留言時自動接）：{k}")
    key_of = {old: new for old, new, _ in moves}

    if args.dry:
        print("（試跑，什麼都沒動）")
        return

    backup = os.path.join(ROOT, "data", f"backup_viewer_key_migration_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(backup, exist_ok=True)
    shutil.copy2(mem.VIEWER_PROFILES_FILE, backup)
    chroma = os.path.join(mem.DATA_DIR, "rag", "chroma")
    if os.path.isdir(chroma):
        shutil.copytree(chroma, os.path.join(backup, "chroma"))
    print(f"備份：{backup}")

    new_profiles = dict(profiles)
    for old, new, prof in moves:
        new_profiles.pop(old, None)
        new_profiles[new] = prof
    _atomic(mem.VIEWER_PROFILES_FILE, new_profiles)
    print(f"本機觀眾檔：搬好 {len(moves)} 位")

    # 向量庫：觀眾說過的話補上 viewer_key（對到帳號的用帳號，對不到的先用名字，接檔時再改）
    import services.rag_store as rag_store
    tagged = 0
    for name in {*(k for k in profiles if ":" not in k)}:
        tagged += rag_store.update_where({"viewer": name}, {"viewer_key": key_of.get(name, name)})
    print(f"向量庫：{tagged} 筆觀眾的話補上 viewer_key")

    cred = os.getenv("FIREBASE_CRED_JSON")
    if cred and (os.getenv("FIREBASE_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes") and moves:
        import asyncio
        import core.db as db_module

        async def _cloud():
            db = db_module.init_firestore(json.loads(cred))
            for old, new, prof in moves:
                status = await db.collection("viewer_profiles").document(new).set(
                    {k: v for k, v in prof.items() if v is not None}, merge=True)
                print(f"  雲端 {new}：HTTP {status}")
            sess = getattr(db, "_session", None) or getattr(db, "session", None)
            if sess is not None and not sess.closed:
                await sess.close()
        asyncio.run(_cloud())
    print("完成")


if __name__ == "__main__":
    main()
