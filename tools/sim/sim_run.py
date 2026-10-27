"""模擬直播用的 7L 啟動包裝（tools/sim/live_up.sh 用它開）：照常跑 vts_7L_test.py，另在 127.0.0.1:7870
開一個測試埠，把模擬的觀眾留言／送禮／關注放進 7L 的輸入佇列（格式跟 TikTok／YouTube 監聽器送進來的一樣）。
正式程式碼完全不動；只在這個包裝啟動時存在。

看不到老爸的螢幕：主程式啟動前把所有截圖入口換成「不截圖」（老爸 2026-10-26 指示，測試絕不能看螢幕）。
live_up.sh 開好後會再經 /exec 確認一次，沒擋住就立刻關掉 7L。

POST /viewer  {"user": "阿呆", "text": "7L 晚安", "uid": "adai01", "platform": "tiktok|youtube"}
POST /event   {"text": "【TikTok 直播動態】：...", "source": "tiktok_gift|tiktok_ambient"}
POST /exec    {"code": "result = m.IS_SLEEPING"}  在主迴圈裡跑一段 async 程式（m＝主程式模組），回 result
GET  /call?fn=名稱&args=[...]                      在主迴圈裡呼叫主程式的一個函式
"""
import asyncio
import json
import os
import runpy
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)


def _put(item):
    import services.web_dashboard as wd
    if not (wd.INPUT_QUEUE and wd.MAIN_EVENT_LOOP):
        return False
    asyncio.run_coroutine_threadsafe(wd.INPUT_QUEUE.put(item), wd.MAIN_EVENT_LOOP).result(5)
    return True


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        # 除錯：列出主迴圈裡名稱含 ?q= 的協程卡在哪一行
        import io as _io
        import services.web_dashboard as wd
        from urllib.parse import urlparse, parse_qs
        q = (parse_qs(urlparse(self.path).query).get("q") or [""])[0]
        if self.path.startswith("/call"):
            # 除錯：在主迴圈裡呼叫主程式的一個協程函式（只在測試包裝裡有）
            import json as _json
            qs = parse_qs(urlparse(self.path).query)
            fn = getattr(sys.modules["vts_7L_test"], qs["fn"][0])
            args = _json.loads(qs.get("args", ["[]"])[0])

            async def _run():
                r = fn(*args)
                return (await r) if asyncio.iscoroutine(r) else r
            try:
                res = asyncio.run_coroutine_threadsafe(_run(), wd.MAIN_EVENT_LOOP).result(120)
                body = _json.dumps({"ok": True, "result": repr(res)[:4000]}, ensure_ascii=False)
            except Exception as e:
                body = _json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            return

        async def dump():
            buf = _io.StringIO()
            for t in asyncio.all_tasks():
                r = repr(t.get_coro())
                if q in r:
                    buf.write("=== " + r[:160] + "\n")
                    t.print_stack(limit=30, file=buf)
            return buf.getvalue()
        out = asyncio.run_coroutine_threadsafe(dump(), wd.MAIN_EVENT_LOOP).result(5)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(out.encode("utf-8"))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        now = time.time()
        if self.path == "/exec":
            # 除錯：在主迴圈裡跑一段 async 程式（變數 m＝主程式模組），回 result 變數（只在測試包裝裡有）
            import services.web_dashboard as wd
            src = "async def __t(m):\n" + "\n".join("    " + l for l in body.get("code", "").splitlines()) + "\n    return locals().get('result')"
            g = {"asyncio": asyncio}
            exec(src, g)
            try:
                res = asyncio.run_coroutine_threadsafe(g["__t"](sys.modules["vts_7L_test"]), wd.MAIN_EVENT_LOOP).result(60)
                out = {"ok": True, "result": repr(res)[:4000]}
            except Exception as e:
                out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
            return
        if self.path == "/viewer":
            user, text = body.get("user", "路人"), body.get("text", "")
            if body.get("platform") == "youtube":
                item = {"text": f"【YouTube 直播觀眾 {user}】：{text}", "platform_uid": body.get("uid", ""),
                        "audio_base64": None, "timestamp": now, "source": "youtube", "message_id": f"sim{now}",
                        "user": user, "avatar": "", "viewer": user, "content": text}
            else:
                item = {"text": f"【TikTok 直播觀眾 {user} 留言】：{text}", "audio_base64": None,
                        "timestamp": now, "source": "tiktok", "platform_uid": body.get("uid", ""),
                        "viewer": user, "content": text}
        elif self.path == "/event":
            item = {"text": body.get("text", ""), "audio_base64": None, "timestamp": now,
                    "source": body.get("source", "tiktok_gift"),
                    "viewer": body.get("viewer", ""), "content": body.get("content", "")}
        else:
            self.send_response(404); self.end_headers(); return
        ok = _put(item)
        self.send_response(200 if ok else 503)
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok}).encode())


threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", 7870), H).serve_forever, daemon=True).start()
import dotenv as _dotenv

# 只在測試時用的覆寫（不寫進 .env）：SIM_MODE=vtuber 用 VTuber 模式開；SIM_NO_CLOUD=1 不連 Firestore（不碰雲端備份）。
# 主程式一開頭會用 override=True 重讀 .env，所以包住 load_dotenv：每次讀完都再套一次。
_SIM_OVERRIDES = {k: v for k, v in (("MODE", os.environ.get("SIM_MODE", "")),
                                    ("FIREBASE_ENABLED", "0" if os.environ.get("SIM_NO_CLOUD") == "1" else "")) if v}
_orig_load_dotenv = _dotenv.load_dotenv


def _load_dotenv_then_override(*a, **k):
    r = _orig_load_dotenv(*a, **k)
    os.environ.update(_SIM_OVERRIDES)
    return r


_dotenv.load_dotenv = _load_dotenv_then_override
from core.env_config import ENV_PATH as _ENV_PATH   # 專案資料夾的 .env，沒有就家目錄的
_dotenv.load_dotenv(_ENV_PATH, override=True)   # 跟主程式一樣先讀 .env，金鑰模組才不會空著初始化
if _SIM_OVERRIDES:
    print(f"🧪 [測試包裝] 覆寫 {_SIM_OVERRIDES}", flush=True)

# 老爸不讓測試看他的螢幕（2026-10-26）：所有截圖入口在主程式啟動前換成「不截圖」。
# 主程式、後台都從 services.screen_capture 拿畫面（用到才 import，所以換模組屬性就生效）；YT 伴看用 PIL.ImageGrab。
import services.screen_capture as _sc
from PIL import ImageGrab as _ig


def _no_screen(*a, **k):
    print("🙈 [測試包裝] 不截老爸的螢幕", flush=True)
    return None


def _no_grab(*a, **k):
    raise RuntimeError("測試包裝：不截老爸的螢幕")


_sc.grab_screen = _no_screen
_sc.gdi_capture_screen = _no_screen
_ig.grab = _no_grab
sys.argv = [os.path.join(ROOT, "vts_7L_test.py")]
runpy.run_path(os.path.join(ROOT, "vts_7L_test.py"), run_name="__main__")
