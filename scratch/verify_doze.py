import asyncio
import io
import os
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 造一個假 groq_router（raise → 走降級輪替）
fake = types.ModuleType("core.groq_router")


async def _boom(*a, **k):
    raise RuntimeError("no network in test")


fake.groq_chat = _boom
sys.modules["core.groq_router"] = fake

import importlib.util

spec = importlib.util.spec_from_file_location(
    "doze_mod", os.path.join(os.getcwd(), "vts_7L_test.py"))
# 主檔太重不直接 import；改用 AST 抽 helper 出來 exec
import ast

src = open("vts_7L_test.py", encoding="utf-8").read()
tree = ast.parse(src)
want = {"_doze_one_liner", "_wait_speech_done", "_DOZE_FALLBACK_IDX",
        "_SLEEP_FALLBACKS", "_WAKE_FALLBACKS"}
nodes = [n for n in tree.body
         if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in want)
         or (isinstance(n, ast.Assign) and any(
             getattr(t, "id", "") in want for t in n.targets))]
mod = ast.Module(body=nodes, type_ignores=[])
ns = {"asyncio": asyncio}
exec(compile(mod, "doze", "exec"), ns)


async def main():
    f = ns["_doze_one_liner"]
    # 降級輪替：sleep 3 句輪一圈
    got = [await f("hint", "sleep") for _ in range(4)]
    assert got[0] != got[1] != got[2], got
    assert got[3] == got[0], "第4次應繞回第一句"
    print("sleep輪替 ok:", got[0][:12], "...")
    w = [await f("hint", "wake") for _ in range(2)]
    assert w[0] != w[1]
    print("wake輪替 ok")

    # _wait_speech_done：假 queue 空＋假 task 未 done→done
    class Q:
        def __init__(self):
            self.n = 1

        def empty(self):
            return self.n == 0

    class T:
        def __init__(self):
            self._d = False

        def done(self):
            return self._d

    ns["speech_queue"] = Q()
    t = T()
    ns["CURRENT_PLAYING_VOICE_TASK"] = t

    async def fin():
        await asyncio.sleep(0.3)
        ns["speech_queue"].n = 0
        t._d = True

    asyncio.create_task(fin())
    import time
    s = time.time()
    await ns["_wait_speech_done"](timeout_sec=5.0)
    el = time.time() - s
    assert 0.2 < el < 2.0, el
    print(f"等播完 ok（{el:.2f}s 即放行，非死等5秒）")

    # 超時放行
    ns["speech_queue"].n = 1
    s = time.time()
    await ns["_wait_speech_done"](timeout_sec=1.0)
    el = time.time() - s
    assert 0.9 < el < 2.0, el
    print(f"超時放行 ok（{el:.2f}s）")


asyncio.run(main())
print("ALL OK")
