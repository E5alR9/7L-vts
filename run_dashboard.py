import asyncio
import os
import sys
import threading
from dotenv import load_dotenv

load_dotenv()

# 將當前目錄加入 sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import services.web_dashboard as wd
import services.tiktok_listener as tk_listener

async def main():
    print("=========================================")
    print("🌟 7L AI-VTuber Web Dashboard (獨立預覽/監控模式)")
    print("=========================================")

    dummy_queue = asyncio.Queue()

    is_sleeping = False
    mock_api_calls = 3

    # 🎧 電腦全系統聲音 (WASAPI Loopback) 即時音量採樣
    real_sys_vol = 0
    def _preview_loopback_sampler():
        nonlocal real_sys_vol
        try:
            import soundcard as sc
            import numpy as np
            sp = sc.default_speaker()
            mic = sc.get_microphone(id=str(sp.name), include_loopback=True)
            with mic.recorder(samplerate=16000, blocksize=1280) as rec:
                while True:
                    chunk = rec.record(numframes=1280)
                    rms = float(np.sqrt(np.mean(np.square(chunk))))
                    real_sys_vol = min(100, int((rms / 0.16) * 100)) if rms > 0.003 else 0
        except Exception:
            pass

    threading.Thread(target=_preview_loopback_sampler, daemon=True).start()

    def get_preview_state():
        nonlocal is_sleeping, mock_api_calls
        calc_energy = max(5.0, round(100.0 - (mock_api_calls * 0.4), 1))
        if is_sleeping:
            return {
                "ai_status": "😴 閉眼沉睡中 (0 API 消耗)",
                "ai_state": "sleep",
                "is_sleeping": True,
                "mic_action": "已暫停",
                "is_mic_enabled": False,
                "mic_volume": 0.0,
                "model_name": "Gemini 3.8 Flash (Tier-7)",
                "api_calls": mock_api_calls,
                "api_energy": calc_energy,
                "vts_expression": "閉眼安睡",
                "screen_context": "7L 正在閉眼沉睡休息中，已暫停畫面視覺掃描以節省額度。",
                "last_vision_time": 0,
                "audio_perception": {
                    "status_text": "休眠暫停中",
                    "sys_tag": "休眠靜音",
                    "sys_detail": "休眠中未主動監聽電腦聲音。",
                    "sys_level": 0,
                    "real_tag": "休眠暫停",
                    "real_detail": "7L 正在睡覺，已暫停接收現實人聲。",
                    "real_level": 0,
                    "user_speaking": ""
                }
            }
        return {
            "ai_status": "🟢 正常運作中",
            "ai_state": "idle",
            "is_sleeping": False,
            "mic_action": "待命",
            "is_mic_enabled": True,
            "mic_volume": 0.22,
            "model_name": "Gemini 3.8 Flash (Tier-7)",
            "api_calls": mock_api_calls,
            "api_energy": calc_energy,
            "vts_expression": "自然",
            "screen_context": "我看到老爸正在監控台進行設定與畫面瀏覽。",
            "last_vision_time": 0,
            "audio_perception": {
                "status_text": "電腦全系統音訊監聽中" if real_sys_vol > 5 else "雙向全雙工監聽",
                "sys_tag": "全系統音訊播放中" if real_sys_vol > 5 else "安靜無聲",
                "sys_detail": "電腦正在播放全系統音訊（影片/音樂/遊戲/鋼琴）" if real_sys_vol > 5 else "電腦目前無音訊輸出（全系統聲音安靜）。",
                "sys_level": real_sys_vol,
                "real_tag": "靈敏傾聽中",
                "real_detail": "老爸剛剛說：『7L 今天過得如何？』",
                "real_level": 28,
                "user_speaking": "7L 今天過得如何？"
            }
        }

    async def set_sleep_preview(enable: bool):
        nonlocal is_sleeping
        is_sleeping = bool(enable)
        if is_sleeping:
            print("🌙 7L 進入深層睡眠模式（眼睛已安詳閉合，0 API 消耗，安靜沉睡中...）")
        else:
            print("☀️ 7L 已被喚醒（雙眼睜開，恢復正常待命）！")
        return is_sleeping

    # 載入真實記憶
    real_memories = []
    mem_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "unified_memory.json")
    if os.path.exists(mem_file):
        try:
            import json
            with open(mem_file, "r", encoding="utf-8") as f:
                real_memories = json.load(f)
        except Exception:
            pass

    # 螢幕畫面感知 (採用 Windows GDI 硬件級 StretchBlt 極速截圖，100% 成功抓取真實桌面)
    def get_preview_screen_image():
        try:
            import ctypes
            from PIL import Image
            import io
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            target_w = 960
            target_h = int(h * (target_w / max(1, w)))

            hdesk = user32.GetDesktopWindow()
            desk_dc = user32.GetWindowDC(hdesk)
            img_dc = gdi32.CreateCompatibleDC(desk_dc)
            mem_bmp = gdi32.CreateCompatibleBitmap(desk_dc, target_w, target_h)
            gdi32.SelectObject(img_dc, mem_bmp)
            gdi32.SetStretchBltMode(img_dc, 4) # HALFTONE
            gdi32.StretchBlt(img_dc, 0, 0, target_w, target_h, desk_dc, 0, 0, w, h, 0x00CC0020)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_int32), ('biHeight', ctypes.c_int32),
                    ('biPlanes', ctypes.c_uint16), ('biBitCount', ctypes.c_uint16), ('biCompression', ctypes.c_uint32),
                    ('biSizeImage', ctypes.c_uint32), ('biXPelsPerMeter', ctypes.c_int32), ('biYPelsPerMeter', ctypes.c_int32),
                    ('biClrUsed', ctypes.c_uint32), ('biClrImportant', ctypes.c_uint32)
                ]
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = target_w
            bmi.biHeight = -target_h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0
            buf = ctypes.create_string_buffer(target_w * target_h * 4)
            gdi32.GetDIBits(img_dc, mem_bmp, 0, target_h, buf, ctypes.byref(bmi), 0)
            screenshot = Image.frombuffer('RGBA', (target_w, target_h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
            gdi32.DeleteObject(mem_bmp)
            gdi32.DeleteDC(img_dc)
            user32.ReleaseDC(hdesk, desk_dc)

            out_buf = io.BytesIO()
            screenshot.save(out_buf, format="JPEG", quality=75)
            return out_buf.getvalue()
        except Exception as e:
            return None

    # 初始化示範工具調用紀錄
    wd.record_tool_call("pe.play_virtual_piano", {"song_name": "鐘", "force_online": False}, "已載入 MIDI 並開始演奏《鐘》", caller="7L (大腦自主)", duration_ms=45.2)
    wd.record_tool_call("trigger_vts_expression", {"expression_name": "害羞臉紅"}, "已切換表情至害羞臉紅", caller="7L (大腦自主)", duration_ms=12.8)
    wd.record_tool_call("set_timer", {"seconds": 300, "message": "記得站起來伸個懶腰"}, "計時器已啟動", caller="老爸 (手動調用)", duration_ms=8.5)

    async def mock_execute_tool(tool_name: str, args: dict):
        await asyncio.sleep(0.35)
        if "play_virtual_piano" in tool_name:
            return f"模擬演奏成功：已為老爸播放《{args.get('song_name', '鐘')}》"
        elif "compose_and_play" in tool_name:
            return f"模擬作曲成功：已為老爸即興創作《{args.get('theme_or_title', '原創曲')}》（風格：{args.get('mood_or_style', '治癒')}）"
        elif "trigger_vts" in tool_name:
            return f"模擬表情切換成功：已切換至「{args.get('expression_name', '自然')}」"
        elif "move_spatial" in tool_name:
            return f"模擬模型移動成功：已位移至「{args.get('target_position', '正中間')}」"
        elif "instrument" in tool_name:
            return f"模擬音色切換成功：已切換為「{args.get('instrument', '鋼琴')}」"
        elif "speed" in tool_name:
            return f"模擬速度調整成功：已設為 {args.get('speed', 1.0)}x"
        elif "volume" in tool_name:
            return f"模擬音量調整成功：已設為 {args.get('volume', 85)}%"
        elif "timer" in tool_name:
            return f"模擬鬧鐘成功：已設定 {args.get('seconds', 60)} 秒提醒"
        elif "update_cloud_knowledge" in tool_name:
            return f"模擬寫入雲端大腦成功：[{args.get('category')}] {args.get('content')}"
        elif "python" in tool_name:
            return "模擬執行 Python 成功：執行耗時 18ms，輸出無異常"
        else:
            return f"工具 {tool_name} 執行成功！參數: {json.dumps(args, ensure_ascii=False)}"

    await wd.start_web_dashboard(
        port=7860,
        input_queue=dummy_queue,
        vts=None,
        get_system_state_cb=get_preview_state,
        set_mic_cb=lambda enable: True,
        set_sleep_cb=set_sleep_preview,
        trigger_expression_cb=None,
        get_memory_cb=lambda: real_memories,
        get_mind_board_cb=lambda: [{"text": "7L 正在待命，歡迎老爸開啟直播或麥克風！"}],
        get_last_vision_image_cb=get_preview_screen_image,
        execute_tool_cb=mock_execute_tool
    )

    # 模擬後台處理輸入 (若在睡覺中，收到喚醒即醒來)
    async def dummy_input_consumer():
        nonlocal is_sleeping, mock_api_calls
        while True:
            item = await dummy_queue.get()
            txt = item.get("text", "")
            if is_sleeping:
                # 🌙 已停用語言喚醒，休眠中忽略所有文字與語音，僅限點擊按鈕喚醒
                continue
            else:
                if any(w in txt for w in ["睡覺", "去睡吧", "去睡覺", "晚安", "/sleep"]):
                    await set_sleep_preview(True)
                else:
                    # 模擬 7L 語音回覆老爸
                    mock_api_calls += 1
                    await asyncio.sleep(0.4)
                    wd.broadcast_event("ai_thought", {"thought": f"老爸跟我說了「{txt}」，我得好好回應他！"})
                    await asyncio.sleep(0.4)
                    wd.broadcast_event("ai_speech", {"text": f"老爸，我有聽到你說「{txt}」喔！"})

    asyncio.create_task(dummy_input_consumer())

    # 背景獨立監聽 TikTok 直播間巡檢
    asyncio.create_task(tk_listener.tiktok_live_worker(dummy_queue))

    # 保持運行
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 儀表板已關閉")
