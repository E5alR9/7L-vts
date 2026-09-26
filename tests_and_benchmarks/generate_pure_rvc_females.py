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
print(f"🚀 初始化純 RVC 女聲翻唱引擎 (設備: {device})...")

hubert_model = load_hubert_model(device, is_half=False)

def convert_rvc_pure_female(
    vocal_clip_in: str,
    inst_clip_in: str,
    out_mp3: str,
    model_name: str,
    key: int = 12,
    index_rate: float = 0.75,
    f0_method: str = "pm"
):
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
        f0_method,
        index_path if os.path.exists(index_path) else "",
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
    
    # 混音伴奏
    cmd_mix = [
        FFMPEG, "-y",
        "-i", temp_voc,
        "-i", inst_clip_in,
        "-filter_complex", "[0:a]volume=1.3[v];[1:a]volume=0.92[i];[v][i]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-b:a", "320k",
        out_mp3
    ]
    subprocess.run(cmd_mix, capture_output=True)
    if os.path.exists(temp_voc):
        os.remove(temp_voc)
    print(f"✨ 已生成: {out_mp3} ({model_name}, key={key:+d}, 耗時: {time.time()-t0:.2f}s)")

def main():
    # 1. Told You So (Christopher) - 副歌 30s ~ 50s (20秒)
    tys_voc_clip = "songs_library/test_ai_cover/tys_voc_30_50.wav"
    tys_inst_clip = "songs_library/test_ai_cover/tys_inst_30_50.wav"
    
    print("\n=== 生成 Christopher《Told You So》純 RVC 女聲翻唱版本 ===")
    # 方案 A: 雲兒青春 (女轉男經典 +12 半音)
    convert_rvc_pure_female(tys_voc_clip, tys_inst_clip, "songs_library/7L_RVC_ToldYouSo_Yuner_KeyPlus12.mp3", "yuner", key=12)
    
    # 方案 B: 可可 (甜美可愛少女音 +12 半音)
    convert_rvc_pure_female(tys_voc_clip, tys_inst_clip, "songs_library/7L_RVC_ToldYouSo_Keke_KeyPlus12.mp3", "keke", key=12)
    
    # 方案 C: 婉心 (溫柔甜美女聲 +12 半音)
    convert_rvc_pure_female(tys_voc_clip, tys_inst_clip, "songs_library/7L_RVC_ToldYouSo_Wanxin_KeyPlus12.mp3", "wanxin", key=12)
    
    # 方案 D: 草莓 (軟萌治癒甜妹音 +12 半音)
    convert_rvc_pure_female(tys_voc_clip, tys_inst_clip, "songs_library/7L_RVC_ToldYouSo_Caomei_KeyPlus12.mp3", "caomei", key=12)
    
    # 方案 E: 學姐 (清澈靈動音 +12 半音)
    convert_rvc_pure_female(tys_voc_clip, tys_inst_clip, "songs_library/7L_RVC_ToldYouSo_Xuejie_KeyPlus12.mp3", "xuejie", key=12)
    
    # 方案 F: 可可 (原調 0 半音，不升八度對比)
    convert_rvc_pure_female(tys_voc_clip, tys_inst_clip, "songs_library/7L_RVC_ToldYouSo_Keke_Key0.mp3", "keke", key=0)

    # 2. So Far Away (Martin Garrix) - Jamie Scott 男聲段落 15s ~ 35s (20秒)
    sfa_voc_clip = "songs_library/test_ai_cover/sfa_voc_15_35.wav"
    sfa_inst_clip = "songs_library/test_ai_cover/sfa_inst_15_35.wav"
    
    print("\n=== 生成 Martin Garrix《So Far Away》純 RVC 女聲翻唱版本 ===")
    convert_rvc_pure_female(sfa_voc_clip, sfa_inst_clip, "songs_library/7L_RVC_SoFarAway_Keke_KeyPlus12.mp3", "keke", key=12)
    convert_rvc_pure_female(sfa_voc_clip, sfa_inst_clip, "songs_library/7L_RVC_SoFarAway_Yuner_KeyPlus12.mp3", "yuner", key=12)

if __name__ == "__main__":
    main()
