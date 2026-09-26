import os
import sys
import subprocess
import soundfile as sf
import torch
import librosa

sys.path.append(os.path.join(os.path.dirname(__file__), "services", "rvc"))
os.environ["rmvpe_root"] = os.path.abspath("models/rvc")

from test_rvc_fixed import convert_rvc_fixed

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"

# 1. 準備 Cateek 女版 NGGYU 副歌 (42s ~ 64s, 22秒)
cateek_voc = "songs_library/cover_cache/htdemucs/cateek_test/vocals.wav"
cateek_inst = "songs_library/cover_cache/htdemucs/cateek_test/no_vocals.wav"

c_clip_voc = "songs_library/cover_cache/cateek_voc_42_64.wav"
c_clip_inst = "songs_library/cover_cache/cateek_inst_42_64.wav"

if os.path.exists(cateek_voc):
    subprocess.run([
        FFMPEG, "-y",
        "-ss", "42", "-t", "22",
        "-i", cateek_voc,
        "-ar", "16000", c_clip_voc
    ], capture_output=True)
    
    subprocess.run([
        FFMPEG, "-y",
        "-ss", "42", "-t", "22",
        "-i", cateek_inst,
        "-ar", "44100", c_clip_inst
    ], capture_output=True)

# 2. 準備千本櫻副歌 (和樂器優子版, 55s ~ 85s, 30秒)
wag_voc = "songs_library/cover_cache/wag_voc_chorus.wav"
wag_inst = "songs_library/cover_cache/wag_inst_chorus.wav"

# 3. 準備王心凌《愛你》副歌 (45s ~ 75s, 30秒)
cyndi_voc = "songs_library/cover_cache/cyndi_voc_chorus.wav"
cyndi_inst = "songs_library/cover_cache/cyndi_inst_chorus.wav"

print("🚀 開始製作【7L 唯一官方音色・全曲目統一演唱會】：可可 (Keke) 音色...")

# 轉換 1: NGGYU (英語)
if os.path.exists(c_clip_voc):
    convert_rvc_fixed(c_clip_voc, c_clip_inst, "songs_library/7L_Unified_Keke_NGGYU_Chorus.mp3", "keke", key=0, index_rate=0.75)

# 轉換 2: 千本櫻 (日語)
if os.path.exists(wag_voc):
    convert_rvc_fixed(wag_voc, wag_inst, "songs_library/7L_Unified_Keke_Senbonzakura_Chorus.mp3", "keke", key=0, index_rate=0.75)

# 轉換 3: 愛你 (中文)
if os.path.exists(cyndi_voc):
    convert_rvc_fixed(cyndi_voc, cyndi_inst, "songs_library/7L_Unified_Keke_AiNi_Chorus.mp3", "keke", key=0, index_rate=0.75)

print("🎉 【7L 統一音色專題】生成完畢！")
