# -*- coding: utf-8 -*-
"""一本流水帳（2026-10-26，docs/REDESIGN.md 的 D）。

發生過的事都在這裡記一筆，只增不改：聽到的（heard）、她講的（said）、心想（thought）、
遞給主腦的紙條（slip）、執行的舞台指令（stage_cmd）、主腦呼叫的工具（tool_call）、
換狀態（stage）、看到的畫面（vision）。

以前這些散在七份清單裡（紙條案底、紙條去重帳本、硬指令去重帳本、只寫沒人讀的上下文……），
各有各的上限和過期規則；去重、斷線救援現在都是對這本帳查詢。
對話記憶（給提示詞用的那份、後台能編輯刪除的那份）還是 core.memory 的 JSON，這裡同時記一份（雙寫）。

一場直播的事件可以拿去重播（tools/replay.py）：不用開實機就能重現當時的輸入。

SQLite（WAL）：實測每筆寫入約 15 微秒、查詢約 30 微秒，直接在主迴圈上寫。
"""
import json
import os
import sqlite3
import threading
import time
from typing import Iterable, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,
    who     TEXT NOT NULL DEFAULT '',
    target  TEXT NOT NULL DEFAULT '',
    text    TEXT NOT NULL DEFAULT '',
    meta    TEXT NOT NULL DEFAULT '{}',
    turn_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_kind_ts ON events(kind, ts);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
"""


def _row(r) -> dict:
    d = dict(r)
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except Exception:
        d["meta"] = {}
    return d


class EventLog:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5.0)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(_SCHEMA)

    def record(self, kind: str, text: str = "", who: str = "", target: str = "", turn_id: str = "",
               ts: Optional[float] = None, **meta) -> int:
        """記一筆，回 id。meta 放其他欄位（要能轉成 JSON）。"""
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO events(ts, kind, who, target, text, meta, turn_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time() if ts is None else ts, kind, who or "", target or "", text or "",
                 json.dumps(meta, ensure_ascii=False, default=str), turn_id or ""))
            return cur.lastrowid

    def recent(self, kinds: Iterable[str] = (), since: Optional[float] = None, until: Optional[float] = None,
               limit: int = 100, **meta_eq) -> List[dict]:
        """最近的事件（舊到新）。kinds 空＝全部；meta_eq 比 meta 裡的欄位（例：brain="live"）。"""
        sql, args = "SELECT * FROM events WHERE 1=1", []
        kinds = list(kinds) if not isinstance(kinds, str) else [kinds]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        if until is not None:
            sql += " AND ts <= ?"
            args.append(until)
        for k, v in meta_eq.items():
            sql += " AND json_extract(meta, ?) = ?"
            args += [f"$.{k}", v]
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [_row(r) for r in reversed(rows)]

    def seen(self, kind: str, text: str, within: float, now: Optional[float] = None) -> bool:
        """within 秒內有沒有一筆同種類、文字一字不差的事件。"""
        now = time.time() if now is None else now
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM events WHERE kind = ? AND text = ? AND ts > ? AND ts <= ? LIMIT 1",
                (kind, text or "", now - within, now)).fetchone() is not None

    def last(self, kind: str, since: Optional[float] = None, prefixes: Iterable[str] = ()) -> Optional[dict]:
        """最新一筆這種事件；prefixes 給了就只看文字開頭符合其中一個的。"""
        sql, args = "SELECT * FROM events WHERE kind = ?", [kind]
        if since is not None:
            sql += " AND ts > ?"
            args.append(since)
        prefixes = list(prefixes)
        if prefixes:
            sql += " AND (" + " OR ".join("substr(text, 1, ?) = ?" for _ in prefixes) + ")"
            for p in prefixes:
                args += [len(p), p]
        sql += " ORDER BY ts DESC, id DESC LIMIT 1"
        with self._lock:
            r = self._db.execute(sql, args).fetchone()
        return _row(r) if r else None

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._db.close()


_DEFAULT: Optional[EventLog] = None
_DEFAULT_LOCK = threading.Lock()


def default_path() -> str:
    from core.memory import mode_path
    return mode_path("events.sqlite")


def get() -> EventLog:
    """全程式一本（照模式分檔，跟對話記憶一樣：data/events_companion.sqlite）。第一次用到才開。"""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = EventLog(default_path())
    return _DEFAULT


def set_default(log: Optional[EventLog]) -> None:
    """測試換成記憶體裡的帳本，不寫到 data/。"""
    global _DEFAULT
    _DEFAULT = log


# 不上傳雲端的事件：看到的畫面描述（老爸不讓測試看螢幕；平常看到的也只留在本機）
CLOUD_SKIP_KINDS = ("vision",)


def _backup_state(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(json.load(f).get("last_id", 0))
    except Exception:
        return 0


async def backup_once(log: EventLog, db, collection: str, state_path: str, batch: int = 400) -> int:
    """把上次推完之後的新事件推上 Firestore（每 batch 筆一份文件），回推了幾筆。
    推失敗就停在那裡，下次從同一筆接著推。Firestore 只當備份：本機帳本才是正本。"""
    last_id, pushed = _backup_state(state_path), 0
    while True:
        with log._lock:
            rows = [_row(r) for r in log._db.execute(
                "SELECT * FROM events WHERE id > ? ORDER BY id LIMIT ?", (last_id, batch)).fetchall()]
        if not rows:
            return pushed
        keep = [{"id": r["id"], "ts": r["ts"], "kind": r["kind"], "who": r["who"], "target": r["target"],
                 "text": r["text"], "meta": json.dumps(r["meta"], ensure_ascii=False, default=str)}
                for r in rows if r["kind"] not in CLOUD_SKIP_KINDS]
        if keep:
            status = await db.collection(collection).document(f"{rows[0]['id']:010d}").set(
                {"rows": keep, "first_id": rows[0]["id"], "last_id": rows[-1]["id"], "pushed_at": time.time()})
            if status not in (200, 201):
                return pushed
        last_id = rows[-1]["id"]
        pushed += len(keep)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({"last_id": last_id, "at": time.time()}, f)


async def cloud_backup_worker(get_db, collection: str, state_path: str, interval: float = 300.0) -> None:
    """每 interval 秒把新事件推上 Firestore 備份（get_db() 回 Firestore 用戶端，沒有就跳過這輪）。"""
    import asyncio
    from core.utils import log_print, log_swallowed
    while True:
        await asyncio.sleep(interval)
        db = get_db()
        if db is None:
            continue
        try:
            n = await backup_once(get(), db, collection, state_path)
            if n:
                log_print(f"☁️ [流水帳備份] {n} 筆推上雲端（{collection}）")
        except Exception:
            log_swallowed()


def memory_kind(speaker: str, role: str, target: str = "", source: str = "") -> str:
    """對話記憶的一筆算哪種事件：心想 thought、她講的 said、其他（老爸、觀眾、系統）heard。"""
    if role == "thought" or target == "內心流動" or source == "thought":
        return "thought"
    if role in ("assistant", "ai", "model") or speaker == "7L":
        return "said"
    return "heard"


def import_memory_entries(log: EventLog, entries: Iterable[dict]) -> int:
    """把舊的 JSON 對話記憶匯進來（帳本是空的才匯，只做一次），回匯了幾筆。"""
    if log.count():
        return 0
    n = 0
    for e in sorted((e for e in entries if isinstance(e, dict)), key=lambda e: e.get("time", 0.0)):
        content = (e.get("content") or "").strip()
        if not content:
            continue
        speaker, role = e.get("speaker", ""), e.get("role", "")
        log.record(memory_kind(speaker, role, e.get("target", ""), e.get("source", "")), content,
                   who=speaker, target=e.get("target", ""), ts=float(e.get("time") or 0.0),
                   role=role, source=e.get("source", ""), imported=True)
        n += 1
    return n
