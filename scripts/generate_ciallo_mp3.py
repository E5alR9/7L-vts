# -*- coding: utf-8 -*-
import os, sys, subprocess

# 加入主工作目錄
sys.path.insert(0, r"C:\Users\qiwai")

import local_xiaoyi_service

def test_synthesis():
    test_text = "Ciallo～(∠・ω<)⌒★ 老爸好！今天也是充滿元氣的一天呢！"
    print(f"正在合成音訊，文本: {test_text}")
    
    wav_bytes = local_xiaoyi_service.synthesize_xiaoyi_bytes(test_text)
    if not wav_bytes:
        print("❌ 合成失敗，未取得音訊資料！")
        return False
    
    wav_path = r"C:\Users\qiwai\ciallo_test.wav"
    mp3_path = r"C:\Users\qiwai\ciallo_test.mp3"
    
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)
    print(f"✅ WAV 已儲存至: {wav_path} ({len(wav_bytes)} bytes)")
    
    # 轉為高品質 MP3
    cmd = ["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", mp3_path]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode == 0:
        print(f"🎉 成功轉換為高品質 MP3: {mp3_path}")
        return True
    else:
        print(f"❌ 轉換 MP3 失敗: {res.stderr.decode('utf-8', errors='ignore')}")
        return False

if __name__ == "__main__":
    test_synthesis()
