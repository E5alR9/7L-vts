import os
import sys
import time
import subprocess
import soundfile as sf
import torch
import librosa

sys.path.append(os.path.join(os.path.dirname(__file__), "services", "rvc"))

from infer.module.models import SynthesizerTrnMs768NSFsid
from infer.hubert import load_hubert_model
from infer.vc.pipeline import Pipeline

class DummyConfig:
    def __init__(self, device="cuda:0", is_half=False):
        self.device = device
        self.is_half = is_half
        self.x_pad = 3
        self.x_query = 10
        self.x_center = 60
        self.x_max = 65

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
device = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"🚀 初始化神經語音轉換引擎 (設備: {device})...")

hubert_model = load_hubert_model(device, is_half=False)

def run_conversion(vocal_clip_in, inst_clip_in, out_mp3, model_path, index_path, key=0, index_rate=0.88):
    t0 = time.time()
    cpt = torch.load(model_path, map_location="cpu")
    config = cpt["config"]
    tgt_sr = config[-1]
    config[-3] = cpt["weight"]["emb_g.weight"].shape[0]
    
    net_g = SynthesizerTrnMs768NSFsid(*config, is_half=False)
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval().to(device)
    
    cfg = DummyConfig(device=device, is_half=False)
    pipeline = Pipeline(tgt_sr, cfg)
    
    audio, sr = librosa.load(vocal_clip_in, sr=16000)
    
    times = [0, 0, 0]
    sid = 0
    audio_opt = pipeline.pipeline(
        hubert_model,
        net_g,
        sid,
        audio,
        times,
        key,
        "pm",
        index_path,
        index_rate,
        cpt.get("f0", 1),
        tgt_sr,
        tgt_sr,
        0.25,
        "v2",
        0.33,
    )
    
    temp_voc = out_mp3 + ".temp_voc.wav"
    sf.write(temp_voc, audio_opt, tgt_sr)
    
    # 混音伴奏 (若 key != 0，伴奏是否移調？先不移調伴奏，或微調)
    # 人聲音量 1.25，伴奏 0.92
    cmd_mix = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", inst_clip_in,
        "-filter_complex", "[0:a]volume=1.28[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_mix, capture_output=True)
    if os.path.exists(temp_voc):
        os.remove(temp_voc)
    print(f"✨ 已生成: {out_mp3} (key={key}, 耗時: {time.time()-t0:.2f}s, 大小: {os.path.getsize(out_mp3)} bytes)")

def main():
    index_file = "dataset/xiaoyi_7L/xiaoyi_7L.index"
    
    # 1. Told You So (Christopher) - 經典副歌段落 30s ~ 50s (20秒)
    tys_voc_full = "songs_library/cover_cache/htdemucs/Christopher_Told_You_So_raw/vocals.wav"
    tys_inst_full = "songs_library/cover_cache/htdemucs/Christopher_Told_You_So_raw/no_vocals.wav"
    
    tys_voc_clip = "songs_library/test_ai_cover/tys_voc_30_50.wav"
    tys_inst_clip = "songs_library/test_ai_cover/tys_inst_30_50.wav"
    
    subprocess.run([FFMPEG, "-y", "-ss", "30", "-t", "20", "-i", tys_voc_full, "-ar", "16000", "-ac", "1", tys_voc_clip], capture_output=True)
    subprocess.run([FFMPEG, "-y", "-ss", "30", "-t", "20", "-i", tys_inst_full, "-ar", "44100", tys_inst_clip], capture_output=True)
    
    # 生成測試方案 1: Told You So - 原調 0 移調 (純女聲聲學神經轉換 + Xiaoyi 特徵庫)
    run_conversion(
        tys_voc_clip, tys_inst_clip,
        "songs_library/7L_ToldYouSo_AI_Pitch0_Xiaoyi.mp3",
        "models/rvc/weights/女声-云儿青春.pth",
        index_file,
        key=0,
        index_rate=0.88
    )
    
    # 生成測試方案 2: Told You So - 微調 +1.5 半音 (偏自然甜美少女聲線 + Xiaoyi 特徵庫)
    run_conversion(
        tys_voc_clip, tys_inst_clip,
        "songs_library/7L_ToldYouSo_AI_Pitch1.5_Xiaoyi.mp3",
        "models/rvc/weights/女声-云儿青春.pth",
        index_file,
        key=1.5,
        index_rate=0.88
    )
    
    # 生成測試方案 3: Told You So - 婉心柔和聲線 (原調 0 移調 + Xiaoyi 特徵庫)
    run_conversion(
        tys_voc_clip, tys_inst_clip,
        "songs_library/7L_ToldYouSo_AI_Wanxin_Pitch0_Xiaoyi.mp3",
        "models/rvc/weights/女声-婉心.pth",
        index_file,
        key=0,
        index_rate=0.88
    )
    
    # 2. So Far Away (Martin Garrix) - Jamie Scott 男聲段落 15s ~ 35s (20秒)
    sfa_voc_full = "songs_library/cover_cache/htdemucs/Martin_Garrix_So_Far_Away_raw/vocals.wav"
    sfa_inst_full = "songs_library/cover_cache/htdemucs/Martin_Garrix_So_Far_Away_raw/no_vocals.wav"
    
    sfa_voc_clip = "songs_library/test_ai_cover/sfa_voc_15_35.wav"
    sfa_inst_clip = "songs_library/test_ai_cover/sfa_inst_15_35.wav"
    
    subprocess.run([FFMPEG, "-y", "-ss", "15", "-t", "20", "-i", sfa_voc_full, "-ar", "16000", "-ac", "1", sfa_voc_clip], capture_output=True)
    subprocess.run([FFMPEG, "-y", "-ss", "15", "-t", "20", "-i", sfa_inst_full, "-ar", "44100", sfa_inst_clip], capture_output=True)
    
    run_conversion(
        sfa_voc_clip, sfa_inst_clip,
        "songs_library/7L_SoFarAway_AI_Pitch0_Xiaoyi.mp3",
        "models/rvc/weights/女声-云儿青春.pth",
        index_file,
        key=0,
        index_rate=0.88
    )

if __name__ == "__main__":
    main()
