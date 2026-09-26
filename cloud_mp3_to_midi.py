# -*- coding: utf-8 -*-
"""
🌐 YouTube & 音訊轉 MIDI 轉錄中樞 (Audio & YouTube to MIDI Pipeline)
功能：
1. 自動將 YouTube 鋼琴/原曲音訊下載為高取樣率音訊。
2. 調用【諧波泛音消除 + 基頻顯著性】高精度轉錄引擎，產出標準 88 鍵雙手 MIDI 樂譜。
3. 自動消除 2x~5x 泛音雜音，符合人類 10 指彈奏生理限制，零鬼音！
"""

import os
import sys
import time
import re
import audio_to_piano_midi

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def convert_youtube_via_cloud_mp3_to_midi(video_url: str, output_midi_path: str) -> bool:
    """完整管線：YouTube ➔ 高音質音訊 ➔ 諧波泛音消除 AI 轉錄 ➔ 88 鍵 MIDI"""
    try:
        return audio_to_piano_midi.convert_youtube_to_piano_midi(video_url, output_midi_path)
    except Exception as e:
        print(f"⚠️ [YouTube 轉錄異常]: {e}")
        return False

def download_yt_and_convert_to_midi(video_url: str, output_dir: str = r"c:\Users\qiwai\midi_sheets", filename_hint: str = "") -> str:
    """下載 YouTube 並調用 AI 轉錄為 88 鍵 MIDI，回傳 MIDI 檔案路徑"""
    os.makedirs(output_dir, exist_ok=True)
    if not filename_hint:
        m = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', video_url)
        vid_id = m.group(1) if m else str(int(time.time()))
        filename_hint = f"yt_{vid_id}"
    clean_name = re.sub(r'[\\/*?:"<>|]', '', filename_hint).strip()
    out_midi = os.path.join(output_dir, f"{clean_name}.mid")
    ok = convert_youtube_via_cloud_mp3_to_midi(video_url, out_midi)
    if ok and os.path.exists(out_midi) and os.path.getsize(out_midi) > 100:
        return out_midi
    return ""

if __name__ == "__main__":
    test_link = "https://www.youtube.com/watch?v=7Ug1aw95-wQ"
    out_m = r"c:\Users\qiwai\midi_sheets\test_huahai_verify.mid"
    res = download_yt_and_convert_to_midi(test_link, filename_hint="周杰倫_花海_鋼琴版")
    print("Downloaded MIDI path:", res)
