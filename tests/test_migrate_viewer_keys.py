"""舊觀眾檔搬到「平台:帳號」當 key 的工具（tools/migrate_viewer_keys.py）。"""
import importlib.util
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("migrate_viewer_keys", os.path.join(ROOT, "tools", "migrate_viewer_keys.py"))
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def _events(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, who TEXT, target TEXT, text TEXT, meta TEXT, turn_id TEXT)")
    for viewer, uid, source in rows:
        con.execute("INSERT INTO events (ts, kind, who, meta) VALUES (0, 'input', ?, ?)",
                    (viewer, json.dumps({"viewer": viewer, "platform_uid": uid, "source": source}, ensure_ascii=False)))
    con.commit()
    con.close()


def test_only_names_with_one_real_account_are_moved(tmp_path):
    db = str(tmp_path / "events.sqlite")
    _events(db, [("J", "jaded_jjj", "tiktok"), ("J", "jaded_jjj", "tiktok_gift"),
                 ("阿呆", "阿呆01", "tiktok"),                                   # 測試包裝的帳號（名字＋01）不算
                 ("雙胞胎", "twin_a", "tiktok"), ("雙胞胎", "twin_b", "tiktok"),  # 一個名字兩個帳號：分不出是誰，不搬
                 ("王", "wang_tw", "twitch"), ("<小>", "small1", "youtube")])
    acc = mig.account_map(db, lambda t, n: t.replace("<", "‹").replace(">", "›"))
    assert acc == {"J": ("tiktok", "jaded_jjj"), "王": ("twitch", "wang_tw"), "‹小›": ("youtube", "small1")}
    profiles = {"J": {"call": "阿J"}, "阿呆": {"call": "呆呆"}, "雙胞胎": {}, "‹小›": {"impression": "愛唱歌"},
                "tiktok:old": {"call": "已經是帳號"}}
    moves = {old: (new, prof) for old, new, prof in mig.plan(profiles, acc)}
    assert set(moves) == {"J", "‹小›"}
    assert moves["J"][0] == "tiktok:jaded_jjj" and moves["J"][1]["call"] == "阿J" and moves["J"][1]["names"] == ["J"]
    assert moves["‹小›"][0] == "youtube:small1"
    # 重跑：新 key 已經有了就不再搬
    profiles["tiktok:jaded_jjj"] = moves["J"][1]
    assert "J" not in {old for old, _, _ in mig.plan(profiles, acc)}
