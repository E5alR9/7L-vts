import os
import sys
import time
import subprocess
import soundfile as sf
import torch
import librosa

sys.path.append(os.path.join(os.path.dirname(__file__), "services", "rvc"))
os.environ["rmvpe_root"] = os.path.abspath("models/rvc")

from infer.module.models import SynthesizerTrnMs768NSFsid
from infer.hubert import load_hubert_model
from infer.vc.pipeline import Pipeline
from test_rvc_rmvpe_senbonzakura import DummyConfig, convert_rvc

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
device = "cuda:0" if torch.cuda.is_available() else "cpu"

print("🔍 尋找和樂器樂團 (鈴華優子) 分離音軌...")
base_demucs = "songs_library/cover_cache/htdemucs"
wagakki_dir = None
for d in os.listdir(base_demucs):
    if "和樂器" in d or "M־" in d:
        wagakki_dir = os.path.join(base_demucs, d)
        break

print("和樂器目錄:", wagakki_dir)

if wagakki_dir:
    wag_voc = os.path.join(wagakki_dir, "vocals.wav")
    wag_inst = os.path.join(wagakki_dir, "no_vocals.wav")
    
    clip_wag_voc = "songs_library/cover_cache/wag_voc_chorus.wav"
    clip_wag_inst = "songs_library/cover_cache/wag_inst_chorus.wav"
    
    # 剪輯 55s ~ 85s (副歌)
    subprocess.run([
        FFMPEG, "-y",
        "-ss", "55", "-t", "30",
        "-i", wag_voc,
        "-ar", "16000", clip_wag_voc
    ], capture_output=True)
    
    subprocess.run([
        FFMPEG, "-y",
        "-ss", "55", "-t", "30",
        "-i", wag_inst,
        "-ar", "44100", clip_wag_inst
    ], capture_output=True)
    
    out_wag_keke = "songs_library/7L_RVC_千本櫻_和樂器優子唱腔_可可音色_Chorus.mp3"
    print("⚡ 正在轉換和樂器樂團 (無嘶吼、優雅詩吟版)...")
    convert_rvc(clip_wag_voc, clip_wag_inst, out_wag_keke, "keke", key=0, index_rate=0.85)

print("\n🚀 同步下載中文甜歌《愛你》（王心凌）進行語言與唱腔對比測試...")
# 下載王心凌《愛你》高音質音訊進行對比
cmd_dl = [
    "yt-dlp", "https://www.youtube.com/watch?v=FjId_ZkPjQk", # 王心凌 愛你 官方音訊
    "-x", "--audio-format", "wav",
    "--audio-quality", "0",
    "--postprocessor-args", "ffmpeg:-ar 44100 -ac 2",
    "-o", "songs_library/cover_cache/cyndi_love_you_raw.wav",
    "--no-playlist"
]
subprocess.run(cmd_dl, capture_output=True)

raw_cyndi = "songs_library/cover_cache/cyndi_love_you_raw.wav"
if os.path.exists(raw_cyndi):
    print("⚡ [GPU 分離] 啟用 Demucs 分離王心凌人聲與伴奏...")
    cmd_dem = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "-d", "cuda",
        "-o", "songs_library/cover_cache",
        raw_cyndi
    ]
    subprocess.run(cmd_dem, capture_output=True)
    
    cyndi_dem_dir = "songs_library/cover_cache/htdemucs/cyndi_love_you_raw"
    c_voc = os.path.join(cyndi_dem_dir, "vocals.wav")
    c_inst = os.path.join(cyndi_dem_dir, "no_vocals.wav")
    
    # 剪輯 45s ~ 75s (最經典副歌: 多愛你一點...)
    c_clip_voc = "songs_library/cover_cache/cyndi_voc_chorus.wav"
    c_clip_inst = "songs_library/cover_cache/cyndi_inst_chorus.wav"
    
    subprocess.run([
        FFMPEG, "-y",
        "-ss", "45", "-t", "30",
        "-i", c_voc,
        "-ar", "16000", c_clip_voc
    ], capture_output=True)
    
    subprocess.run([
        FFMPEG, "-y",
        "-ss", "45", "-t", "30",
        "-i", c_inst,
        "-ar", "44100", c_clip_inst
    ], capture_output=True)
    
    out_cyndi_keke = "songs_library/7L_RVC_愛你_王心凌_可可音色_Chorus.mp3"
    print("⚡ 正在轉換中文經典《愛你》-> 7L 可可音色...")
    convert_rvc(c_clip_voc, c_clip_inst, out_cyndi_keke, "keke", key=0, index_rate=0.85)
    print(f"🎉 中文甜歌生成完畢: {out_cyndi_keke}")
