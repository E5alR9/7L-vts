# -*- coding: utf-8 -*-
"""
CosyVoice 3 本地 TTS 服務（跑在獨立 venv：venvs\\cosyvoice）

為什麼獨立服務：
  CosyVoice 的釘選依賴（numpy 1.26.4 / transformers 4.51.3 / protobuf 4.25）
  與主專案（numpy 2.4.6 / transformers 4.57.6 / protobuf 6.33.4）衝突，
  所以用 --system-site-packages venv 隔離（繼承系統 torch 2.6.0+cu124，免重裝 2.4GB），
  以「localhost HTTP 服務」形式給 tts_router 呼叫（跟 edge 同模式：拿 bytes 就走）。

啟動（用 venv 的 python，不是系統 python）：
  venvs\\cosyvoice\\Scripts\\python.exe services\\cosyvoice_server.py --port 9881

端點：
  GET  /health          → {"ok":true,"model":...,"sample_rate":...,"ref":...}
  POST /tts             body: {"text": "...", "speed": 1.0}  → audio/wav bytes
  POST /tts             失敗回 JSON {"ok":false,"error":"..."}（HTTP 500）
"""
import argparse
import io
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ai_vtuber
COSY_SRC = os.path.join(ROOT, "third_party", "CosyVoice")
MATCHA = os.path.join(COSY_SRC, "third_party", "Matcha-TTS")
DEFAULT_MODEL = os.path.join(ROOT, "models", "cosyvoice", "Fun-CosyVoice3-0.5B")
# 參考音檔（zero-shot 條件音）：優先模型目錄 asset，再退到 repo 範例
REF_CANDIDATES = [
    os.getenv("COSYVOICE_REF_WAV") or "",
    os.path.join(DEFAULT_MODEL, "asset", "zero_shot_prompt.wav"),
    os.path.join(COSY_SRC, "asset", "zero_shot_prompt.wav"),
    os.path.join(COSY_SRC, "asset", "cross_lingual_prompt.wav"),
]
# 參考音稿（zero_shot 需要；拿不到就改走 cross_lingual，不需要音稿）
# ⚠️ CosyVoice3 硬性要求 prompt_text 帶 <|endofprompt|> 指令前綴，否則 LLM 內部
#    assert 會炸（"…not detected in CosyVoice3 text or prompt_text"）→ 只生成 3 個
#    語音 token → 下游 f0_predictor conv1d kernel4 > input3 崩潰。
REF_TEXT = (os.getenv("COSYVOICE_REF_TEXT") or
            "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。")
SYNTH_TIMEOUT = float(os.getenv("COSYVOICE_SYNTH_TIMEOUT") or "60")

_model = None
_info = {"ok": False}


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def find_ref():
    for p in REF_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    # 最後手段：模型目錄下任何 wav
    for base in (DEFAULT_MODEL, COSY_SRC):
        for dirpath, _, files in os.walk(base):
            for f in files:
                if f.lower().endswith(".wav"):
                    return os.path.join(dirpath, f)
    return None


def load_model():
    global _model, _info
    sys.path.insert(0, COSY_SRC)
    sys.path.insert(0, MATCHA)
    model_dir = os.getenv("COSYVOICE_MODEL_DIR") or DEFAULT_MODEL
    if not os.path.isdir(model_dir):
        raise RuntimeError(f"模型目錄不存在: {model_dir}")

    t0 = time.time()
    # CosyVoice3 用 AutoModel（自動挑對的類別）；舊版回 CosyVoice
    try:
        from cosyvoice.cli.cosyvoice import AutoModel
        _model = AutoModel(model_dir=model_dir)
    except Exception as e:
        _log(f"[CosyVoice] AutoModel 失敗（{e}），回退 CosyVoice 類別")
        from cosyvoice.cli.cosyvoice import CosyVoice
        _model = CosyVoice(model_dir=model_dir)
    dt = time.time() - t0

    ref = find_ref()
    _info = {"ok": True, "model_dir": model_dir, "load_sec": round(dt, 1),
             "ref": ref, "sample_rate": getattr(_model, "sample_rate", 24000)}
    _log(f"[CosyVoice] 模型載入完成 {dt:.1f}s  sr={_info['sample_rate']}  ref={ref}")
    return _model


def synth(text: str, speed: float = 1.0) -> bytes:
    """回傳 WAV bytes（單一 chunk 拼接）"""
    if not _model:
        raise RuntimeError("模型尚未載入")
    ref = _info.get("ref")
    if not ref:
        raise RuntimeError("找不到參考音檔（zero-shot 條件音）")

    import torchaudio
    chunks = []
    # ⚠️ 只走 zero_shot：CosyVoice3 的 cross_lingual 不會注入 <|endofprompt|> 前綴，
    #    會讓 LLM 內部 assert 失敗（且生成器卡死、請求掛起）。自訂參考音檔請一併設
    #    COSYVOICE_REF_TEXT（該音檔的逐字稿）。
    it = _model.inference_zero_shot(text, REF_TEXT, ref, stream=True)

    # ⚠️ 守衛：模型內部執行緒若斷言失敗，生成器會永遠卡住（實測會掛死請求）。
    #    丟到執行緒跑 + 逾時，確保 HTTP 層一定拿得到結果或明確錯誤。
    def _consume(gen):
        out = []
        for seg in gen:
            out.append(seg["tts_speech"])
        return out

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_consume, it)
        try:
            chunks = fut.result(timeout=SYNTH_TIMEOUT)
        except FuturesTimeout:
            fut.cancel()
            raise RuntimeError(f"合成逾時（>{SYNTH_TIMEOUT}s），可能模型內部執行緒已掛")
    if not chunks:
        raise RuntimeError("模型回傳空白")
    import torch
    # 版型注意：CosyVoice yield 的 tts_speech 是 (1, T) —— 時間軸在 dim1！
    # （cat dim=0 會因 T 不同直接報錯；誤當 (T,C) 轉置會變多聲道壞檔）
    full = torch.cat(chunks, dim=1)              # (1, T1)+(1, T2)+… → (1, T_total)
    if speed and abs(speed - 1.0) > 1e-3:
        t = full.shape[1]
        idx = (torch.arange(int(t / speed)) * speed).long().clamp(max=t - 1)
        full = full[:, idx]
    buf = io.BytesIO()
    # 存成 PCM_SIGNED 16-bit：float32 WAV 相容性差（speech_recognition/部分播放器讀不了）
    wav16 = (full.clamp(-1.0, 1.0) * 32767.0).to(torch.int16)
    torchaudio.save(buf, wav16, _info["sample_rate"], format="WAV")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):          # 靜音存取 log
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._json({"ok": _info.get("ok", False), **_info})
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/tts"):
            return self._json({"ok": False, "error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            text = (data.get("text") or "").strip()
            speed = float(data.get("speed") or 1.0)
            if not text:
                return self._json({"ok": False, "error": "text 為空"}, 400)
            t0 = time.time()
            wav = synth(text, speed)
            dt = time.time() - t0
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.send_header("X-Synth-Sec", f"{dt:.2f}")
            self.end_headers()
            self.wfile.write(wav)
        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("COSYVOICE_PORT") or "9881"))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    _log(f"[CosyVoice] 載入模型中… (venv={os.path.basename(os.path.dirname(sys.executable))})")
    try:
        load_model()
    except Exception as e:
        _log(f"[CosyVoice] 模型載入失敗：{type(e).__name__}: {e}")
        traceback.print_exc()
        # 仍然起服務（health 回 ok:false），讓 tts_router 明確看到「服務在但模型沒好」

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    _log(f"[CosyVoice] 服務就緒 http://{args.host}:{args.port}  (health=/health, tts=POST /tts)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
