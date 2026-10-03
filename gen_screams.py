# -*- coding: utf-8 -*-
"""
電擊音效管理與調整工具
GPT-SoVITS 為口語/對話模型，電擊尖叫需使用調試好的高速音調或專屬動漫受擊音效。
"""
import os
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "sounds_7L_clean")

def set_scream_mode(mode: str = "local_tts"):
    """
    mode 選項:
    - 'local_tts' / 'xiaoyi' (預設、推薦): 本地 GPT-SoVITS 曉伊原生少女聲帶（微電：「啊啊啊！好麻！」/ 重電：「啊啊啊啊啊啊！痛痛痛！」）
    - 'pure_aaa': 本地 GPT-SoVITS 曉伊純「啊啊啊啊！」爆裂尖叫
    - 'classic': 經典高速八連叫 (調速版)
    - 'high_pitch': 萌系高音尖叫 (呀啊啊啊！+8Hz 高音)
    - 'anime_real': 真人動漫聲優音效
    """
    if mode in ["local_tts", "xiaoyi", "default"]:
        shutil.copyfile(os.path.join(DATA_DIR, "shocks_light", "light_1_aaa.mp3"), os.path.join(DATA_DIR, "test_a_8_pure.mp3"))
        shutil.copyfile(os.path.join(DATA_DIR, "shocks_heavy", "heavy_1_scream.mp3"), os.path.join(DATA_DIR, "shock_heavy_pure.mp3"))
        msg = " 已套用【本地 GPT-SoVITS 曉伊原生電擊叫聲：啊啊啊！好麻！】！"
    elif mode == "pure_aaa":
        shutil.copyfile(os.path.join(DATA_DIR, "shocks_light", "light_3_burst.mp3"), os.path.join(DATA_DIR, "test_a_8_pure.mp3"))
        shutil.copyfile(os.path.join(DATA_DIR, "shocks_heavy", "heavy_1_scream.mp3"), os.path.join(DATA_DIR, "shock_heavy_pure.mp3"))
        msg = " 已套用【本地 GPT-SoVITS 曉伊純「啊啊啊啊！」爆裂尖叫】！"
    elif mode == "classic":
        shutil.copyfile(os.path.join(DATA_DIR, "opt_light_classic.mp3"), os.path.join(DATA_DIR, "test_a_8_pure.mp3"))
        shutil.copyfile(os.path.join(DATA_DIR, "test_shock_heavy_pure.mp3"), os.path.join(DATA_DIR, "shock_heavy_pure.mp3"))
        msg = " 已套用【經典高速電擊叫聲】！"
    elif mode == "high_pitch":
        shutil.copyfile(os.path.join(DATA_DIR, "opt_light_high.mp3"), os.path.join(DATA_DIR, "test_a_8_pure.mp3"))
        shutil.copyfile(os.path.join(DATA_DIR, "opt_heavy_high.mp3"), os.path.join(DATA_DIR, "shock_heavy_pure.mp3"))
        msg = " 已套用【萌系高音電擊叫聲】！"
    elif mode == "anime_real":
        shutil.copyfile(os.path.join(DATA_DIR, "7L_anime_pure_kyaa.wav"), os.path.join(DATA_DIR, "test_a_8_pure.mp3"))
        shutil.copyfile(os.path.join(DATA_DIR, "7L_anime_hyaa.wav"), os.path.join(DATA_DIR, "shock_heavy_pure.mp3"))
        msg = " 已套用【動漫聲優受擊驚呼】！"
    else:
        msg = f" 未知模式: {mode}"
    print(msg)

def play_preview(mode: str = None):
    """直接播放指定模式（或當前套用模式）的叫聲供預覽"""
    import pygame
    import time
    if not pygame.mixer.get_init():
        pygame.mixer.init()

    if mode:
        set_scream_mode(mode)

    p_light = os.path.join(DATA_DIR, "test_a_8_pure.mp3")
    p_heavy = os.path.join(DATA_DIR, "shock_heavy_pure.mp3")

    channel = pygame.mixer.Channel(5)
    channel.set_volume(1.0)

    print("⚡ [試聽 1/2] 正在播放：Lv.1 微電刺激叫聲...")
    if os.path.exists(p_light):
        s = pygame.mixer.Sound(p_light)
        channel.play(s)
        while channel.get_busy():
            time.sleep(0.04)

    time.sleep(0.6)

    print("⚡⚡ [試聽 2/2] 正在播放：Lv.2 強力電擊處分叫聲...")
    if os.path.exists(p_heavy):
        s = pygame.mixer.Sound(p_heavy)
        channel.play(s)
        while channel.get_busy():
            time.sleep(0.04)

    print("✅ 預覽試聽結束！")

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if arg in ["preview", "play", "listen"]:
        target_mode = sys.argv[2] if len(sys.argv) > 2 else None
        play_preview(target_mode)
    else:
        set_scream_mode(arg)
        play_preview()
