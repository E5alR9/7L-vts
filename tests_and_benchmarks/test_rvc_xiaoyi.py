import os
import sys
import time
import traceback
import numpy as np
import soundfile as sf
import torch

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

def convert_voice(
    input_wav: str,
    model_pth: str,
    index_file: str,
    output_wav: str,
    f0_up_key: int = 0,
    index_rate: float = 0.85,
    f0_method: str = "pm",
    device: str = "cuda:0",
    is_half: bool = False,
):
    print(f"🚀 [7L 神經聲線轉換] 開始載入模型與 Xiaoyi 特徵庫...")
    t0 = time.time()
    
    # 1. 載入 RVC 權重
    cpt = torch.load(model_pth, map_location="cpu")
    config = cpt["config"]
    tgt_sr = config[-1]
    config[-3] = cpt["weight"]["emb_g.weight"].shape[0]
    
    net_g = SynthesizerTrnMs768NSFsid(*config, is_half=is_half)
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval().to(device)
    if is_half:
        net_g = net_g.half()
        
    print(f"✅ [生成器就緒] 採樣率: {tgt_sr}Hz, 設備: {device}")
    
    # 2. 載入 HuBERT
    hubert_model = load_hubert_model(device, is_half=is_half)
    print(f"✅ [HuBERT 聲學特徵模型就緒]")
    
    # 3. 初始化 Pipeline
    cfg = DummyConfig(device=device, is_half=is_half)
    pipeline = Pipeline(tgt_sr, cfg)
    
    # 4. 讀取音訊
    import librosa
    audio, sr = librosa.load(input_wav, sr=16000)
    print(f"🎵 載入輸入人聲: {input_wav}, 長度: {len(audio)/16000:.2f}s")
    
    # 5. 推理轉換
    times = [0, 0, 0]
    sid = 0
    resample_sr = tgt_sr
    rms_mix_rate = 0.25
    version = "v2"
    protect = 0.33
    if_f0 = cpt.get("f0", 1)
    
    print(f"⚡ 正在透過 Xiaoyi 聲學特徵索引進行聲帶共鳴置換 (index_rate={index_rate}, key={f0_up_key})...")
    audio_opt = pipeline.pipeline(
        hubert_model,
        net_g,
        sid,
        audio,
        times,
        f0_up_key,
        f0_method,
        index_file,
        index_rate,
        if_f0,
        tgt_sr,
        resample_sr,
        rms_mix_rate,
        version,
        protect,
    )
    
    # 6. 輸出音訊
    sf.write(output_wav, audio_opt, tgt_sr)
    print(f"🎉 [轉換成功] 已生成 7L 專屬人聲音軌: {output_wav} (耗時: {time.time()-t0:.2f}s)")
    return True

if __name__ == "__main__":
    vocal_in = "songs_library/cover_cache/htdemucs/Christopher_Told_You_So_raw/vocals.wav"
    model_pth = "models/rvc/weights/xiaoyi.pth"
    index_file = "models/rvc/indices/xiaoyi.index"
    
    os.makedirs("songs_library/test_ai_cover", exist_ok=True)
    temp_clip_in = "songs_library/test_ai_cover/tys_clip_15s_in.wav"
    vocal_out = "songs_library/test_ai_cover/tys_xiaoyi_vocal.wav"
    
    # 切割 Christopher Told You So 最精彩的 20 秒 (從第 30 秒副歌開始)
    import subprocess
    cmd_clip = [
        r"C:\ffmpeg\bin\ffmpeg.exe", "-y",
        "-ss", "30", "-t", "20",
        "-i", vocal_in,
        "-ar", "16000", "-ac", "1",
        temp_clip_in
    ]
    subprocess.run(cmd_clip, capture_output=True)
    
    success = convert_voice(
        input_wav=temp_clip_in,
        model_pth=model_pth,
        index_file=index_file,
        output_wav=vocal_out,
        f0_up_key=0, # 不調高音，原調轉換！
        index_rate=0.88,
        f0_method="pm"
    )
    
    if success:
        # 混音伴奏
        inst_in = "songs_library/cover_cache/htdemucs/Christopher_Told_You_So_raw/no_vocals.wav"
        temp_inst = "songs_library/test_ai_cover/tys_inst_clip.wav"
        subprocess.run([
            r"C:\ffmpeg\bin\ffmpeg.exe", "-y",
            "-ss", "30", "-t", "20",
            "-i", inst_in,
            "-ar", "44100", temp_inst
        ], capture_output=True)
        
        final_mp3 = "songs_library/7L_cover_Told_You_So_XiaoyiAI_test.mp3"
        subprocess.run([
            r"C:\ffmpeg\bin\ffmpeg.exe", "-y",
            "-i", vocal_out,
            "-i", temp_inst,
            "-filter_complex", "[0:a]volume=1.2[v];[1:a]volume=0.9[i];[v][i]amix=inputs=2:duration=first[out]",
            "-map", "[out]",
            "-b:a", "320k",
            final_mp3
        ], capture_output=True)
        print("Final mixed song created:", final_mp3, "Size:", os.path.getsize(final_mp3) if os.path.exists(final_mp3) else 0)
