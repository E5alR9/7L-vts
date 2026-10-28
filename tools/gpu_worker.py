# -*- coding: utf-8 -*-
"""筆電的顯卡小幫手：桌機的 7L 翻唱時，把人聲分離（Roformer）和 RVC 變聲丟過來，這裡跑完傳回去。

桌機那邊見 services/remote_gpu.py；筆電沒開、忙或出錯，桌機就照舊自己跑。
一次只接一件（筆電 8 GB 顯卡，兩種重活疊在一起 RVC 會慢到 20 分鐘以上），忙的時候回 503 讓桌機自己來；
顯卡剩不多（筆電自己的 7L 開著）也回 503。閒置 10 分鐘把模型從顯卡卸掉，不佔著筆電自己要用的顯存。

    python tools/gpu_worker.py        （連接埠 24820，只收 Tailscale 和本機來的）
用 pythonw 跑時日誌寫到 data/gpu_worker/gpu_worker.log。
"""
import asyncio
import gc
import glob
import ipaddress
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

WORK_DIR = os.path.join(ROOT, "data", "gpu_worker")
os.makedirs(WORK_DIR, exist_ok=True)
if sys.stdout is None:   # pythonw 沒有主控台，print 會炸
    sys.stdout = sys.stderr = open(os.path.join(WORK_DIR, "gpu_worker.log"), "a", encoding="utf-8", buffering=1)

import torch
from aiohttp import web
from core.utils import log_print

PORT = int(os.getenv("GPU_WORKER_PORT", "24820"))
IDLE_UNLOAD_SEC = 600
MIN_FREE_MB = 1500
_ALLOWED = [ipaddress.ip_network(n) for n in
            ("100.64.0.0/10", "fd7a:115c:a1e0::/48", "127.0.0.0/8", "::1/128")]

_job_lock = asyncio.Lock()
_last_job = time.time()


def _free_mb() -> int:
    if not torch.cuda.is_available():
        return 0
    free, _total = torch.cuda.mem_get_info()
    return free // (1024 * 1024)


@web.middleware
async def _only_tailscale(request, handler):
    try:
        ok = any(ipaddress.ip_address(request.remote) in n for n in _ALLOWED)
    except ValueError:
        ok = False
    if not ok:
        raise web.HTTPForbidden()
    return await handler(request)


async def health(request):
    return web.json_response({
        "ok": torch.cuda.is_available(),
        "busy": _job_lock.locked(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "free_mb": _free_mb(),
    })


async def _run_job(request, label: str, work):
    """收進來的 wav 存成 job 檔 → 背景執行緒跑 work(src, base) → 回它給的 Response；job 檔一律清掉。"""
    global _last_job
    if _job_lock.locked() or _free_mb() < MIN_FREE_MB:
        return web.json_response({"ok": False, "busy": True, "free_mb": _free_mb()}, status=503)
    async with _job_lock:
        base = f"job_{int(time.time() * 1000)}"
        src = os.path.join(WORK_DIR, base + ".wav")
        t0 = time.time()
        try:
            with open(src, "wb") as f:
                async for chunk in request.content.iter_chunked(1 << 20):
                    f.write(chunk)
            log_print(f"🖥️ [顯卡小幫手] 收到{label}：{request.query.get('song', '')}（{os.path.getsize(src) // 1024} KB）")
            resp = await asyncio.to_thread(work, src, base)
            log_print(f"🖥️ [顯卡小幫手] {label}{'完成' if resp.status == 200 else '失敗'}，{time.time() - t0:.0f} 秒")
            return resp
        except Exception as e:
            log_print(f"⚠️ [顯卡小幫手] {label}異常: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        finally:
            _last_job = time.time()
            # roformer_out 裡 audio-separator 自己的輸出也照 job 名清掉
            for p in glob.glob(os.path.join(WORK_DIR, base + "*")) + \
                     glob.glob(os.path.join(WORK_DIR, "roformer_out", base + "*")):
                try:
                    os.remove(p)
                except OSError:
                    pass


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


async def separate(request):
    def work(src, base):
        from services.roformer_sep import separate_roformer
        # 輸出放固定的 WORK_DIR：roformer_sep 按輸出資料夾快取模型，每次換資料夾就會再載一份上顯卡
        voc = os.path.join(WORK_DIR, base + "_vocals.wav")
        ins = os.path.join(WORK_DIR, base + "_instrumental.wav")
        if not separate_roformer(src, voc, ins, song_name=request.query.get("song", "")):
            return web.json_response({"ok": False, "error": "roformer failed"}, status=500)
        v, i = _read(voc), _read(ins)
        return web.Response(body=v + i, content_type="application/octet-stream",
                            headers={"X-Vocals-Bytes": str(len(v))})
    return await _run_job(request, "人聲分離", work)


async def rvc(request):
    def work(src, base):
        from services.neural_voice_converter import convert_vocal_to_xiaoyi
        from core.paths import RVC_7L_MODEL, RVC_7L_INDEX
        out = os.path.join(WORK_DIR, base + "_7l_vocal.wav")
        ok = convert_vocal_to_xiaoyi(
            src, out, key=float(request.query.get("key", "0")),
            model_pth=RVC_7L_MODEL, index_file=RVC_7L_INDEX,
            index_rate=float(request.query.get("index_rate", "0.88")),
            auto_pitch=request.query.get("auto_pitch", "1") == "1")
        if not ok or not os.path.exists(out):
            return web.json_response({"ok": False, "error": "rvc failed"}, status=500)
        return web.Response(body=_read(out), content_type="audio/wav")
    return await _run_job(request, "RVC 變聲", work)


async def _idle_unloader(app):
    async def loop():
        while True:
            await asyncio.sleep(60)
            if _job_lock.locked() or time.time() - _last_job < IDLE_UNLOAD_SEC:
                continue
            dropped = False
            rs = sys.modules.get("services.roformer_sep")
            if rs is not None and rs._SEPS:
                with rs._SEPS_LOCK:
                    rs._SEPS.clear()
                dropped = True
            nvc = sys.modules.get("services.neural_voice_converter")
            if nvc is not None and (nvc._HUBERT_MODEL is not None or nvc._NET_G_CACHE):
                nvc._HUBERT_MODEL = None
                nvc._NET_G_CACHE.clear()
                dropped = True
            if dropped:
                gc.collect()
                torch.cuda.empty_cache()
                log_print(f"🖥️ [顯卡小幫手] 閒置 {IDLE_UNLOAD_SEC // 60} 分鐘，模型卸下顯卡（剩 {_free_mb()} MB）")
    task = asyncio.create_task(loop())
    yield
    task.cancel()


def main():
    app = web.Application(middlewares=[_only_tailscale], client_max_size=1024 ** 3)
    app.router.add_get("/health", health)
    app.router.add_post("/separate", separate)
    app.router.add_post("/rvc", rvc)
    app.cleanup_ctx.append(_idle_unloader)
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "沒有 CUDA 顯卡"
    log_print(f"🖥️ [顯卡小幫手] {gpu}，聽 {PORT}（只收 Tailscale／本機）")
    web.run_app(app, host=os.getenv("GPU_WORKER_HOST", "0.0.0.0"), port=PORT, print=None)


if __name__ == "__main__":
    main()
