# -*- coding: utf-8 -*-
"""
🎙️ 7L 本地 TTS 聲紋特徵提煉與練習中樞 (Train 7L Voiceprint from Local TTS)
- 提取本地 GPT-SoVITS 參考母帶 (xiaoyi_girl_ref.wav 等) 的 256 維聲紋 Embedding
- 可調用本地 TTS 產生不同語調之 7L 發音練習樣本
- 建立並儲存 data/7l_voiceprint.npy，讓 7L 即刻具備「辨識自身發言」能力
"""

import os
import sys
import glob
import numpy as np

# 確保路徑
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mic_live_plugin.voiceprint_verifier import voiceprint_verifier, safe_print

def train_7l_voiceprint(synthesize_new: bool = False):
    safe_print("=" * 60)
    safe_print("🎙️ 正在開始 7L 本地 TTS 聲紋特徵提煉與練習...")
    safe_print("=" * 60)

    # 1. 收集本地參考音檔母帶
    ref_files = [
        r"C:\Users\qiwai\xiaoyi_girl_ref.wav",
        r"C:\Users\qiwai\xiaoyi_ref.wav",
        r"C:\Users\qiwai\xiaoyi_japanese_ref.wav"
    ]
    existing_refs = [f for f in ref_files if os.path.exists(f)]
    safe_print(f"📁 找到 {len(existing_refs)} 個 7L 核心母帶檔案: {[os.path.basename(f) for f in existing_refs]}")

    sample_files = list(existing_refs)

    # 2. 如果指定合成新語句，調用 local_xiaoyi_service 進行練習
    if synthesize_new:
        try:
            safe_print("✨ 正在調用本地 GPT-SoVITS 進行多語句發音練習...")
            from local_xiaoyi_service import init_gpt_sovits, run as run_tts
            init_gpt_sovits()
            practice_texts = [
                "哈囉老爸，我是小依，今天過得開心嗎？",
                "這是我自己的聲音練習樣本喔，要好好記住我。",
                "隨時準備為老爸服務，彈琴、唱歌、聊天都沒問題！"
            ]
            out_dir = os.path.join(PROJECT_ROOT, "data", "tts_practice")
            os.makedirs(out_dir, exist_ok=True)
            for i, text in enumerate(practice_texts):
                safe_print(f"  [TTS 練習 {i+1}/{len(practice_texts)}] 合成台詞: 「{text}」")
                wav_path = os.path.join(out_dir, f"7l_practice_{i+1}.wav")
                try:
                    run_tts(text, "zh", "happy", wav_path)
                    if os.path.exists(wav_path):
                        sample_files.append(wav_path)
                except Exception as e:
                    safe_print(f"  ⚠️ 合成樣本 {i+1} 失敗: {e}")
        except Exception as e:
            safe_print(f"⚠️ 本地 TTS 即時合成練習跳過 (直接使用現有母帶): {e}")

    # 3. 執行特徵提煉
    success = voiceprint_verifier.train_or_calibrate_7l_from_tts(ref_paths=sample_files, max_samples=15)
    
    if success:
        safe_print("=" * 60)
        safe_print(f"🎉 7L 聲紋學習完成！總計加載 {len(voiceprint_verifier.anchor_7l_embeddings)} 組特徵向量。")
        
        # 4. 驗證比對 (自我測試)
        if existing_refs:
            test_file = existing_refs[0]
            is_7l, score = voiceprint_verifier.verify_is_7l(test_file)
            safe_print(f"🧪 [自我驗證測試] 測試 7L 自身母帶 ({os.path.basename(test_file)}):")
            safe_print(f"   ➔ 是否辨識為 7L: {'✅ 是' if is_7l else '❌ 否'} (相似度分數: {score:.4f})")

        # 5. 老爸音檔交叉驗證 (確認不會誤殺老爸)
        dad_samples = glob.glob(os.path.join(PROJECT_ROOT, "data", "clean_voice_samples", "*.wav"))
        if dad_samples:
            dad_test = dad_samples[0]
            is_7l_for_dad, dad_as_7l_score = voiceprint_verifier.verify_is_7l(dad_test)
            safe_print(f"🧪 [交叉排除測試] 測試老爸樣本 ({os.path.basename(dad_test)}):")
            safe_print(f"   ➔ 是否被誤判為 7L: {'⚠️ 誤判' if is_7l_for_dad else '✅ 正常放行 (非 7L)'} (與 7L 相似度: {dad_as_7l_score:.4f})")
        safe_print("=" * 60)
    else:
        safe_print("❌ 聲紋學習未完成，請檢查音訊檔案是否存在。")

if __name__ == "__main__":
    synthesize = "--synthesize" in sys.argv
    train_7l_voiceprint(synthesize_new=synthesize)
