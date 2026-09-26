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
from test_rvc_rmvpe_senbonzakura import DummyConfig

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
device = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"🚀 初始化修正後的 ContentVec + RMVPE 轉音引擎 (設備: {device})...")

hubert_model = load_hubert_model(device, is_half=False)

def convert_rvc_fixed(vocal_in, inst_in, out_mp3, model_name, key=0, index_rate=0.75):
    t0 = time.time()
    model_path = f"models/rvc/weights/{model_name}.pth"
    index_path = f"models/rvc/indices/{model_name}.index"
    
    cpt = torch.load(model_path, map_location="cpu")
    config = cpt["config"]
    tgt_sr = config[-1]
    config[-3] = cpt["weight"]["emb_g.weight"].shape[0]
    
    net_g = SynthesizerTrnMs768NSFsid(*config, is_half=False)
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval().to(device)
    
    cfg = DummyConfig(device=device, is_half=False)
    pipeline = Pipeline(tgt_sr, cfg)
    
    audio, sr = librosa.load(vocal_in, sr=16000)
    times = [0, 0, 0]
    sid = 0
    
    print(f"⚡ 正在進行修復後 RVC 轉換: {out_mp3} (模型={model_name}, key={key}, index_rate={index_rate})...")
    audio_opt = pipeline.pipeline(
        hubert_model,
        net_g,
        sid,
        audio,
        times,
        key,
        "rmvpe",
        index_path if os.path.exists(index_path) else "",
        index_rate,
        cpt.get("f0", 1),
        tgt_sr,
        tgt_sr,
        0.25,
        "v2",
        0.33,
    )
    
    temp_voc = out_mp3 + ".temp.wav"
    sf.write(temp_voc, audio_opt, tgt_sr)
    
    cmd_mix = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", inst_in,
        "-filter_complex", "[0:a]volume=1.25,equalizer=f=3200:t=q:w=1.2:g=1.5[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_mix, capture_output=True)
    if os.path.exists(temp_voc):
        os.remove(temp_voc)
    print(f"🎉 生成成功: {out_mp3} (耗時: {time.time()-t0:.2f}s, 大小: {os.path.getsize(out_mp3)} bytes)")

if __name__ == "__main__":
    # 1. 測試千本櫻 (和樂器優子版，無Ado撕吼)
    wag_voc = "songs_library/cover_cache/wag_voc_chorus.wav"
    wag_inst = "songs_library/cover_cache/wag_inst_chorus.wav"
    if os.path.exists(wag_voc):
        convert_rvc_fixed(wag_voc, wag_inst, "songs_library/7L_FixedRVC_千本櫻_可可_Chorus.mp3", "keke", key=0, index_rate=0.75)
        convert_rvc_fixed(wag_voc, wag_inst, "songs_library/7L_FixedRVC_千本櫻_雲兒_Chorus.mp3", "yuner", key=0, index_rate=0.75)

    # 2. 測試王心凌《愛你》副歌
    cyndi_voc = "songs_library/cover_cache/cyndi_voc_chorus.wav"
    cyndi_inst = "songs_library/cover_cache/cyndi_inst_chorus.wav"
    if os.path.exists(cyndi_voc):
        convert_rvc_fixed(cyndi_voc, cyndi_inst, "songs_library/7L_FixedRVC_愛你_可可_Chorus.mp3", "keke", key=0, index_rate=0.75)
        convert_rvc_fixed(cyndi_voc, cyndi_inst, "songs_library/7L_FixedRVC_愛你_雲兒_Chorus.mp3", "yuner", key=0, index_rate=0.75)

