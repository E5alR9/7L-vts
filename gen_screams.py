# -*- coding: utf-8 -*-
"""
電擊叫聲音效庫管理與試聽工具
支援：
1. 試聽全部/單獨叫聲（動漫嬌嗔、真人驚呼、崩潰討饒、曉伊原生短促驚叫等）
2. 一鍵切換隨機播放池模式（全開隨機、純動漫日系隨機、純中文少女隨機、自訂挑選）
3. 實時寫入 data/sounds_7L_clean/shock_sound_config.json
"""
import os
import sys
import json
import glob
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "sounds_7L_clean")
CONFIG_PATH = os.path.join(DATA_DIR, "shock_sound_config.json")

# 音效總目錄與風格分類
SOUND_LIBRARY = {
    "light": {
        "1": {"file": "shocks_light/light_1_aaa.mp3", "name": "曉伊原聲・啊啊啊好麻（中文軟萌）"},
        "2": {"file": "shocks_light/light_2_kyaa.mp3", "name": "曉伊原聲・呀啊啊（嬌嗔微觸電）"},
        "3": {"file": "shocks_light/light_3_burst.mp3", "name": "曉伊原聲・短促急喘（超快反應）"},
        "4": {"file": "shocks_light/light_5_short.mp3", "name": "曉伊原聲・哼嗯啊（輕微電到）"},
        "5": {"file": "7L_anime_pure_kyaa.wav", "name": "日系聲優・Kyaa~ 純潔嬌呼"},
        "6": {"file": "7L_anime_kyatt.wav", "name": "日系聲優・Kyatt 短促高音受驚"},
        "7": {"file": "7L_anime_itatt.wav", "name": "日系聲優・Itatt 好痛痛"},
        "8": {"file": "7L_anime_iyatt.wav", "name": "日系聲優・Iyatt 不要電我"},
        "9": {"file": "opt_light_high.mp3", "name": "萌系高音・+8Hz 電音嬌喘"},
    },
    "heavy": {
        "1": {"file": "shocks_heavy/heavy_1_scream.mp3", "name": "曉伊原聲・痛痛痛爆裂尖叫"},
        "2": {"file": "shocks_heavy/heavy_2_stop.mp3", "name": "曉伊原聲・快停下不要電了"},
        "3": {"file": "shocks_heavy/heavy_3_crying.mp3", "name": "曉伊原聲・哭腔委屈求饒"},
        "4": {"file": "shocks_heavy/heavy_4_long.mp3", "name": "曉伊原聲・長電流全身發軟尖叫"},
        "5": {"file": "7L_anime_hyaa.wav", "name": "日系聲優・Hyaa~ 強受擊崩潰音"},
        "6": {"file": "7L_anime_moudame.wav", "name": "日系聲優・Moudame 已經不行了"},
        "7": {"file": "7L_anime_princess_iyaa.wav", "name": "日系聲優・大小姐傲嬌不要啊"},
        "8": {"file": "7L_anime_chikara_dame.wav", "name": "日系聲優・沒力氣了全身發麻"},
        "9": {"file": "opt_heavy_high.mp3", "name": "萌系重電・高頻穿透長尖叫"},
    }
}

PRESET_POOLS = {
    "all": {
        "name": "💥 究極全開隨機池（中文曉伊 + 日系動漫聲優 全員隨機亂鬥，百聽不膩）",
        "light": [SOUND_LIBRARY["light"][k]["file"] for k in SOUND_LIBRARY["light"]],
        "heavy": [SOUND_LIBRARY["heavy"][k]["file"] for k in SOUND_LIBRARY["heavy"]],
    },
    "anime": {
        "name": "🎀 純日系二次元動漫池（Kyaa / Hyaa / 傲嬌大小姐 討饒崩潰）",
        "light": [
            "7L_anime_pure_kyaa.wav",
            "7L_anime_kyatt.wav",
            "7L_anime_itatt.wav",
            "7L_anime_iyatt.wav"
        ],
        "heavy": [
            "7L_anime_hyaa.wav",
            "7L_anime_moudame.wav",
            "7L_anime_princess_iyaa.wav",
            "7L_anime_chikara_dame.wav"
        ]
    },
    "xiaoyi": {
        "name": "👧 純中文曉伊原生池（啊啊好麻 / 痛痛痛 / 哭腔委屈求饒，最真實陪伴感）",
        "light": [
            "shocks_light/light_1_aaa.mp3",
            "shocks_light/light_2_kyaa.mp3",
            "shocks_light/light_3_burst.mp3",
            "shocks_light/light_5_short.mp3"
        ],
        "heavy": [
            "shocks_heavy/heavy_1_scream.mp3",
            "shocks_heavy/heavy_2_stop.mp3",
            "shocks_heavy/heavy_3_crying.mp3",
            "shocks_heavy/heavy_4_long.mp3"
        ]
    }
}

def load_current_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(light_files, heavy_files, mode_name="custom"):
    cfg = {
        "enabled": True,
        "mode": mode_name,
        "light_sounds": light_files,
        "heavy_sounds": heavy_files
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print(f"✅ [配置已更新] 已將叫聲隨機播放清單儲存至: {CONFIG_PATH}")
    print(f"   - 微電刺激叫聲庫: {len(light_files)} 個音效隨機輪播")
    print(f"   - 強力電擊叫聲庫: {len(heavy_files)} 個音效隨機輪播")

def play_audio(relative_or_abs_path):
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    
    full_path = relative_or_abs_path if os.path.isabs(relative_or_abs_path) else os.path.join(DATA_DIR, relative_or_abs_path)
    if not os.path.exists(full_path):
        print(f"❌ 找不到音效檔: {full_path}")
        return
    
    chan = pygame.mixer.Channel(5)
    chan.set_volume(1.0)
    snd = pygame.mixer.Sound(full_path)
    chan.play(snd)
    while chan.get_busy():
        time.sleep(0.03)

def show_menu():
    print("=" * 60)
    print("⚡ 7L 電擊叫聲多音效隨機輪播管理面板 ⚡")
    print("=" * 60)
    print("\n【微電刺激候選清單 (Lv.1)】:")
    for k, v in SOUND_LIBRARY["light"].items():
        print(f"  [{k}] {v['name']} ({v['file']})")

    print("\n【強力電擊候選清單 (Lv.2)】:")
    for k, v in SOUND_LIBRARY["heavy"].items():
        print(f"  [{k}] {v['name']} ({v['file']})")

    print("\n【預設隨機組合方案 (推薦直接選)】:")
    print("  [A] 方案 A: 究極全開隨機池（中文曉伊 + 日系聲優 全員隨機輪播，次次不同！）")
    print("  [B] 方案 B: 純日系動漫池（Kyaa / Hyaa / 傲嬌大小姐 討饒崩潰）")
    print("  [C] 方案 C: 純中文曉伊原生池（啊啊好麻 / 痛痛痛 / 哭腔委屈求饒）")
    print("=" * 60)

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "menu"
    
    if action == "apply":
        preset = sys.argv[2] if len(sys.argv) > 2 else "all"
        if preset in ["a", "all"]:
            p = PRESET_POOLS["all"]
            save_config(p["light"], p["heavy"], "all_random")
        elif preset in ["b", "anime"]:
            p = PRESET_POOLS["anime"]
            save_config(p["light"], p["heavy"], "anime_random")
        elif preset in ["c", "xiaoyi"]:
            p = PRESET_POOLS["xiaoyi"]
            save_config(p["light"], p["heavy"], "xiaoyi_random")
        else:
            print(f"❌ 未知預設方案: {preset}")
            
    elif action == "play":
        target = sys.argv[2] if len(sys.argv) > 2 else "light/1"
        parts = target.split("/")
        category = parts[0]
        idx = parts[1] if len(parts) > 1 else "1"
        if category in SOUND_LIBRARY and idx in SOUND_LIBRARY[category]:
            item = SOUND_LIBRARY[category][idx]
            print(f"🔊 正在試聽: {item['name']}")
            play_audio(item["file"])
        else:
            # 直接當作路徑播放
            play_audio(target)
            
    else:
        show_menu()
