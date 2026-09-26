#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
==============================================================================
🎙️ 老爸專屬「純淨人聲聲紋錄製與校準工具」 (record_clean_dad_voiceprint.py)
==============================================================================
說明：
  本工具用於錄製老爸乾淨無雜音的真實人聲樣本（排除電視、遊戲、7L 回音等干擾）。
  自動提煉 256 維高品質 WeSpeaker 特徵向量並建立專屬聲紋基準庫。
  錄製完成後會立即備份舊檔並更新 data/dad_voiceprint.npy，
  運作中的 7L 主程式 (vts_7L_test.py) 會透過毫秒級熱重載機制立即生效，無需重開機！
==============================================================================
"""

import os
import sys
import time
import shutil
import wave
import io
import datetime
import numpy as np

# 設置控制台 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import sounddevice as sd
except ImportError:
    print("❌ 請先安裝 sounddevice: pip install sounddevice")
    sys.exit(1)

from mic_live_plugin.voiceprint_verifier import voiceprint_verifier

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
VOICEPRINT_FILE = os.path.join(DATA_DIR, "dad_voiceprint.npy")
CLEAN_SAMPLES_DIR = os.path.join(DATA_DIR, "clean_voice_samples")
SAMPLE_RATE = 16000  # 16kHz 單聲道為 WeSpeaker 標準規格

# 推薦朗讀語句（涵蓋老爸日常說話、問句、感嘆句、點歌指令等不同語氣與完整母音）
PROMPT_SENTENCES = [
    ("7L，今天晚上要吃什麼好料？", "（日常輕鬆語氣，自然自然說出即可）"),
    ("七仔，幫我彈一首卡農來聽聽！", "（指令語氣，可測試 7L 點歌與鋼琴執行）"),
    ("阿七，妳剛才在想什麼？說給我聽聽。", "（疑問關心語氣，覆蓋「ㄚ、ㄧ、ㄨ」等核心母音）"),
    ("喂，7L，今天直播間看起來挺熱鬧的喔！", "（感嘆與讚賞語氣，音調略為上揚）"),
    ("七仔，你有沒有看到我的滑鼠跑到哪裡去了？", "（日常尋物語氣，平穩自然互動）"),
    ("好啦，那妳先去鋼琴旁邊彈琴吧。", "（引導走位與動作語氣）"),
]


def print_banner():
    print("=" * 66)
    print(" 🎙️  7L 專屬老爸純淨人聲聲紋錄音與校準工具 (Threshold: 70%)")
    print("=" * 66)
    print("💡 目的：錄製 3~4 句乾淨老爸人聲，徹底排除 7L 女聲與遊戲雜音干擾！")
    print("💡 特色：錄完立即熱更新到運行中的 7L 系統，免重開機即刻生效！")
    print("=" * 66)
    print()


def select_input_device():
    """列出可用麥克風設備並提供選擇"""
    devices = sd.query_devices()
    input_devs = [(idx, d) for idx, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
    
    default_dev_idx = sd.default.device[0]
    default_name = "未知"
    if 0 <= default_dev_idx < len(devices):
        default_name = devices[default_dev_idx].get("name", "預設")

    print(f"🎙️ 目前系統預設錄音設備: [{default_dev_idx}] {default_name}")
    print("   直接按 [Enter] 使用預設設備，或輸入 'list' 檢視所有麥克風：", end="")
    choice = input().strip()
    
    if choice.lower() == "list":
        print("\n--- 可用錄音麥克風清單 ---")
        for idx, dev in input_devs:
            mark = " (系統預設)" if idx == default_dev_idx else ""
            print(f" [{idx}] {dev['name']}{mark}")
        print("請輸入欲使用的設備編號 (直接按 Enter 使用預設): ", end="")
        dev_in = input().strip()
        if dev_in.isdigit() and any(idx == int(dev_in) for idx, _ in input_devs):
            return int(dev_in)
    elif choice.isdigit() and any(idx == int(choice) for idx, _ in input_devs):
        return int(choice)

    return default_dev_idx


def test_microphone_level(device_idx: int, duration_sec: float = 3.0):
    """麥克風測試與動態音量條"""
    print(f"\n🔊 [麥克風測試] 請隨意發出聲音，確認收音是否正常 (測試 {int(duration_sec)} 秒)...")
    block_len = int(SAMPLE_RATE * 0.1)  # 100ms
    num_blocks = int(duration_sec * 10)
    
    max_peak = 0.0
    for _ in range(num_blocks):
        audio_chunk = sd.rec(block_len, samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=device_idx)
        sd.wait()
        peak = float(np.max(np.abs(audio_chunk)))
        if peak > max_peak:
            max_peak = peak
        # 繪製動態音量長條圖
        bars = int(peak * 50)
        bars_str = "█" * min(bars, 40)
        print(f"\r  音量強度: [{bars_str:<40}] Peak: {peak:.2f}", end="", flush=True)
    print()

    if max_peak < 0.02:
        print("⚠️ 警告：收音音量極小或無聲！請確認麥克風靜音開關或 Windows 隱私權設定。")
    else:
        print("✅ 麥克風收音良好！準備就緒。")
    print()


def record_clip(prompt_text: str, hint: str, clip_idx: int, device_idx: int, duration_sec: float = 4.5) -> np.ndarray:
    """單句引導錄音"""
    print(f"------------------------------------------------------------------")
    print(f"📝 [第 {clip_idx} 句] 請朗讀以下句子：")
    print(f"👉 「\033[1;36m{prompt_text}\033[0m」 {hint}")
    print(f"------------------------------------------------------------------")
    print("準備好後，按 [Enter] 開始 3 秒倒數計時...", end="")
    input()

    for i in [3, 2, 1]:
        print(f"⏱️ {i} ...", flush=True)
        time.sleep(0.9)

    print(f"🔴 【開始錄音】請自然朗讀！（錄製 {duration_sec} 秒）", flush=True)
    
    # 開始錄製
    rec_samples = int(SAMPLE_RATE * duration_sec)
    audio = sd.rec(rec_samples, samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=device_idx)
    
    # 錄音時顯示倒數進度
    steps = int(duration_sec * 4)
    step_time = duration_sec / steps
    for s in range(steps):
        time.sleep(step_time)
        pct = int((s + 1) / steps * 100)
        progress = "▓" * int(pct / 5)
        print(f"\r  錄音中: [{progress:<20}] {pct}%", end="", flush=True)
    sd.wait()
    print("\n⏹️ 【錄音結束】")

    audio = audio.flatten()
    peak = float(np.max(np.abs(audio)))
    print(f"📊 本次錄音最大音量: {peak:.2f}")
    if peak < 0.03:
        print("⚠️ 聲音較小，建議靠麥克風近一點重新錄製。")
    return audio


def save_audio_to_wav(audio: np.ndarray, file_path: str):
    """保存音訊為標準 16kHz 16-bit PCM WAV"""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    int16_data = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_data.tobytes())


def main():
    print_banner()

    if not voiceprint_verifier.is_initialized:
        print("❌ 聲紋引擎 (sherpa-onnx / WeSpeaker) 未正常初始化，無法提取特徵。")
        input("按 Enter 結束...")
        return

    device_idx = select_input_device()
    test_microphone_level(device_idx)

    os.makedirs(CLEAN_SAMPLES_DIR, exist_ok=True)

    recorded_audios = []
    recorded_embs = []
    clip_files = []

    print("🎙️ 我們即將錄製 3~4 句純淨的老爸人聲語音。")
    print("請保持房間環境安靜，關閉背景音樂或影片聲。\n")

    for idx, (sentence, hint) in enumerate(PROMPT_SENTENCES, 1):
        while True:
            audio = record_clip(sentence, hint, idx, device_idx, duration_sec=4.5)
            
            # 臨時保存並計算 embedding
            temp_path = os.path.join(CLEAN_SAMPLES_DIR, f"clean_dad_prompt_{idx}.wav")
            save_audio_to_wav(audio, temp_path)
            
            emb = voiceprint_verifier.compute_embedding(temp_path)
            if emb is None:
                print("❌ 特徵提取失敗（可能無聲或音訊無效），按 [Enter] 重新錄製本句...", end="")
                input()
                continue
            
            print("✅ 成功提煉 256 維高精度聲紋特徵向量！")
            print("滿意請按 [Enter] 繼續下一句；若想重錄本句請輸入 'r' 後按 Enter：", end="")
            choice = input().strip().lower()
            if choice == "r":
                print("🔄 重新錄製本句...")
                continue
            
            recorded_audios.append(audio)
            recorded_embs.append(emb)
            clip_files.append(temp_path)
            print()
            break

        if idx >= 3:
            print(f"✨ 已完成 {idx} 句錄音！想要再多錄 1 句以求更全面嗎？ (輸入 'y' 繼續錄製，直接按 Enter 完成): ", end="")
            more = input().strip().lower()
            if more != "y":
                break

    if len(recorded_embs) < 2:
        print("⚠️ 錄製樣本不足 2 筆，無法進行交叉驗證。")
        return

    # 一致性交叉計算
    print("\n==================================================================")
    print("🔍 [聲紋品質與特徵一致性分析]")
    print("==================================================================")
    matrix = np.zeros((len(recorded_embs), len(recorded_embs)))
    similarities = []
    for i in range(len(recorded_embs)):
        for j in range(len(recorded_embs)):
            sim = float(np.dot(recorded_embs[i], recorded_embs[j]))
            matrix[i, j] = sim
            if i < j:
                similarities.append(sim)
                print(f"  樣本 {i+1} 與 樣本 {j+1} 語音相似度: {sim:.4f}")

    avg_sim = np.mean(similarities) if similarities else 0.0
    print(f"\n🌟 平均特徵一致度 (Cosine Similarity): {avg_sim:.4f}")
    if avg_sim >= 0.75:
        print("🏆 評級: 【極優】人聲特徵純淨穩定，能精準與 7L 女聲及環境雜音完全區隔！")
    elif avg_sim >= 0.65:
        print("👍 評級: 【良好】特徵具備足夠代表性。")
    else:
        print("⚠️ 評級: 【偏低】各句聲音差異較大，建議檢查收音環境後重新校準。")

    # 備份舊聲紋檔
    if os.path.exists(VOICEPRINT_FILE):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(DATA_DIR, f"dad_voiceprint_backup_{ts}.npy")
        default_backup = os.path.join(DATA_DIR, "dad_voiceprint_backup.npy")
        try:
            shutil.copy2(VOICEPRINT_FILE, backup_file)
            shutil.copy2(VOICEPRINT_FILE, default_backup)
            print(f"\n💾 已將舊聲紋檔備份至: {os.path.basename(backup_file)}")
        except Exception as e:
            print(f"⚠️ 備份舊聲紋檔失敗: {e}")

    # 保存新聲紋特徵檔
    new_embs_array = np.array(recorded_embs, dtype=np.float32)
    np.save(VOICEPRINT_FILE, new_embs_array)
    print(f"🎉 成功寫入全新老爸純淨聲紋檔: {VOICEPRINT_FILE} ({len(recorded_embs)} 組基準特徵)！")

    # 觸發本機熱重載
    voiceprint_verifier.reload_voiceprint()
    print("⚡ 聲紋驗證器已完成熱重載！")
    print(f"🔒 聲紋過濾閾值目前設定為: 0.70 (70%)")

    # 即時實測環節
    print("\n==================================================================")
    print("🎯 [即時實測老爸聲紋辨識]")
    print("==================================================================")
    print("老爸，現在隨便說一句話來測試新的聲紋辨識效果吧！")
    print("按 [Enter] 開始 3 秒測試錄音...", end="")
    input()
    
    test_audio = sd.rec(int(SAMPLE_RATE * 3.5), samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=device_idx)
    for i in range(3, 0, -1):
        print(f"\r  請說話... (剩餘 {i} 秒)", end="", flush=True)
        time.sleep(1.0)
    sd.wait()
    print("\r  分析中...                                 ", end="", flush=True)
    
    test_wav_path = os.path.join(CLEAN_SAMPLES_DIR, "test_instant.wav")
    save_audio_to_wav(test_audio.flatten(), test_wav_path)
    
    is_dad, score = voiceprint_verifier.verify_is_dad(test_wav_path, threshold=0.70)
    print(f"\n\n🎯 實測聲紋得分: {score:.4f} (門檻: 0.70)")
    if is_dad:
        print(f"🟢 【老爸本人驗證通過！】（得分 {score:.2f} >= 0.70）")
        print("✨ 恭喜老爸！從現在起 7L 將精準辨識您的聲音，背景音樂、遊戲聲與 7L 自己的聲音都不會再誤觸！")
    else:
        print(f"🔴 【未能通過門檻】（得分 {score:.2f} < 0.70）")
        print("💡 提示：若平時發話距離麥克風較遠，可以隨時重新執行本腳本重新校準。")

    print("\n完成！按 Enter 退出。")
    input()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="老爸純淨人聲聲紋錄製與校準工具")
    parser.add_argument("--test", type=str, help="測試指定音訊檔之聲紋得分", default=None)
    parser.add_argument("--calibrate-dir", type=str, help="從指定目錄中的 WAV 建立基準聲紋", default=None)
    args = parser.parse_args()

    if args.test:
        if os.path.exists(args.test):
            is_dad, score = voiceprint_verifier.verify_is_dad(args.test, threshold=0.70)
            print(f"🎵 檔案: {args.test}")
            print(f"🎯 聲紋得分: {score:.4f} (門檻: 0.70) ➔ {'🟢 通過 (老爸本人)' if is_dad else '🔴 攔截 (非老爸或雜音)'}")
        else:
            print(f"❌ 找不到指定檔案: {args.test}")
    elif args.calibrate_dir:
        success = voiceprint_verifier.calibrate_from_directory(args.calibrate_dir)
        print("✅ 目錄校準完成！" if success else "❌ 校準失敗。")
    else:
        main()
