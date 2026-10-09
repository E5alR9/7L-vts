# -*- coding: utf-8 -*-
"""隔離測試 update_daily_diary 的 Groq 專責流程（不打網路、不寫真 diaries/）。"""
import ast
import asyncio
import io
import json
import os
import sys
import tempfile
import types
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = r"C:\Users\qiwai"

# ── 假 groq_router ──
FAKE = {"text": None, "calls": 0}
fake_mod = types.ModuleType("core.groq_router")


async def _fake_groq_chat(messages, **kw):
    FAKE["calls"] += 1
    if not FAKE["text"]:
        return None
    return types.SimpleNamespace(text=FAKE["text"], model="fake/qwen")


fake_mod.groq_chat = _fake_groq_chat
sys.path.insert(0, ROOT)
sys.modules["core.groq_router"] = fake_mod
import core  # noqa: E402
core.groq_router = fake_mod

# ── 抽出兩個函式 ──
src = open(os.path.join(ROOT, "vts_7L_test.py"), encoding="utf-8").read()
mod = ast.parse(src)
wanted = {n.name: n for n in mod.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name in ("update_daily_diary", "extract_text_from_content")}
assert set(wanted) == {"update_daily_diary", "extract_text_from_content"}, wanted.keys()

ns = {
    "ZoneInfo": ZoneInfo, "datetime": datetime, "os": os, "json": json,
    "db": None, "log_print": print,
    "asyncio": asyncio, "re": __import__("re"),
}
exec(compile(ast.Module(body=[wanted["extract_text_from_content"], wanted["update_daily_diary"]],
                        type_ignores=[]), "<diary>", "exec"), ns)
diary = ns["update_daily_diary"]

chat = [
    {"role": "user", "content": "老爸：今天直播好累喔，觀眾一直刷彈幕我都來不及回，真的有點招架不住了啦"},
    {"role": "assistant", "content": "7L：那晚點就早點休息嘛，剩下的交給我來回，你去躺一下也好"},
]

_orig_cwd = os.getcwd()
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    try:
        # 1. Groq 正常回覆 → 寫入日記
        FAKE.update(text="今天和老爸聊到直播很累，約好早點休息。", calls=0)
        asyncio.run(diary("chan", chat))
        files = os.listdir("diaries")
        assert len(files) == 1, files
        data = json.load(open(os.path.join("diaries", files[0]), encoding="utf-8"))
        assert "約好早點休息" in data["summary"], data
        print(f"1) Groq 命中 → 寫入 {files[0]}：{data['summary'][:30]}...（呼叫 {FAKE['calls']} 次）")

        # 2. Groq 全滅 → 跳過（不覆寫、不呼叫 Gemini）
        before = open(os.path.join("diaries", files[0]), encoding="utf-8").read()
        FAKE.update(text=None, calls=0)
        asyncio.run(diary("chan", chat))
        after = open(os.path.join("diaries", files[0]), encoding="utf-8").read()
        assert before == after, "Groq 失敗時不該動到日記"
        assert FAKE["calls"] == 1, FAKE
        print(f"2) Groq 全滅 → 跳過本輪、舊日誌原封不動（呼叫 {FAKE['calls']} 次，零 Gemini）")

        # 3. 對話太短 → 根本不呼叫模型
        FAKE.update(text="不該被呼叫", calls=0)
        asyncio.run(diary("chan", [{"role": "user", "content": "哈"}]))
        assert FAKE["calls"] == 0, FAKE
        print("3) 對話 <40 字 → 直接 return，零 API 呼叫")
    finally:
        os.chdir(_orig_cwd)

print("\nDIARY GROQ TEST OK")
