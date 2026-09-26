# -*- coding: utf-8 -*-
"""自舉生成情緒參考音：用曉伊自己的聲音念出每段情緒台詞，存成 ref wav。
為什麼不用 Edge TTS：GPT-SoVITS 的參考音同時決定「音色+情緒」，
拿微軟的聲音當 ref，7L 會被帶偏成別人的音色。自舉則音色零漂移。

用法（主環境，需顯卡/GPT-SoVITS 就緒）：python gen_emotion_refs.py
輸出：根目錄 xiaoyi_{ask,exclaim,soft,sad,annoyed}_ref.wav（單聲道 32kHz，對齊現有 ref）
"""
import os
import subprocess
import sys
import wave

BASE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = (r"C:\ffmpeg\bin\ffmpeg.exe"
          if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe") else "ffmpeg")


def to_ref_wav(raw_bytes: bytes, out_path: str) -> float:
    """mp3/wav bytes → 單聲道 16-bit 32kHz wav，回傳秒數"""
    tmp_in = out_path + ".tmp_in.bin"
    with open(tmp_in, "wb") as f:
        f.write(raw_bytes)
    cmd = [FFMPEG, "-y", "-v", "error", "-i", tmp_in,
           "-ac", "1", "-ar", "32000", "-sample_fmt", "s16", out_path]
    subprocess.run(cmd, check=True, timeout=60)
    os.remove(tmp_in)
    with wave.open(out_path, "rb") as w:
        secs = w.getnframes() / w.getframerate()
    return secs


def main():
    sys.path.insert(0, BASE)
    import local_xiaoyi_service as tts

    slots = tts.EMOTION_REF_VOICES
    print(f"共 {len(slots)} 段，開始自舉合成（會先載入 GPT-SoVITS，稍等）…")
    for emo, slot in slots.items():
        text = slot["text"]
        # emotion=None → 自動按標點判定，烘焙對應語氣進參考音
        data = tts.synthesize_xiaoyi_bytes(text)
        if not data or len(data) < 100:
            print(f"❌ [{emo}] 合成失敗，跳過")
            continue
        secs = to_ref_wav(bytes(data), slot["audio"])
        flag = "⚠️ 太短(<3s)，效果可能打折" if secs < 3.0 else "✅"
        print(f"{flag} [{emo}] {os.path.basename(slot['audio'])} "
              f"{secs:.1f}s ← 「{text}」")
    print("完成。重啟 vts_7L_test.py 即自動啟用（啟動日誌會顯示使用的 ref）。")


if __name__ == "__main__":
    main()
