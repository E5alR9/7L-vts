# -*- coding: utf-8 -*-
"""重播一段直播（2026-10-26，docs/REDESIGN.md 的 D）。

從流水帳（data/events_<模式>.sqlite）挑一段時間的輸入（老爸打字、直播留言、送禮……），
照順序丟進乾跑包裝（tests/dryrun.py：主程式這一串原樣跑，AI 和硬體是假的），
列出每則輸入讓她做了什麼：遞給主腦的紙條、CPU 直接執行的舞台指令、排進說話佇列的話、被吞掉的錯誤。
以前要重現一個問題得開實機、等兩三分鐘、照當時的順序再打一次。

    python tools/replay.py                      # 最近 20 則輸入
    python tools/replay.py --last 50
    python tools/replay.py --since "2026-10-26 09:39" --until "2026-10-26 09:45"
    python tools/replay.py --rest               # 假裝 Live 主腦不在，紙條由（假的）REST 大腦接
    python tools/replay.py --sentry silent      # 看板哨兵一律判「不用回」

只讀帳本，不寫；重播時的帳本、記憶都在記憶體裡。錄音不在帳本裡，麥克風輸入只重播文字。
"""
import argparse
import asyncio
import datetime
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]


def load_inputs(db_path: str, since: float = None, until: float = None, last: int = 20) -> list:
    """帳本裡的輸入事件（舊到新）。用唯讀方式開，不會動到帳本。"""
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    sql, args = "SELECT * FROM events WHERE kind = 'input'", []
    if since is not None:
        sql += " AND ts >= ?"
        args.append(since)
    if until is not None:
        sql += " AND ts <= ?"
        args.append(until)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    args.append(last)
    rows = [dict(r) for r in db.execute(sql, args).fetchall()]
    db.close()
    for r in rows:
        r["meta"] = json.loads(r.get("meta") or "{}")
    return list(reversed(rows))


def to_queue_item(ev: dict, now: float = None) -> dict:
    """帳本裡的一筆輸入 → 監聽器放進輸入佇列的樣子。時間戳用重播當下（用當時的，看板會當成過期留言丟掉）。"""
    m = ev["meta"]
    return {"text": ev["text"], "timestamp": time.time() if now is None else now, "source": m.get("source") or ev.get("target") or "unknown",
            "platform_uid": m.get("platform_uid", ""), "viewer": m.get("viewer", ""), "content": m.get("content", ""),
            "user": m.get("user", ""), "audio_base64": None}


def _ts(s: str) -> float:
    return datetime.datetime.fromisoformat(s).timestamp()


async def replay(inputs: list, live: bool = True, sentry: str = "speak", settle: float = 2.0) -> list:
    """一則一則丟進乾跑，每則跑完記下多了什麼。回 [(輸入, 結果)]。"""
    from core import eventlog
    from core.identity import is_owner_account
    from dryrun import DryRun

    eventlog.set_default(eventlog.EventLog(":memory:"))   # 重播產生的事件不寫回真的帳本
    decision = ({"should_speak": True, "target": "", "focus": "回應", "raw": "[SPEAK]"} if sentry == "speak"
                else {"should_speak": False, "raw": "[SILENCE]"})
    out = []
    async with DryRun(live=live, sentry=decision, live_sender=True, speaker=True) as d:
        d.ns["is_owner_account"] = is_owner_account            # 認老爸用真的設定
        for ev in inputs:
            before = (len(d.sent_slips), len(d.tools), len(d.spoken), len(d.problems), len(d.brain.calls),
                      len(d.logs))
            await d.input_queue.put(to_queue_item(ev))
            await d.settle(settle)
            out.append((ev, {
                "slips": [s[0] for s in d.sent_slips[before[0]:]],
                "deduped": sum("紙條去重" in l for l in d.logs[before[5]:]),
                "tools": [(t[0], t[1]) for t in d.tools[before[1]:]],
                "speech": [x.get("text", "") for x in d.spoken[before[2]:]],
                "problems": d.problems[before[3]:],
                "rest_brain_calls": len(d.brain.calls) - before[4],
            }))
    return out


def main(argv=None):
    from core.eventlog import default_path
    ap = argparse.ArgumentParser(description="從流水帳重播一段直播（乾跑，不開 Live、不出聲）")
    ap.add_argument("--db", default=None, help="帳本路徑（預設 data/events_<模式>.sqlite）")
    ap.add_argument("--since", help="從這個時間開始，例：2026-10-26 09:39")
    ap.add_argument("--until", help="到這個時間為止")
    ap.add_argument("--last", type=int, default=20, help="最多幾則輸入（取最近的）")
    ap.add_argument("--rest", action="store_true", help="假裝 Live 主腦不在")
    ap.add_argument("--sentry", choices=("speak", "silent"), default="speak", help="看板哨兵的判定")
    ap.add_argument("--settle", type=float, default=2.0, help="每則輸入後等幾秒讓背景做完")
    a = ap.parse_args(argv)
    db = a.db or default_path()
    inputs = load_inputs(db, _ts(a.since) if a.since else None, _ts(a.until) if a.until else None, a.last)
    if not inputs:
        print(f"帳本裡這段時間沒有輸入：{db}")
        return 1
    print(f"重播 {len(inputs)} 則輸入（{db}，Live 主腦{'不在' if a.rest else '在線'}，哨兵 {a.sentry}）\n")
    for ev, r in asyncio.run(replay(inputs, live=not a.rest, sentry=a.sentry, settle=a.settle)):
        t = datetime.datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M:%S")
        print(f"[{t}] {ev['meta'].get('source', '')} {ev['who'] or ''}：{ev['meta'].get('content') or ev['text']}")
        for tool, args in r["tools"]:
            print(f"    ⚡ 舞台指令 {tool}({args})")
        for s in r["slips"]:
            print(f"    📥 紙條 {s[:100]}")
        if r["deduped"]:
            print(f"    📄 {r['deduped']} 張紙條 10 秒內送過，去重跳過")
        for s in r["speech"]:
            print(f"    🗣️ {s[:100]}")
        if r["rest_brain_calls"]:
            print(f"    🧠 REST 大腦被叫 {r['rest_brain_calls']} 次")
        for p in r["problems"]:
            print(f"    ❗ {p[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
