import os
import sys
import subprocess
import time
import shutil

sys.path.append(os.path.join(os.path.dirname(__file__), "services", "rvc"))
os.environ["rmvpe_root"] = os.path.abspath("models/rvc")

from services.neural_voice_converter import convert_vocal_to_xiaoyi
from services.auto_cover_pipeline import mix_cover_and_export

FFMPEG = os.getenv("FFMPEG_EXE") or (r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe") else "ffmpeg")

songs = [
    {
        "name": "Never_Gonna_Give_You_Up",
        "title": "Never Gonna Give You Up",
        "voc": "songs_library/cover_cache/htdemucs/cateek_test/vocals.wav",
        "inst": "songs_library/cover_cache/htdemucs/cateek_test/no_vocals.wav",
        "chorus_start": "42",
        "chorus_dur": "30"
    },
    {
        "name": "千本櫻",
        "title": "千本櫻",
        "voc": "songs_library/cover_cache/htdemucs/千本櫻_和樂器樂團神級版_raw/vocals.wav",
        "inst": "songs_library/cover_cache/htdemucs/千本櫻_和樂器樂團神級版_raw/no_vocals.wav",
        "chorus_start": "55",
        "chorus_dur": "30"
    },
    {
        "name": "愛你",
        "title": "愛你",
        "voc": "songs_library/cover_cache/htdemucs/cyndi_love_you_raw/vocals.wav",
        "inst": "songs_library/cover_cache/htdemucs/cyndi_love_you_raw/no_vocals.wav",
        "chorus_start": "45",
        "chorus_dur": "30"
    }
]

def main():
    print("🍓 開始為 7L 灌錄官方【草莓（Caomei）正式版單曲庫】...")

    for s in songs:
        s_name = s["name"]
        full_mp3 = f"songs_library/7L_cover_{s_name}.mp3"
        chorus_mp3 = f"songs_library/7L_cover_{s_name}_Chorus.mp3"
        
        print(f"\n🎙️ 正在錄製 7L 官方草莓正式單曲: 《{s['title']}》...")
        temp_caomei_voc = f"songs_library/cover_cache/{s_name}_caomei_vocal.wav"
        
        # 轉換整首歌曲為草莓音色
        ok = convert_vocal_to_xiaoyi(
            s["voc"],
            temp_caomei_voc,
            key=0.0,
            model_name="caomei",
            index_rate=0.75
        )
        
        if ok and os.path.exists(temp_caomei_voc):
            # 混音產出完整版 MP3
            mix_cover_and_export(temp_caomei_voc, s["inst"], full_mp3)
            print(f"✅ 完整版生成完成: {full_mp3} ({os.path.getsize(full_mp3)} bytes)")
            
            # 剪輯 30 秒高潮副歌
            cmd_clip = [
                FFMPEG, "-y",
                "-ss", s["chorus_start"], "-t", s["chorus_dur"],
                "-i", full_mp3,
                "-b:a", "320k",
                chorus_mp3
            ]
            subprocess.run(cmd_clip, capture_output=True)
            print(f"✅ 副歌精華生成完成: {chorus_mp3} ({os.path.getsize(chorus_mp3)} bytes)")
            
            if os.path.exists(temp_caomei_voc):
                os.remove(temp_caomei_voc)

    print("\n🎉 7L 官方三大旗艦單曲（草莓音色版）全部製作完畢！")


if __name__ == "__main__":
    main()
