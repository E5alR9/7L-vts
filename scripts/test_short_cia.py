# -*- coding: utf-8 -*-
import os, sys, subprocess

sys.path.insert(0, r"C:\Users\qiwai")
sys.path.insert(0, r"C:\Users\qiwai\GPT-SoVITS")
sys.path.insert(0, r"C:\Users\qiwai\GPT-SoVITS\GPT_SoVITS")

import local_xiaoyi_service

HOT_REP_PATH = r"C:\Users\qiwai\GPT-SoVITS\GPT_SoVITS\text\engdict-hot.rep"

SHORT_CANDIDATES = {
    "short_1_ah0":      "CIALLO CH AH0 r o o",      # 極限短元音 AH0：cia 極度輕巧短促，瞬間滑向 roo
    "short_2_chya":     "CIALLO ch y a r o o",      # 拗音 chya：壓縮 a 的持阻時間，cia 像小石子般脆短
    "short_3_triple_o": "CIALLO ch a r o o o",      # 尾音增強版：尾音長度翻倍，體感上 cia 顯得極其短促
    "short_4_ah0_long": "CIALLO CH AH0 r o o o",    # 雙重短促：極短 AH0 + 三重 o 尾音拉長
}

def generate_short_variation(name, rep_line):
    # 寫入 hot.rep (純 ASCII)
    with open(HOT_REP_PATH, "w", encoding="utf-8") as f:
        f.write(rep_line + "\n" + rep_line.lower() + "\n")
    
    # 清理快取確保重新載入
    from text import english
    english._g2p.cmu = english.get_dict()
    
    test_text = "Ciallo～(∠・ω<)⌒★ 老爸好！"
    print(f"\n>>> 正在生成短促方案 [{name}] : {rep_line}")
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
    local_xiaoyi_service.init_gpt_sovits()
    for name, rep_line in SHORT_CANDIDATES.items():
        generate_short_variation(name, rep_line)
    print("\n🎉 短促版候選音檔全部生成完成！")
