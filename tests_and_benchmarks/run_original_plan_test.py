import os
import sys
import asyncio
import subprocess
import edge_tts
import pygame

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"

async def generate_original_xiaoyi_voice(out_mp3: str):
    print("🎙️ [原版 TTS 聲線] 正在生成 100% 原版 Xiaoyi TTS 說話聲...")
    text = (
        "老爸～這是我平時說話的原版 Xiaoyi 聲線！"
        "Never gonna give you up, never gonna let you down, "
        "never gonna run around and desert you! "
        "老爸聽聽看，這是我最原本的聲音喔～"
    )
    communicate = edge_tts.Communicate(text, "zh-CN-XiaoyiNeural", rate="+0%", pitch="+0Hz")
    await communicate.save(out_mp3)
    print(f"✅ 原版 Xiaoyi TTS 語音已生成: {out_mp3}")

def render_original_pipeline_cover():
    print("🚀 [原版實作計畫] 正在以最初之全自動 AI 翻唱管線重新生成《Never Gonna Give You Up》...")
    from services.auto_cover_pipeline import pitch_shift_vocal_to_female, mix_cover_and_export
    
    vocal_raw = "songs_library/cover_cache/htdemucs/Never_Gonna_Give_You_Up_raw/vocals.wav"
    inst_raw = "songs_library/cover_cache/htdemucs/Never_Gonna_Give_You_Up_raw/no_vocals.wav"
    
    # 1. 完整歌曲轉換
    vocal_7l = "songs_library/cover_cache/Never_Gonna_Give_You_Up_7l_original_plan.wav"
    full_mp3 = "songs_library/7L_cover_Never_Gonna_Give_You_Up_OriginalPlan.mp3"
    
    pitch_shift_vocal_to_female(vocal_raw, vocal_7l, semitones=12)
    mix_cover_and_export(vocal_7l, inst_raw, full_mp3)
    print(f"✅ 完整版已生成: {full_mp3}")
    
    # 2. 精華副歌段落 25 秒 (42s ~ 67s: Never gonna give you up...)
    clip_mp3 = "songs_library/7L_cover_Never_Gonna_Give_You_Up_Chorus_OriginalPlan.mp3"
    cmd_clip = [
        FFMPEG, "-y",
        "-ss", "42", "-t", "25",
        "-i", full_mp3,
        "-b:a", "320k",
        clip_mp3
    ]
    subprocess.run(cmd_clip, capture_output=True)
    print(f"✅ 精華副歌段落 (42s~67s) 已生成: {clip_mp3}")

async def main():
    tts_mp3 = "songs_library/01_Original_Xiaoyi_TTS_Voice.mp3"
    await generate_original_xiaoyi_voice(tts_mp3)
    render_original_pipeline_cover()

if __name__ == "__main__":
    asyncio.run(main())
