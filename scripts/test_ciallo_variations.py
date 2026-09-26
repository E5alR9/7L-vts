# -*- coding: utf-8 -*-
import os, sys, subprocess

sys.path.insert(0, r"C:\Users\qiwai")
sys.path.insert(0, r"C:\Users\qiwai\GPT-SoVITS")
sys.path.insert(0, r"C:\Users\qiwai\GPT-SoVITS\GPT_SoVITS")

import local_xiaoyi_service

HOT_REP_PATH = r"C:\Users\qiwai\GPT-SoVITS\GPT_SoVITS\text\engdict-hot.rep"

CANDIDATES = {
    "A_glide_smooth":       "CIALLO CH Y AA0 L OW1 OW0",       # 滑音連貫：Y半元音平滑過渡，cia極快，llo平滑拖音
    "B_quick_long_smooth":  "CIALLO CH AA0 L OW1 OW0 OW0",   # 快速cia + 單重音平滑不中斷超長拖音
    "C_ultra_fast_cia":     "CIALLO CH AH0 L OW1 OW0",       # 極速弱化cia + 飽滿拉長llo
    "D_natural_clean":      "CIALLO CH AA0 L OW1",           # 自然緊湊版（無多重音干擾，一氣呵成）
    "E_japanese_charo":     "CIALLO ch a r o o",             # 日語芳乃原版連貫羅馬音（完全無輔音阻斷）
}

def generate_variation(name, rep_line):
    # 寫入 hot.rep
    with open(HOT_REP_PATH, "w", encoding="utf-8") as f:
        f.write(rep_line + "\n")
    
    # 清理 english.py 記憶體快取以確保重新讀取 hot.rep
    from text import english
    english._g2p.cmu = english.get_dict()
    
    test_text = "Ciallo～(∠・ω<)⌒★ 老爸好！"
    print(f"\n>>> 正在生成方案 [{name}] : {rep_line}")
    wav_bytes = local_xiaoyi_service.synthesize_xiaoyi_bytes(test_text)
    if not wav_bytes:
        print(f"❌ [{name}] 合成失敗")
        return None
    
    wav_path = rf"C:\Users\qiwai\ciallo_{name}.wav"
    mp3_path = rf"C:\Users\qiwai\ciallo_{name}.mp3"
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)
    
    subprocess.run(["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", mp3_path], capture_output=True)
    print(f"✅ 生成成功: {mp3_path}")
    return mp3_path

if __name__ == "__main__":
    # 預熱 pipeline
    local_xiaoyi_service.init_gpt_sovits()
    
    for name, rep_line in CANDIDATES.items():
        generate_variation(name, rep_line)
    
    print("\n🎉 全部候選版本已生成完畢！")
