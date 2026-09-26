# -*- coding: utf-8 -*-
"""
test_live_vision.py
Gemini Live API - 螢幕共享 + 即時語音對話（自動重連版）
Model: gemini-3.1-flash-live-preview
"""
import sys, io as _io, os, re, queue, threading, time, asyncio
import numpy as np

# 強制 UTF-8 輸出
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8","utf8"):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import mss, pyaudio, sounddevice as sd
from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ── 0. 金鑰 ────────────────────────────────────────────
load_dotenv()
_raw = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_KEYS = [k.strip() for k in re.split(r"[\s,;]+", _raw) if k.strip()]
if not GEMINI_KEYS:
    print("[錯誤] .env 中找不到 GEMINI_API_KEYS")
    sys.exit(1)
API_KEY = GEMINI_KEYS[0]
print(f"[OK] 金鑰: {API_KEY[:8]}…{API_KEY[-4:]}")

# ── 1. 設定 ─────────────────────────────────────────────
MODEL          = "gemini-3.1-flash-live-preview"
SCREEN_FPS     = 1.0
SCREEN_QUALITY = 40
SCREEN_W, SCREEN_H = 1280, 720
MIC_RATE   = 16000
MIC_CHUNK  = 1024
SPEAKER_RATE = 24000

# ── 2. 截圖 ─────────────────────────────────────────────
def capture_screen_jpeg() -> bytes:
    with mss.MSS() as sct:
        raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    img = img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", quality=SCREEN_QUALITY)
    return buf.getvalue()

# ── 3. 主程式 ────────────────────────────────────────────
async def main():
    client = genai.Client(api_key=API_KEY)
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(parts=[types.Part(text=(
            "你是一個好奇、友善的 AI 助理。"
            "你能即時看到使用者的螢幕畫面，並用繁體中文對話。"
            "當畫面有有趣內容時，可以主動說出觀察。"
        ))]),
    )

    # ── 共用資源（跨 session 存活）─────────────────────
    audio_q: queue.Queue = queue.Queue()
    frame_q: asyncio.Queue = asyncio.Queue(maxsize=2)
    mic_q:   asyncio.Queue = asyncio.Queue(maxsize=20)

    def audio_player():
        buf = b""
        chunk_bytes = (SPEAKER_RATE // 10) * 2
        while True:
            try:
                data = audio_q.get(timeout=0.5)
                if data is None: break
                buf += data
                while len(buf) >= chunk_bytes:
                    chunk, buf = buf[:chunk_bytes], buf[chunk_bytes:]
                    arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                    sd.play(arr, samplerate=SPEAKER_RATE, blocking=True)
            except queue.Empty:
                continue

    threading.Thread(target=audio_player, daemon=True).start()

    pa = pyaudio.PyAudio()
    print(f"[麥克風] {pa.get_default_input_device_info()['name']}")
    stream = pa.open(format=pyaudio.paInt16, channels=1,
                     rate=MIC_RATE, input=True, frames_per_buffer=MIC_CHUNK)

    async def screen_loop():
        loop = asyncio.get_event_loop()
        while True:
            try:
                jpeg = await loop.run_in_executor(None, capture_screen_jpeg)
                if frame_q.full():
                    try: frame_q.get_nowait()
                    except: pass
                await frame_q.put(jpeg)
            except Exception as e:
                print(f"[截圖錯誤] {e}")
            await asyncio.sleep(1.0 / SCREEN_FPS)

    async def mic_loop():
        loop = asyncio.get_event_loop()
        while True:
            try:
                pcm = await loop.run_in_executor(None, stream.read, MIC_CHUNK, False)
                if mic_q.full():
                    try: mic_q.get_nowait()
                    except: pass
                await mic_q.put(pcm)
            except Exception as e:
                print(f"[麥克風錯誤] {e}")
                await asyncio.sleep(0.05)

    # 截圖與麥克風只啟動一次
    asyncio.create_task(screen_loop())
    asyncio.create_task(mic_loop())

    async def send_loop(session):
        screen_timer = mic_timer = 0.0
        screen_iv = 1.0 / SCREEN_FPS
        mic_iv    = MIC_CHUNK / MIC_RATE   # ≈ 0.064s
        while True:
            now = time.monotonic()
            if now - screen_timer >= screen_iv:
                try:
                    jpeg = frame_q.get_nowait()
                    await session.send_realtime_input(
                        video=types.Blob(data=jpeg, mime_type="image/jpeg"))
                    screen_timer = now
                except asyncio.QueueEmpty:
                    pass
            if now - mic_timer >= mic_iv:
                try:
                    pcm = mic_q.get_nowait()
                    await session.send_realtime_input(
                        audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
                    mic_timer = now
                except asyncio.QueueEmpty:
                    pass
            await asyncio.sleep(0.01)

    async def recv_loop(session):
        started = False
        async for response in session.receive():
            sc = response.server_content
            if not sc: continue
            if sc.model_turn:
                for part in sc.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        audio_q.put(part.inline_data.data)
            if sc.input_transcription and sc.input_transcription.text:
                if started: print(); started = False
                print(f"\n[你說] {sc.input_transcription.text}")
            if sc.output_transcription and sc.output_transcription.text:
                if not started:
                    print("[Gemini] ", end="", flush=True)
                    started = True
                print(sc.output_transcription.text, end="", flush=True)
            if sc.turn_complete:
                if started: print(); started = False
            if sc.interrupted:
                print("\n[打斷]" if started else "[打斷]")
                started = False
                while not audio_q.empty():
                    try: audio_q.get_nowait()
                    except: break

    # ── 自動重連迴圈 ──────────────────────────────────
    sno = 0
    while True:
        sno += 1
        print(f"\n{'='*55}")
        print(f"  Gemini Live Vision | {MODEL}")
        print(f"  螢幕: {SCREEN_FPS} FPS | {SCREEN_W}x{SCREEN_H} | q={SCREEN_QUALITY}")
        print(f"  Session #{sno} | Ctrl+C 結束")
        print(f"{'='*55}\n")
        try:
            async with client.aio.live.connect(model=MODEL, config=config) as session:
                print(f"[連線成功] Session #{sno} 開始...")
                try:
                    recv_task = asyncio.create_task(recv_loop(session))
                    send_task = asyncio.create_task(send_loop(session))
                    try:
                        await recv_task   # recv 結束（正常或異常）→ 觸發重連
                    finally:
                        send_task.cancel()
                        try: await send_task
                        except asyncio.CancelledError: pass

                except Exception as e:
                    err = str(e)
                    if "ping timeout" in err or "keepalive" in err or "1011" in err:
                        print(f"\n[Session #{sno} 超時] 2 分鐘限制到了，3 秒後自動重連...")
                    else:
                        print(f"\n[Session #{sno} 中斷] {type(e).__name__}: {err[:80]}")
        except Exception as e:
            print(f"\n[連線失敗] {type(e).__name__}: {e}")
            print("5 秒後重試...")
            await asyncio.sleep(5)
            continue

        # 清空舊 session 殘留音訊
        while not audio_q.empty():
            try: audio_q.get_nowait()
            except: break

        await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止 Live Vision。")
    except Exception as e:
        print(f"\n[啟動失敗] {e}")
